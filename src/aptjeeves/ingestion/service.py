from __future__ import annotations

import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.service import AttachmentService
from aptjeeves.ingestion.fingerprint import conversation_id, message_fingerprint
from aptjeeves.ingestion.hashing import sha256_file
from aptjeeves.ingestion.normalizer import (
    NORMALIZER_VERSION,
    REDACTOR_VERSION,
    normalize_message,
)
from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.ingestion.vcard import parse_vcard
from aptjeeves.storage.models import ServiceContactUpsert, FactEvidenceInput
from aptjeeves.ingestion.parsers import (
    ParseResult,
    TELEGRAM_PARSER_VERSION,
    TelegramJsonParser,
    WHATSAPP_PARSER_VERSION,
    WhatsAppTextParser,
)
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.privacy.redactor import redact_preview
from aptjeeves.storage.db import utc_now_iso
from aptjeeves.storage.models import ImportSummary, RawMessageInsert
from aptjeeves.storage.repositories import (
    CanonicalFactRepository,
    ImportRunRepository,
    RawMessageRepository,
)


@dataclass(frozen=True)
class IngestRequest:
    """User-supplied parameters for one chat export ingestion run."""

    platform: str
    file_path: Path
    chat_name: str | None = None
    default_timezone: str = "Asia/Kolkata"
    date_order: str = "DMY"
    upload_dir: Path | None = None
    max_parse_failure_rate: float = 0.05


class ChatIngestionService:
    """Coordinates parsing, normalization, dedupe, storage, and events for imports."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        attachment_config: AttachmentConfig | None = None,
    ) -> None:
        """Create an ingestion service using an already-migrated SQLite connection."""

        self.connection = connection
        self.attachments = AttachmentService(connection, config=attachment_config)
        self.import_runs = ImportRunRepository(connection)
        self.raw_messages = RawMessageRepository(connection)
        self.facts = CanonicalFactRepository(connection)
        self.events = ObservabilityService(connection)

    def ingest(self, request: IngestRequest) -> ImportSummary:
        """Ingest a chat export and return a persisted import summary.

        Milestone 1 supports WhatsApp text exports and Telegram JSON exports.
        The key guarantee is idempotency: a repeated or expanded export can be
        imported safely because each normalized message is inserted through the
        unique `message_fingerprint` ledger in `raw_messages`.
        """

        platform = request.platform.strip().casefold()
        if platform not in {"whatsapp", "telegram"}:
            raise ValueError(f"Unsupported platform for Milestone 1: {request.platform}")

        parser_version, parse_result = self._parse_request(request, platform)
        effective_chat_name = (
            request.chat_name
            or parse_result.chat_name
            or _fallback_chat_name_from_file(request.file_path)
        )

        # Import IDs are per-run; trace IDs correlate all events emitted by this run.
        import_batch_id = f"import_{uuid.uuid4().hex}"
        trace_id = f"trace_{uuid.uuid4().hex}"
        source_file = str(request.file_path)
        source_file_hash = sha256_file(request.file_path)
        source_conversation_id = self._source_conversation_id(
            platform=platform,
            chat_name=effective_chat_name,
            parser_conversation_id=parse_result.source_conversation_id,
        )

        # Persist the run before parsing so even partial failures are observable.
        with self.connection:
            self.import_runs.create(
                import_batch_id=import_batch_id,
                source_platform=platform,
                source_file=source_file,
                source_file_hash=source_file_hash,
                chat_name=effective_chat_name,
                parser_version=parser_version,
                normalizer_version=NORMALIZER_VERSION,
                redactor_version=REDACTOR_VERSION,
            )
            self.events.emit(
                trace_id=trace_id,
                event_type="import_started",
                stage="ingestion",
                import_batch_id=import_batch_id,
                payload={
                    "platform": platform,
                    "source_file_hash": source_file_hash,
                    "chat_name": effective_chat_name,
                },
            )

        total_messages_seen = len(parse_result.messages)
        new_messages_inserted = 0
        duplicate_messages_skipped = 0

        with self.connection:
            # Parse failures are non-fatal at this stage; the batch can still
            # produce useful messages while surfacing the problematic lines.
            for failure in parse_result.failures:
                self.events.emit(
                    trace_id=trace_id,
                    event_type="parse_failure",
                    stage="ingestion",
                    severity="warning",
                    import_batch_id=import_batch_id,
                    payload={
                        "line_number": failure.line_number,
                        "source_offset": failure.source_offset,
                        "reason": failure.reason,
                        "text_preview": redact_preview(failure.text_preview),
                    },
                )

            for parsed in parse_result.messages:
                # Normalization handles timezone conversion, sender hashing,
                # whitespace canonicalization, and media-only filtering.
                normalized = normalize_message(
                    parsed,
                    default_timezone=request.default_timezone,
                    date_order=request.date_order,
                )
                if normalized is None:
                    self.events.emit(
                        trace_id=trace_id,
                        event_type="message_ignored",
                        stage="ingestion",
                        import_batch_id=import_batch_id,
                        payload={
                            "reason": "empty_or_media_only",
                            "source_line_start": parsed.source_line_start,
                            "source_line_end": parsed.source_line_end,
                        },
                    )
                    continue

                # The fingerprint is the durable message identity. It must stay
                # stable across monthly full exports so old messages are skipped.
                fingerprint = message_fingerprint(
                    platform=platform,
                    source_conversation_id=source_conversation_id,
                    source_message_id=parsed.source_message_id,
                    canonical_sender=normalized.canonical_sender,
                    sent_at_utc=normalized.sent_at_utc,
                    normalized_text_hash=normalized.normalized_text_hash,
                )
                # Deriving message_id from the fingerprint gives duplicate rows
                # the same app-level ID without needing a separate lookup.
                message_id = f"msg_{fingerprint[:32]}"

                # `insert_if_new` relies on the database UNIQUE constraint. This
                # makes dedupe atomic and safe even if later imports overlap.
                inserted = self.raw_messages.insert_if_new(
                    RawMessageInsert(
                        message_id=message_id,
                        message_fingerprint=fingerprint,
                        import_batch_id=import_batch_id,
                        platform=platform,
                        source_conversation_id=source_conversation_id,
                        chat_name=effective_chat_name,
                        source_message_id=parsed.source_message_id,
                        sender_hash=normalized.sender_hash,
                        sender_display_hint=normalized.sender_display_hint,
                        sent_at_utc=normalized.sent_at_utc,
                        source_timezone=normalized.source_timezone,
                        normalized_text_hash=normalized.normalized_text_hash,
                        sanitized_text=normalized.sanitized_text,
                        raw_text_debug_ref=None,
                        source_file=source_file,
                        source_offset=parsed.source_offset,
                        source_line_start=parsed.source_line_start,
                        source_line_end=parsed.source_line_end,
                        processing_status="new",
                        first_seen_at=utc_now_iso(),
                        processed_at=None,
                        parser_version=parser_version,
                        normalizer_version=NORMALIZER_VERSION,
                        redactor_version=REDACTOR_VERSION,
                    )
                )
                if inserted:
                    # Only newly inserted messages continue to later extraction
                    # milestones. In Milestone 1 we stop after storing the row.
                    new_messages_inserted += 1
                    self.events.emit(
                        trace_id=trace_id,
                        event_type="raw_message_inserted",
                        stage="ingestion",
                        import_batch_id=import_batch_id,
                        message_id=message_id,
                        payload={
                            "message_fingerprint": fingerprint,
                            "source_line_start": parsed.source_line_start,
                            "source_line_end": parsed.source_line_end,
                            "redaction_counts": normalized.redaction_counts,
                        },
                    )
                    # If the message contains a vCard filename (e.g. "Jaya Akka.vcf"),
                    # attempt to read the corresponding file from request.upload_dir
                    # (if provided) and upsert a richer contact with extracted
                    # phone/email methods. Falls back to a minimal contact if the
                    # file is not available or parsing fails.
                    filename = _extract_vcard_filename(parsed.text)
                    if filename:
                        name_hint = filename.rsplit(".", 1)[0]
                        contact_methods: list[dict[str, str]] = []
                        contact_hashes: list[str] = []
                        # If an upload_dir is provided, attempt to parse the vCard
                        if request.upload_dir:
                            vcf_path = _resolve_vcard_path(request.upload_dir, filename)
                            vcard = None
                            try:
                                vcard = parse_vcard(vcf_path)
                            except Exception:
                                vcard = None
                            if vcard:
                                if vcard.get("phones"):
                                    for tel in vcard["phones"]:
                                        contact_methods.append({"type": "phone", "value": tel})
                                        contact_hashes.append(sha256_text(tel))
                                if vcard.get("emails"):
                                    for em in vcard["emails"]:
                                        contact_methods.append({"type": "email", "value": em})
                                        contact_hashes.append(sha256_text(em))
                                if vcard.get("name"):
                                    name_hint = vcard.get("name")

                        fact_identity_key = f"service_contact|vcard|{sha256_text(filename)}"
                        contact_fact = ServiceContactUpsert(
                            fact_identity_key=fact_identity_key,
                            title=name_hint or filename,
                            summary=f"vCard shared in chat: {filename}",
                            privacy_status="public_to_residents",
                            confidence=0.9,
                            first_seen=normalized.sent_at_utc,
                            latest_seen=normalized.sent_at_utc,
                            extractor_prompt_version=None,
                            llm_model_version=None,
                            service_type="unknown",
                            display_name=name_hint,
                            normalized_name=(name_hint.casefold() if name_hint else None),
                            contact_methods=contact_methods,
                            contact_method_hashes=contact_hashes,
                            contact_classification="vendor_or_service_contact",
                            is_resident_affiliated=False,
                            resident_affiliation_reason=None,
                            area_or_scope=None,
                            price_hint=None,
                            availability_hint=None,
                            caveats=None,
                        )
                        evidence = [
                            FactEvidenceInput(
                                message_id=message_id,
                                message_fingerprint=fingerprint,
                                sanitized_snippet=normalized.sanitized_text,
                                evidence_type="vcard",
                                confidence=0.9,
                            )
                        ]
                        try:
                            self.facts.upsert_service_contact(contact_fact, evidence)
                            self.events.emit(
                                trace_id=trace_id,
                                event_type="vcard_contact_upserted",
                                stage="ingestion",
                                import_batch_id=import_batch_id,
                                payload={
                                    "message_id": message_id,
                                    "filename": filename,
                                },
                            )
                        except Exception as e:
                            # Don't let contact upsert failures block the import
                            self.events.emit(
                                trace_id=trace_id,
                                event_type="vcard_contact_upsert_failed",
                                stage="ingestion",
                                severity="warning",
                                import_batch_id=import_batch_id,
                                payload={"error": str(e), "message_id": message_id, "filename": filename},
                            )
                else:
                    # Duplicates are expected during monthly/full-history imports,
                    # so they are counted and traced instead of treated as errors.
                    duplicate_messages_skipped += 1
                    self.events.emit(
                        trace_id=trace_id,
                        event_type="duplicate_message_skipped",
                        stage="ingestion",
                        import_batch_id=import_batch_id,
                        payload={
                            "message_fingerprint": fingerprint,
                            "reason": "message_fingerprint already exists",
                        },
                    )
                    # vCard facts may have failed on an earlier import, so allow
                    # duplicate-message replays to backfill canonical contacts.
                    filename = _extract_vcard_filename(parsed.text)
                    if filename:
                        name_hint = filename.rsplit(".", 1)[0]
                        contact_methods: list[dict[str, str]] = []
                        contact_hashes: list[str] = []
                        if request.upload_dir:
                            vcf_path = _resolve_vcard_path(request.upload_dir, filename)
                            vcard = None
                            try:
                                vcard = parse_vcard(vcf_path)
                            except Exception:
                                vcard = None
                            if vcard:
                                if vcard.get("phones"):
                                    for tel in vcard["phones"]:
                                        contact_methods.append({"type": "phone", "value": tel})
                                        contact_hashes.append(sha256_text(tel))
                                if vcard.get("emails"):
                                    for em in vcard["emails"]:
                                        contact_methods.append({"type": "email", "value": em})
                                        contact_hashes.append(sha256_text(em))
                                if vcard.get("name"):
                                    name_hint = vcard.get("name")

                        fact_identity_key = f"service_contact|vcard|{sha256_text(filename)}"
                        contact_fact = ServiceContactUpsert(
                            fact_identity_key=fact_identity_key,
                            title=name_hint or filename,
                            summary=f"vCard shared in chat: {filename}",
                            privacy_status="public_to_residents",
                            confidence=0.9,
                            first_seen=normalized.sent_at_utc,
                            latest_seen=normalized.sent_at_utc,
                            extractor_prompt_version=None,
                            llm_model_version=None,
                            service_type="unknown",
                            display_name=name_hint,
                            normalized_name=(name_hint.casefold() if name_hint else None),
                            contact_methods=contact_methods,
                            contact_method_hashes=contact_hashes,
                            contact_classification="vendor_or_service_contact",
                            is_resident_affiliated=False,
                            resident_affiliation_reason=None,
                            area_or_scope=None,
                            price_hint=None,
                            availability_hint=None,
                            caveats=None,
                        )
                        evidence = [
                            FactEvidenceInput(
                                message_id=message_id,
                                message_fingerprint=fingerprint,
                                sanitized_snippet=normalized.sanitized_text,
                                evidence_type="vcard",
                                confidence=0.9,
                            )
                        ]
                        try:
                            self.facts.upsert_service_contact(contact_fact, evidence)
                            self.events.emit(
                                trace_id=trace_id,
                                event_type="vcard_contact_upserted",
                                stage="ingestion",
                                import_batch_id=import_batch_id,
                                payload={
                                    "message_id": message_id,
                                    "filename": filename,
                                    "from_duplicate_message": True,
                                },
                            )
                        except Exception as e:
                            self.events.emit(
                                trace_id=trace_id,
                                event_type="vcard_contact_upsert_failed",
                                stage="ingestion",
                                severity="warning",
                                import_batch_id=import_batch_id,
                                payload={"error": str(e), "message_id": message_id, "filename": filename},
                            )

                # Attachments (PDF/DOCX/XLSX/CSV/TXT/images) referenced by this
                # message are hashed, spooled, and linked here; text extraction
                # happens later in the attachments stage. Duplicate messages are
                # included so a re-import with the files present can backfill.
                self.attachments.register_from_message(
                    text=parsed.text,
                    message_id=message_id,
                    upload_dir=request.upload_dir,
                    trace_id=trace_id,
                    import_batch_id=import_batch_id,
                )

            status = _import_status(
                parse_failures=len(parse_result.failures),
                total_attempted=total_messages_seen + len(parse_result.failures),
                max_failure_rate=request.max_parse_failure_rate,
            )
            # Final counters live on import_runs so the CLI can show a concise
            # summary without scanning all events.
            self.import_runs.complete(
                import_batch_id=import_batch_id,
                status=status,
                total_messages_seen=total_messages_seen,
                new_messages_inserted=new_messages_inserted,
                duplicate_messages_skipped=duplicate_messages_skipped,
                parse_failures=len(parse_result.failures),
            )
            self.events.emit(
                trace_id=trace_id,
                event_type="import_completed",
                stage="ingestion",
                import_batch_id=import_batch_id,
                payload={
                    "status": status,
                    "total_messages_seen": total_messages_seen,
                    "new_messages_inserted": new_messages_inserted,
                    "duplicate_messages_skipped": duplicate_messages_skipped,
                    "parse_failures": len(parse_result.failures),
                },
            )

        summary = self.import_runs.get_summary(import_batch_id)
        if summary is None:
            raise RuntimeError(f"Import summary was not persisted: {import_batch_id}")
        return summary

    def _parse_request(self, request: IngestRequest, platform: str) -> tuple[str, ParseResult]:
        """Parse the export file with the platform-specific parser."""

        if platform == "whatsapp":
            return WHATSAPP_PARSER_VERSION, WhatsAppTextParser().parse_file(request.file_path)
        if platform == "telegram":
            return TELEGRAM_PARSER_VERSION, TelegramJsonParser().parse_file(request.file_path)
        raise ValueError(f"Unsupported platform for Milestone 1: {request.platform}")

    def _source_conversation_id(
        self,
        *,
        platform: str,
        chat_name: str,
        parser_conversation_id: str | None,
    ) -> str:
        """Return a stable source conversation ID for fingerprint construction."""

        if parser_conversation_id:
            return conversation_id(platform=platform, chat_name=f"native:{parser_conversation_id}")
        return conversation_id(platform=platform, chat_name=chat_name)


def _fallback_chat_name_from_file(file_path: Path) -> str:
    """Use the export filename as a final conversation-name fallback."""

    stem = file_path.stem.strip()
    if not stem:
        raise ValueError(f"Could not infer chat name from file path: {file_path}")
    return stem


def _import_status(
    *,
    parse_failures: int,
    total_attempted: int,
    max_failure_rate: float,
) -> str:
    """Determine import run status from parse failure counts and threshold.

    - ``completed`` when there are no parse failures.
    - ``completed_with_errors`` when the failure rate is at or below the
      configured threshold (minor/expected failures such as file headers).
    - ``failed`` when the failure rate exceeds the threshold, indicating the
      parser or export format has a significant problem.
    """

    if parse_failures == 0:
        return "completed"
    failure_rate = parse_failures / max(1, total_attempted)
    if failure_rate > max_failure_rate:
        return "failed"
    return "completed_with_errors"


def _extract_vcard_filename(text: str) -> str | None:
    """Extract a likely .vcf attachment name from one chat message."""

    match = re.search(r"([^\r\n]+?\.vcf)(?:\s+\(file attached\))?$", text, flags=re.IGNORECASE)
    if not match:
        return None
    filename = match.group(1).strip()
    filename = filename.strip("\u200e\u200f\u202a\u202b\u202c\u202d\u202e")
    return filename or None


def _resolve_vcard_path(upload_dir: Path, filename: str) -> Path:
    """Resolve a vCard path, tolerating case and Unicode quirks from exports."""

    direct = upload_dir / filename
    if direct.is_file():
        return direct

    target = _normalized_filename(filename)
    for candidate in upload_dir.iterdir():
        if candidate.is_file() and _normalized_filename(candidate.name) == target:
            return candidate
    return direct


def _normalized_filename(value: str) -> str:
    """Return a comparison-friendly filename key for export attachment lookup."""

    return unicodedata.normalize("NFKC", value).strip().casefold()



from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from aptjeeves.ingestion.fingerprint import conversation_id, message_fingerprint
from aptjeeves.ingestion.hashing import sha256_file
from aptjeeves.ingestion.normalizer import (
    NORMALIZER_VERSION,
    REDACTOR_VERSION,
    normalize_message,
)
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
from aptjeeves.storage.repositories import ImportRunRepository, RawMessageRepository


@dataclass(frozen=True)
class IngestRequest:
    """User-supplied parameters for one chat export ingestion run."""

    platform: str
    file_path: Path
    chat_name: str | None = None
    default_timezone: str = "Asia/Kolkata"
    date_order: str = "DMY"
    max_parse_failure_rate: float = 0.05


class ChatIngestionService:
    """Coordinates parsing, normalization, dedupe, storage, and events for imports."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create an ingestion service using an already-migrated SQLite connection."""

        self.connection = connection
        self.import_runs = ImportRunRepository(connection)
        self.raw_messages = RawMessageRepository(connection)
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

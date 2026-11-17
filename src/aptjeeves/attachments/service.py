from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from aptjeeves.attachments import repository as states
from aptjeeves.attachments.chunking import split_text
from aptjeeves.attachments.ocr import OCR_NONE
from aptjeeves.attachments.config import RETENTION_DELETE_AFTER_EXTRACT, AttachmentConfig
from aptjeeves.attachments.discovery import find_attachment_filenames, resolve_attachment_path
from aptjeeves.attachments.extractors import (
    EXTRACTOR_VERSION,
    METHOD_LOCAL_OCR,
    METHOD_NATIVE_TEXT,
    AttachmentExtractionError,
    extract_blocks,
    extract_blocks_isolated,
)
from aptjeeves.attachments.repository import AttachmentInsert, AttachmentRepository
from aptjeeves.attachments.sensitive import assess_sensitivity
from aptjeeves.attachments.sniff import DOC_KINDS, sniff_kind
from aptjeeves.ingestion.hashing import sha256_file, sha256_text
from aptjeeves.ingestion.normalizer import NORMALIZER_VERSION, normalize_text
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.privacy.redactor import REDACTOR_VERSION, redact_text
from aptjeeves.storage.db import utc_now_iso
from aptjeeves.storage.models import RawMessageInsert
from aptjeeves.storage.repositories import RawMessageRepository

logger = logging.getLogger(__name__)

SEGMENT_PARSER_VERSION = "attachment_segments_v1"
ATTACHMENT_SOURCE_PREFIX = "attachment:"

_DOC_SUFFIX = {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "csv": ".csv", "txt": ".txt"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass(frozen=True)
class AttachmentSummary:
    """Result of one process_pending run."""

    processed: int = 0
    text_extracted: int = 0
    segments_inserted: int = 0
    no_text: int = 0
    skipped_sensitive: int = 0
    failed: int = 0
    total_pending_before: int = 0
    remaining_pending: int = 0
    limit_applied: int = 0


class AttachmentService:
    """Registers attachments found in chat and turns them into extractable segments."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        config: AttachmentConfig | None = None,
        spool_dir: Path | None = None,
    ) -> None:
        self.connection = connection
        self.config = config or AttachmentConfig.from_env()
        self.attachments = AttachmentRepository(connection)
        self.raw_messages = RawMessageRepository(connection)
        self.events = ObservabilityService(connection)
        self._spool_dir = spool_dir

    # ------------------------------------------------------------------ discovery

    def register_from_message(
        self,
        *,
        text: str,
        message_id: str,
        upload_dir: Path | None,
        trace_id: str,
        import_batch_id: str,
    ) -> int:
        """Find, hash, spool and link attachments referenced by one chat message.

        Returns the number of attachments linked. Never raises for per-file
        problems; they become events or terminal statuses instead.
        """

        if upload_dir is None:
            return 0
        linked = 0
        for filename in find_attachment_filenames(text):
            try:
                if self._register_one(
                    filename=filename,
                    message_id=message_id,
                    upload_dir=upload_dir,
                    trace_id=trace_id,
                    import_batch_id=import_batch_id,
                ):
                    linked += 1
            except Exception as exc:  # noqa: BLE001 - one bad file must not fail the import
                logger.warning("Attachment registration failed: %s", type(exc).__name__)
                self.events.emit(
                    trace_id=trace_id,
                    event_type="attachment_failed",
                    stage="attachments",
                    severity="warning",
                    import_batch_id=import_batch_id,
                    message_id=message_id,
                    payload={"reason": "registration_error", "error_type": type(exc).__name__},
                )
        return linked

    def _register_one(
        self,
        *,
        filename: str,
        message_id: str,
        upload_dir: Path,
        trace_id: str,
        import_batch_id: str,
    ) -> bool:
        path = resolve_attachment_path(upload_dir, filename)
        if not path.is_file():
            self.events.emit(
                trace_id=trace_id,
                event_type="attachment_skipped",
                stage="attachments",
                import_batch_id=import_batch_id,
                message_id=message_id,
                payload={"reason": "missing_file"},
            )
            return False

        size = path.stat().st_size
        content_sha = sha256_file(path)
        attachment_id = f"att_{content_sha[:32]}"
        kind = sniff_kind(path)
        if kind == "vcard":
            return False  # owned by the existing vCard flow

        existing = self.attachments.get_by_hash(content_sha)
        if existing is None:
            self._insert_new(
                attachment_id=attachment_id,
                content_sha=content_sha,
                filename=filename,
                path=path,
                kind=kind,
                size=size,
            )
            row = self.attachments.get(attachment_id)
            self.events.emit(
                trace_id=trace_id,
                event_type="attachment_discovered",
                stage="attachments",
                import_batch_id=import_batch_id,
                message_id=message_id,
                payload={
                    "attachment_id": attachment_id,
                    "kind": kind,
                    "size_bytes": size,
                    "status": row["status"] if row else None,
                    "reason": row["status_reason"] if row else None,
                },
            )
        new_link = self.attachments.link(attachment_id, message_id)
        if existing is not None and new_link:
            self.events.emit(
                trace_id=trace_id,
                event_type="attachment_deduped",
                stage="attachments",
                import_batch_id=import_batch_id,
                message_id=message_id,
                payload={"attachment_id": attachment_id},
            )
        return new_link

    def _insert_new(
        self,
        *,
        attachment_id: str,
        content_sha: str,
        filename: str,
        path: Path,
        kind: str,
        size: int,
    ) -> None:
        spool_path: str | None = None
        reason: str | None = None
        if size > self.config.max_bytes:
            state, reason = states.SKIPPED_TOO_LARGE, "file_too_large"
        elif kind in DOC_KINDS:
            state = states.PENDING
            spool_path = str(self._copy_to_spool(path, content_sha, _DOC_SUFFIX[kind]))
        elif kind == "image":
            if self._ocr_enabled():
                state = states.PENDING
            else:
                # Kept so enabling OCR later can pick it up (see requeue_for_ocr).
                state, reason = states.SKIPPED_UNSUPPORTED, "image_ocr_not_enabled"
            suffix = path.suffix.lower() if path.suffix.lower() in _IMAGE_SUFFIXES else ".img"
            spool_path = str(self._copy_to_spool(path, content_sha, suffix))
        else:
            state, reason = states.SKIPPED_UNSUPPORTED, f"unsupported_type:{kind}"

        self.attachments.insert_if_new(
            AttachmentInsert(
                attachment_id=attachment_id,
                content_sha256=content_sha,
                original_filename=filename,
                mime_sniffed=kind,
                size_bytes=size,
                spool_path=spool_path,
                status=state,
                status_reason=reason,
            )
        )

    def _ocr_enabled(self) -> bool:
        return self.config.ocr_backend != OCR_NONE

    def _copy_to_spool(self, source: Path, content_sha: str, suffix: str) -> Path:
        spool = self._resolve_spool_dir()
        spool.mkdir(parents=True, exist_ok=True)
        # Content-addressed and name-free: the stored filename never carries PII.
        target = spool / f"{content_sha}{suffix}"
        if not target.exists():
            shutil.copyfile(source, target)
        return target

    def _resolve_spool_dir(self) -> Path:
        if self._spool_dir is None:
            row = self.connection.execute("PRAGMA database_list").fetchone()
            db_file = row["file"] if row is not None else ""
            if db_file:
                self._spool_dir = Path(db_file).parent / "attachments"
            else:
                self._spool_dir = Path(tempfile.mkdtemp(prefix="aptjeeves_spool_"))
        return self._spool_dir

    # ----------------------------------------------------------------- processing

    def process_pending(self, *, limit: int = 50) -> AttachmentSummary:
        """Extract text from pending attachments and insert segments as raw messages."""

        if self._ocr_enabled():
            # Files parked earlier because OCR was off become candidates now.
            self.attachments.requeue_for_ocr()
        counts = self.attachments.count_by_status()
        total_pending = counts[states.PENDING]
        rows = self.attachments.list_by_status(states.PENDING, limit=limit)
        trace_id = f"trace_{uuid.uuid4().hex}"
        outcome = {"extracted": 0, "segments": 0, "no_text": 0, "sensitive": 0, "failed": 0}

        for row in rows:
            result, segments = self._process_one(row, trace_id)
            outcome["segments"] += segments
            if result == states.TEXT_EXTRACTED:
                outcome["extracted"] += 1
            elif result == states.NO_TEXT:
                outcome["no_text"] += 1
            elif result == states.SKIPPED_SENSITIVE:
                outcome["sensitive"] += 1
            else:
                outcome["failed"] += 1

        return AttachmentSummary(
            processed=len(rows),
            text_extracted=outcome["extracted"],
            segments_inserted=outcome["segments"],
            no_text=outcome["no_text"],
            skipped_sensitive=outcome["sensitive"],
            failed=outcome["failed"],
            total_pending_before=total_pending,
            remaining_pending=max(0, total_pending - len(rows)),
            limit_applied=limit,
        )

    def _process_one(self, row: sqlite3.Row, trace_id: str) -> tuple[str, int]:
        """Process one attachment; returns (final status, segments inserted)."""

        attachment_id = row["attachment_id"]
        spool_path = Path(row["spool_path"]) if row["spool_path"] else None
        kind = row["mime_sniffed"]

        if kind == "image" and not self._ocr_enabled():
            return self._done(attachment_id, trace_id, states.SKIPPED_UNSUPPORTED, "image_ocr_not_enabled")
        if spool_path is None or not spool_path.is_file() or (kind not in DOC_KINDS and kind != "image"):
            return self._done(attachment_id, trace_id, states.FAILED, "spool_missing")

        try:
            if self.config.isolate:
                extracted = extract_blocks_isolated(kind, spool_path, self.config)
            else:
                extracted = extract_blocks(kind, spool_path, self.config)
        except AttachmentExtractionError as exc:
            return self._done(attachment_id, trace_id, states.FAILED, exc.category)

        blocks = extracted["blocks"]
        full_text = "\n\n".join(block["text"] for block in blocks)
        text_chars = len(full_text.strip())
        page_count = extracted.get("page_count")
        method = extracted.get("method", METHOD_NATIVE_TEXT)

        if text_chars < self.config.min_segment_chars:
            if method == METHOD_LOCAL_OCR:
                # OCR already ran: nothing more to try, so the file can go.
                return self._done(
                    attachment_id, trace_id, states.NO_TEXT, "no_text_after_ocr",
                    page_count=page_count, text_chars=text_chars, method=method, delete_spool=True,
                )
            return self._done(
                attachment_id, trace_id, states.NO_TEXT, "no_text_layer",
                page_count=page_count, text_chars=text_chars,
            )

        verdict = assess_sensitivity(full_text, flat_listing_threshold=self.config.flat_listing_threshold)
        if verdict.is_sensitive:
            # Nothing from the document is persisted beyond this category.
            return self._done(
                attachment_id, trace_id, states.SKIPPED_SENSITIVE, verdict.reason,
                page_count=page_count, text_chars=text_chars, delete_spool=True,
            )

        parent = self.attachments.first_parent(attachment_id)
        if parent is None:
            return self._done(attachment_id, trace_id, states.FAILED, "no_parent_message")

        inserted = self._insert_segments(row, parent, blocks)
        return self._done(
            attachment_id, trace_id, states.TEXT_EXTRACTED,
            "truncated" if extracted.get("truncated") else None,
            page_count=page_count, text_chars=text_chars, segment_count=inserted,
            method=method, delete_spool=True,
            import_batch_id=parent["import_batch_id"],
        )

    def _done(self, *args: object, **kwargs: object) -> tuple[str, int]:
        """Finish an attachment and pair its status with the segment count."""

        new_status = self._finish(*args, **kwargs)  # type: ignore[arg-type]
        return new_status, int(kwargs.get("segment_count") or 0)

    def _insert_segments(
        self,
        attachment: sqlite3.Row,
        parent: sqlite3.Row,
        blocks: list[dict[str, str]],
    ) -> int:
        content_sha = attachment["content_sha256"]
        safe_name = redact_text(attachment["original_filename"]).text
        inserted = 0
        index = 0
        with self.connection:
            for block in blocks:
                sanitized_block = redact_text(normalize_text(block["text"])).text
                label_base = redact_text(block["label"]).text
                pieces = split_text(
                    sanitized_block, self.config.segment_chars, self.config.segment_overlap
                )
                for part_number, piece in enumerate(pieces, start=1):
                    if len(piece.strip()) < self.config.min_segment_chars:
                        continue
                    index += 1
                    label = label_base if len(pieces) == 1 else f"{label_base} (part {part_number})"
                    fingerprint = sha256_text(
                        f"attachment|{content_sha}|{parent['source_conversation_id']}|{index}"
                    )
                    was_new = self.raw_messages.insert_if_new(
                        RawMessageInsert(
                            message_id=f"msg_{fingerprint[:32]}",
                            message_fingerprint=fingerprint,
                            import_batch_id=parent["import_batch_id"],
                            platform=parent["platform"],
                            source_conversation_id=parent["source_conversation_id"],
                            chat_name=parent["chat_name"],
                            source_message_id=None,
                            sender_hash=parent["sender_hash"],
                            sender_display_hint=parent["sender_display_hint"],
                            sent_at_utc=parent["sent_at_utc"],
                            source_timezone=parent["source_timezone"],
                            normalized_text_hash=sha256_text(piece),
                            sanitized_text=piece,
                            raw_text_debug_ref=None,
                            source_file=f"{ATTACHMENT_SOURCE_PREFIX}{safe_name}",
                            source_offset=index,
                            source_line_start=None,
                            source_line_end=None,
                            processing_status="new",
                            first_seen_at=utc_now_iso(),
                            processed_at=None,
                            parser_version=SEGMENT_PARSER_VERSION,
                            normalizer_version=NORMALIZER_VERSION,
                            redactor_version=REDACTOR_VERSION,
                            source_kind="attachment",
                            parent_message_id=parent["message_id"],
                            attachment_id=attachment["attachment_id"],
                            segment_label=label,
                        )
                    )
                    if was_new:
                        inserted += 1
        return inserted

    def _finish(
        self,
        attachment_id: str,
        trace_id: str,
        new_status: str,
        reason: str | None,
        *,
        page_count: int | None = None,
        text_chars: int | None = None,
        segment_count: int | None = None,
        method: str | None = None,
        delete_spool: bool = False,
        import_batch_id: str | None = None,
    ) -> str:
        with self.connection:
            self.attachments.set_result(
                attachment_id,
                status=new_status,
                reason=reason,
                extraction_method=method,
                page_count=page_count,
                text_chars=text_chars,
                segment_count=segment_count,
                extractor_version=EXTRACTOR_VERSION,
            )
            if new_status == states.TEXT_EXTRACTED:
                event_type, severity = "attachment_text_extracted", "info"
            elif new_status == states.FAILED:
                event_type, severity = "attachment_failed", "warning"
            else:
                event_type, severity = "attachment_skipped", "info"
            self.events.emit(
                trace_id=trace_id,
                event_type=event_type,
                stage="attachments",
                severity=severity,
                import_batch_id=import_batch_id,
                payload={
                    "attachment_id": attachment_id,
                    "status": new_status,
                    "reason": reason,
                    "page_count": page_count,
                    "text_chars": text_chars,
                    "segments": segment_count,
                },
            )
        # Only statuses that can never need the file again are eligible for
        # cleanup (no_text files stay until OCR has been attempted).
        if delete_spool and self.config.retention == RETENTION_DELETE_AFTER_EXTRACT:
            self._delete_spool(attachment_id)
        return new_status

    def _delete_spool(self, attachment_id: str) -> None:
        row = self.attachments.get(attachment_id)
        if row is None or not row["spool_path"]:
            return
        try:
            Path(row["spool_path"]).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not delete spooled attachment: %s", type(exc).__name__)
            return
        with self.connection:
            self.attachments.clear_spool_path(attachment_id)

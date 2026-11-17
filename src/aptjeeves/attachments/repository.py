from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from aptjeeves.storage.db import utc_now_iso

# Statuses
PENDING = "pending"
TEXT_EXTRACTED = "text_extracted"
NO_TEXT = "no_text"
SKIPPED_UNSUPPORTED = "skipped_unsupported"
SKIPPED_TOO_LARGE = "skipped_too_large"
SKIPPED_SENSITIVE = "skipped_sensitive"
FAILED = "failed"

ALL_STATUSES = (
    PENDING,
    TEXT_EXTRACTED,
    NO_TEXT,
    SKIPPED_UNSUPPORTED,
    SKIPPED_TOO_LARGE,
    SKIPPED_SENSITIVE,
    FAILED,
)


@dataclass(frozen=True)
class AttachmentInsert:
    attachment_id: str
    content_sha256: str
    original_filename: str
    mime_sniffed: str | None
    size_bytes: int | None
    spool_path: str | None
    status: str
    status_reason: str | None = None


class AttachmentRepository:
    """Persistence for attachments and their links to parent chat messages."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_by_hash(self, content_sha256: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM attachments WHERE content_sha256 = ?", (content_sha256,)
        ).fetchone()

    def get(self, attachment_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM attachments WHERE attachment_id = ?", (attachment_id,)
        ).fetchone()

    def insert_if_new(self, item: AttachmentInsert) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO attachments (
              attachment_id, content_sha256, original_filename, mime_sniffed,
              size_bytes, spool_path, status, status_reason, first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.attachment_id,
                item.content_sha256,
                item.original_filename,
                item.mime_sniffed,
                item.size_bytes,
                item.spool_path,
                item.status,
                item.status_reason,
                utc_now_iso(),
            ),
        )
        return cursor.rowcount == 1

    def link(self, attachment_id: str, message_id: str) -> bool:
        """Link a parent message to an attachment; true when the link is new."""

        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO attachment_links (attachment_id, message_id) VALUES (?, ?)",
            (attachment_id, message_id),
        )
        return cursor.rowcount == 1

    def list_by_status(self, status: str, *, limit: int = 50) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM attachments WHERE status = ? ORDER BY first_seen_at, attachment_id LIMIT ?",
            (status, limit),
        ).fetchall()

    def count_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in ALL_STATUSES}
        for row in self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM attachments GROUP BY status"
        ).fetchall():
            counts[row["status"]] = int(row["count"])
        return counts

    def first_parent(self, attachment_id: str) -> sqlite3.Row | None:
        """Return the earliest linked chat message; segments inherit its metadata."""

        return self.connection.execute(
            """
            SELECT m.* FROM attachment_links l
            JOIN raw_messages m ON m.message_id = l.message_id
            WHERE l.attachment_id = ?
            ORDER BY m.sent_at_utc, m.message_id
            LIMIT 1
            """,
            (attachment_id,),
        ).fetchone()

    def set_result(
        self,
        attachment_id: str,
        *,
        status: str,
        reason: str | None = None,
        extraction_method: str | None = None,
        page_count: int | None = None,
        text_chars: int | None = None,
        segment_count: int | None = None,
        extractor_version: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE attachments
            SET status = ?, status_reason = ?, extraction_method = ?, page_count = ?,
                text_chars = ?, segment_count = ?, extractor_version = ?, processed_at = ?
            WHERE attachment_id = ?
            """,
            (
                status,
                reason,
                extraction_method,
                page_count,
                text_chars,
                segment_count,
                extractor_version,
                utc_now_iso(),
                attachment_id,
            ),
        )

    def clear_spool_path(self, attachment_id: str) -> None:
        self.connection.execute(
            "UPDATE attachments SET spool_path = NULL WHERE attachment_id = ?", (attachment_id,)
        )

    def reset_failed(self) -> int:
        cursor = self.connection.execute(
            "UPDATE attachments SET status = ?, status_reason = NULL WHERE status = ?",
            (PENDING, FAILED),
        )
        return cursor.rowcount

    def requeue_for_ocr(self) -> int:
        """Re-queue images and scan-only PDFs that were parked before OCR was enabled."""

        cursor = self.connection.execute(
            """
            UPDATE attachments
            SET status = ?, status_reason = NULL
            WHERE spool_path IS NOT NULL AND (
              (status = ? AND status_reason = 'image_ocr_not_enabled')
              OR (status = ? AND mime_sniffed = 'pdf' AND extraction_method IS NULL)
            )
            """,
            (PENDING, SKIPPED_UNSUPPORTED, NO_TEXT),
        )
        return cursor.rowcount

    def ocr_counts(self) -> dict[str, int]:
        """Counts describing OCR work, for status displays."""

        def scalar(sql: str) -> int:
            return int(self.connection.execute(sql).fetchone()[0])

        return {
            "text_extracted": scalar(
                "SELECT COUNT(*) FROM attachments WHERE status = 'text_extracted' AND extraction_method = 'local_ocr'"
            ),
            "no_text": scalar(
                "SELECT COUNT(*) FROM attachments WHERE status = 'no_text' AND extraction_method = 'local_ocr'"
            ),
            "awaiting_ocr": scalar(
                "SELECT COUNT(*) FROM attachments WHERE status = 'skipped_unsupported' "
                "AND status_reason = 'image_ocr_not_enabled'"
                " OR (status = 'no_text' AND mime_sniffed = 'pdf' AND extraction_method IS NULL)"
            ),
            "failed_unavailable": scalar(
                "SELECT COUNT(*) FROM attachments WHERE status = 'failed' AND status_reason = 'ocr_unavailable'"
            ),
        }

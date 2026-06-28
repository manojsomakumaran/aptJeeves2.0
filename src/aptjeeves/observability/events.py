from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from aptjeeves.storage.db import utc_now_iso


class ObservabilityService:
    """Writes privacy-safe structured events for ingestion and future flows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create an event writer bound to a SQLite connection."""

        self.connection = connection

    def emit(
        self,
        *,
        trace_id: str,
        event_type: str,
        stage: str,
        severity: str = "info",
        status: str | None = None,
        import_batch_id: str | None = None,
        message_id: str | None = None,
        fact_id: str | None = None,
        query_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist one sanitized pipeline event.

        Callers are responsible for passing only privacy-safe payload fields.
        The event table is intentionally generic so later milestones can reuse it
        for extraction, retrieval, answering, and replay traces.
        """

        actual_severity = status if status is not None else severity

        self.connection.execute(
            """
            INSERT INTO pipeline_events (
              event_id, trace_id, event_type, stage, severity, import_batch_id,
              message_id, fact_id, query_id, sanitized_payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"event_{uuid.uuid4().hex}",
                trace_id,
                event_type,
                stage,
                actual_severity,
                import_batch_id,
                message_id,
                fact_id,
                query_id,
                json.dumps(payload or {}, sort_keys=True),
                utc_now_iso(),
            ),
        )

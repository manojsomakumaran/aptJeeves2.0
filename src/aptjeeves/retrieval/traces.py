from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from aptjeeves.storage.db import utc_now_iso


class RetrievalTraceRepository:
    """Persistence operations for retrieval_traces."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(
        self,
        *,
        query_id: str,
        trace_id: str,
        query_text_hash: str | None,
        query_intent: str | None,
        query_embedding_hash: str | None,
        candidate_fact_ids: list[str],
        selected_fact_ids: list[str],
        removed_by_privacy: list[str] | None,
        rerank_scores: list[dict[str, Any]] | None,
    ) -> str:
        retrieval_trace_id = f"rtrace_{uuid.uuid4().hex}"
        self.connection.execute(
            """
            INSERT INTO retrieval_traces (
              retrieval_trace_id, query_id, trace_id, query_text_hash,
              query_intent, query_embedding_hash, candidate_fact_ids_json,
              selected_fact_ids_json, removed_by_privacy_json,
              rerank_scores_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retrieval_trace_id,
                query_id,
                trace_id,
                query_text_hash,
                query_intent,
                query_embedding_hash,
                json.dumps(candidate_fact_ids),
                json.dumps(selected_fact_ids),
                json.dumps(removed_by_privacy) if removed_by_privacy else None,
                json.dumps(rerank_scores, default=str) if rerank_scores else None,
                utc_now_iso(),
            ),
        )
        return retrieval_trace_id

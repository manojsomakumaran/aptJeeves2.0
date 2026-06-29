from __future__ import annotations

import math
import sqlite3
import uuid
import logging

from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel
from aptjeeves.indexing.text_builder import EmbeddingTextBuilder
from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.storage.models import IndexSummary, VectorEntryUpsert
from aptjeeves.storage.repositories import CanonicalFactRepository, VectorEntryRepository


logger = logging.getLogger(__name__)


class VectorIndexingService:
    """Creates or refreshes vector_entries for canonical facts."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        embedding_model: LocalTokenEmbeddingModel | None = None,
    ) -> None:
        """Create an indexing service for the local SQLite store."""

        self.connection = connection
        self.embedding_model = embedding_model or LocalTokenEmbeddingModel()
        self.facts = CanonicalFactRepository(connection)
        self.vectors = VectorEntryRepository(connection)
        self.text_builder = EmbeddingTextBuilder(connection)
        self.events = ObservabilityService(connection)

    def index_pending(self, *, limit: int = 100) -> IndexSummary:
        """Index facts whose current fact_version has no active vector entry."""

        total_pending = self.facts.count_facts_for_indexing(
            embedding_model_version=self.embedding_model.model_version
        )

        fact_rows = self.facts.list_facts_for_indexing(
            limit=limit,
            embedding_model_version=self.embedding_model.model_version,
        )

        processed_count = len(fact_rows)
        remaining_pending = max(0, total_pending - processed_count)
        estimated_batches_remaining = math.ceil(remaining_pending / limit) if limit > 0 else 0

        logger.info(f"Indexing pending facts with limit {limit}. Found {processed_count} facts out of {total_pending} total pending.")

        if not fact_rows:
            return IndexSummary(
                vector_ids=[],
                total_pending_before=total_pending,
                remaining_pending=remaining_pending,
                estimated_batches_remaining=estimated_batches_remaining,
                limit_applied=limit,
            )

        # 1. Generate all embeddings (network I/O) OUTSIDE the transaction
        embeddings_to_write = []
        for fact in fact_rows:
            embedding_text = self.text_builder.build(fact)
            embedding_json = self.embedding_model.embed_json(embedding_text)
            embeddings_to_write.append((fact, embedding_text, embedding_json))

        # 2. Write them to the database (CPU/Disk I/O) INSIDE the transaction (fast)
        trace_id = f"trace_{uuid.uuid4().hex}"
        vector_ids: list[str] = []
        with self.connection:
            for fact, embedding_text, embedding_json in embeddings_to_write:
                entry = VectorEntryUpsert(
                    fact_id=fact["fact_id"],
                    fact_type=fact["fact_type"],
                    fact_version=fact["fact_version"],
                    embedding_text=embedding_text,
                    embedding_hash=sha256_text(embedding_text),
                    embedding_model_version=self.embedding_model.model_version,
                    embedding_json=embedding_json,
                    vector_store_ref=f"sqlite:vector_entries:{fact['fact_id']}",
                )
                vector_id = self.vectors.upsert_active(entry)
                self.events.emit(
                    trace_id=trace_id,
                    event_type="vector_entry_upserted",
                    stage="indexing",
                    fact_id=fact["fact_id"],
                    payload={
                        "vector_id": vector_id,
                        "fact_type": fact["fact_type"],
                        "fact_version": fact["fact_version"],
                        "embedding_model_version": self.embedding_model.model_version,
                    },
                )
                vector_ids.append(vector_id)

        return IndexSummary(
            vector_ids=vector_ids,
            total_pending_before=total_pending,
            remaining_pending=remaining_pending,
            estimated_batches_remaining=estimated_batches_remaining,
            limit_applied=limit,
        )

    def index_fact(self, fact: sqlite3.Row, *, trace_id: str | None = None) -> str:
        """Index one canonical fact row."""

        embedding_text = self.text_builder.build(fact)
        embedding_json = self.embedding_model.embed_json(embedding_text)
        entry = VectorEntryUpsert(
            fact_id=fact["fact_id"],
            fact_type=fact["fact_type"],
            fact_version=fact["fact_version"],
            embedding_text=embedding_text,
            embedding_hash=sha256_text(embedding_text),
            embedding_model_version=self.embedding_model.model_version,
            embedding_json=embedding_json,
            vector_store_ref=f"sqlite:vector_entries:{fact['fact_id']}",
        )
        vector_id = self.vectors.upsert_active(entry)
        self.events.emit(
            trace_id=trace_id or f"trace_{uuid.uuid4().hex}",
            event_type="vector_entry_upserted",
            stage="indexing",
            fact_id=fact["fact_id"],
            payload={
                "vector_id": vector_id,
                "fact_type": fact["fact_type"],
                "fact_version": fact["fact_version"],
                "embedding_model_version": self.embedding_model.model_version,
            },
        )
        return vector_id

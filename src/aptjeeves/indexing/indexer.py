from __future__ import annotations

import sqlite3
import uuid

from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel
from aptjeeves.indexing.text_builder import EmbeddingTextBuilder
from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.storage.models import VectorEntryUpsert
from aptjeeves.storage.repositories import CanonicalFactRepository, VectorEntryRepository


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

    def index_pending(self, *, limit: int = 100) -> list[str]:
        """Index facts whose current fact_version has no active vector entry."""

        fact_rows = self.facts.list_facts_for_indexing(limit=limit)
        if not fact_rows:
            return []

        trace_id = f"trace_{uuid.uuid4().hex}"
        vector_ids: list[str] = []
        with self.connection:
            for fact in fact_rows:
                vector_id = self.index_fact(fact, trace_id=trace_id)
                vector_ids.append(vector_id)
        return vector_ids

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

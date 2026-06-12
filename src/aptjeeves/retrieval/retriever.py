from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel


RETRIEVER_VERSION = "local_cosine_v1"


@dataclass(frozen=True)
class RetrievalCandidate:
    """A vector entry matched by similarity search."""

    vector_id: str
    fact_id: str
    fact_type: str
    similarity: float
    embedding_text: str


class VectorRetriever:
    """Retrieves canonical facts using cosine similarity via the embedding model."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        embedding_model: Any = None,
        *,
        top_k: int = 10,
        min_similarity: float = 0.05,
    ) -> None:
        self.connection = connection
        self.embedding_model = embedding_model or LocalTokenEmbeddingModel()
        self.top_k = top_k
        self.min_similarity = min_similarity

    def retrieve(self, query: str) -> list[RetrievalCandidate]:
        """Embed the query and return the top-K similar vector entries."""

        query_json = self.embedding_model.embed_json(query)
        if not query_json or query_json in ("{}", "[]"):
            return []

        rows = self.connection.execute(
            """
            SELECT vector_id, fact_id, fact_type, embedding_json, embedding_text
            FROM vector_entries
            WHERE status = 'active' AND embedding_model_version = ?
            """,
            (self.embedding_model.model_version,)
        ).fetchall()

        scored: list[RetrievalCandidate] = []
        for row in rows:
            sim = self.embedding_model.similarity(query_json, row["embedding_json"])
            if sim >= self.min_similarity:
                scored.append(
                    RetrievalCandidate(
                        vector_id=row["vector_id"],
                        fact_id=row["fact_id"],
                        fact_type=row["fact_type"],
                        similarity=round(sim, 6),
                        embedding_text=row["embedding_text"],
                    )
                )

        scored.sort(key=lambda c: c.similarity, reverse=True)
        return scored[: self.top_k]


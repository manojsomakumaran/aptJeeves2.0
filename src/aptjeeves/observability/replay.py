from __future__ import annotations

import sqlite3
import uuid

from aptjeeves.extraction.schemas import Extractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.retrieval.service import QueryService
from aptjeeves.storage.repositories import CanonicalFactRepository, QueryRunRepository, RawMessageRepository


class ReplayService:
    """Replay later pipeline stages from sanitized stored inputs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.events = ObservabilityService(connection)
        self.raw_messages = RawMessageRepository(connection)
        self.facts = CanonicalFactRepository(connection)
        self.queries = QueryRunRepository(connection)

    def replay_import(self, *, import_batch_id: str, extractor: Extractor, embedding_model: object) -> dict[str, object]:
        rows = self.raw_messages.list_by_import_batch(import_batch_id)
        if not rows:
            raise ValueError(f"Import batch not found: {import_batch_id}")
        trace_id = f"trace_{uuid.uuid4().hex}"
        extraction = ExtractionService(self.connection, extractor).extract_rows(rows)
        indexer = VectorIndexingService(self.connection, embedding_model)
        vector_ids: list[str] = []
        with self.connection:
            for fact_id in extraction.fact_ids:
                fact = self.facts.get_fact(fact_id)
                if fact is None:
                    continue
                vector_ids.append(indexer.index_fact(fact, trace_id=trace_id))
            self.events.emit(
                trace_id=trace_id,
                event_type="replay_import_completed",
                stage="replay",
                import_batch_id=import_batch_id,
                payload={
                    "from_stage": "extraction",
                    "fact_ids": extraction.fact_ids,
                    "vector_ids": vector_ids,
                },
            )
        return {
            "import_batch_id": import_batch_id,
            "fact_ids": extraction.fact_ids,
            "vector_ids": vector_ids,
            "extraction_failures": extraction.extraction_failures,
        }

    def replay_fact_index(self, *, fact_id: str, embedding_model: object) -> dict[str, object]:
        fact = self.facts.get_fact(fact_id)
        if fact is None:
            raise ValueError(f"Fact not found: {fact_id}")
        trace_id = f"trace_{uuid.uuid4().hex}"
        vector_id = VectorIndexingService(self.connection, embedding_model).index_fact(fact, trace_id=trace_id)
        with self.connection:
            self.events.emit(
                trace_id=trace_id,
                event_type="replay_fact_index_completed",
                stage="replay",
                fact_id=fact_id,
                payload={"vector_id": vector_id},
            )
        return {"fact_id": fact_id, "vector_id": vector_id}

    def replay_query(
        self,
        *,
        query_id: str,
        embedding_model: object,
        answerer: object,
        intent_classifier: object | None = None,
        top_k: int = 10,
        max_answer_facts: int = 5,
    ):
        query = self.queries.get(query_id)
        if query is None:
            raise ValueError(f"Query not found: {query_id}")
        service = QueryService(
            self.connection,
            embedding_model=embedding_model,
            answerer=answerer,
            intent_classifier=intent_classifier,
            top_k=top_k,
            max_answer_facts=max_answer_facts,
        )
        answer = service.ask(query["query_text_redacted"])
        with self.connection:
            self.events.emit(
                trace_id=f"trace_{uuid.uuid4().hex}",
                event_type="replay_query_completed",
                stage="replay",
                query_id=answer.query_id,
                payload={
                    "replayed_query_id": query_id,
                    "intent": answer.intent,
                    "confidence": answer.confidence,
                },
            )
        return answer
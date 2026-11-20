from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from aptjeeves.answering.guardrails import GUARDRAIL_VERSION, GuardrailValidator
from aptjeeves.answering.formatter import AnswerFormatter, AnswerResponse
from aptjeeves.answering.reveal import reveal_contacts
from aptjeeves.answering.llm_answerer import LLM_ANSWERER_VERSION
from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel
from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.privacy.redactor import redact_text
from aptjeeves.retrieval.context import ContextBuilder
from aptjeeves.retrieval.intent import KeywordIntentClassifier
from aptjeeves.retrieval.reranker import Reranker
from aptjeeves.retrieval.retriever import VectorRetriever
from aptjeeves.retrieval.traces import RetrievalTraceRepository
from aptjeeves.storage.repositories import QueryRunRepository


class QueryService:
    """Orchestrates the full retrieval-and-answer pipeline for a resident query."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        embedding_model: Any = None,
        answerer: Any = None,
        intent_classifier: Any = None,
        top_k: int = 10,
        max_answer_facts: int = 5,
    ) -> None:
        self.connection = connection
        self.retriever = VectorRetriever(connection, embedding_model, top_k=top_k)
        self.reranker = Reranker(connection)
        self.context_builder = ContextBuilder(connection, max_facts=max_answer_facts)
        self.answerer = answerer or AnswerFormatter()
        self.intent_classifier = intent_classifier or KeywordIntentClassifier()
        self.traces = RetrievalTraceRepository(connection)
        self.events = ObservabilityService(connection)
        self.query_runs = QueryRunRepository(connection)
        self.guardrails = GuardrailValidator(connection)

    def ask(self, query: str) -> AnswerResponse:
        """Run the full ask pipeline and return a structured answer."""

        query_id = f"query_{uuid.uuid4().hex}"
        trace_id = f"trace_{uuid.uuid4().hex}"

        # 1. Redact query for retrieval, logging, and provider calls
        redacted = redact_text(query)

        # 2. Classify intent
        intent_result = self.intent_classifier.classify(redacted.text)

        with self.connection:
            self.query_runs.create(
                query_id=query_id,
                trace_id=trace_id,
                query_text_redacted=redacted.text,
                query_text_hash=sha256_text(redacted.text),
                query_intent=intent_result.intent,
                answerer_version=_answerer_version(self.answerer),
                guardrail_version=GUARDRAIL_VERSION,
            )

        # 3. Retrieve candidates
        candidates = self.retriever.retrieve(redacted.text)
        candidate_fact_ids = [c.fact_id for c in candidates]

        # 4. Rerank
        ranked = self.reranker.rerank(candidates, intent=intent_result.intent)

        # 5. Build context
        context = self.context_builder.build(
            query_id=query_id,
            intent=intent_result.intent,
            ranked_facts=ranked,
        )
        selected_fact_ids = [f.fact_id for f in context.facts]

        # 6. Generate answer (template formatter or LLM)
        answer = self.answerer.answer(context, query=redacted.text)
        guardrail = self.guardrails.validate(answer, context=context, trace_id=trace_id)

        # 7. Record trace
        embedding_hash = sha256_text(redacted.text)
        rerank_scores = [
            {
                "fact_id": r.fact_id,
                "similarity": r.similarity,
                "final_score": r.final_score,
            }
            for r in ranked
        ]
        with self.connection:
            retrieval_trace_id = self.traces.insert(
                query_id=query_id,
                trace_id=trace_id,
                query_text_hash=sha256_text(redacted.text),
                query_intent=intent_result.intent,
                query_embedding_hash=embedding_hash,
                candidate_fact_ids=candidate_fact_ids,
                selected_fact_ids=selected_fact_ids,
                removed_by_privacy=None,
                rerank_scores=rerank_scores,
            )
            self.query_runs.complete(
                query_id=query_id,
                status="blocked" if guardrail.action == "refuse_safely" else "completed",
                retrieval_trace_id=retrieval_trace_id,
                final_action=guardrail.action,
                notes=f"intent_classifier={_intent_classifier_version(self.intent_classifier)}",
            )
            self.events.emit(
                trace_id=trace_id,
                event_type="query_answered",
                stage="retrieval",
                query_id=query_id,
                payload={
                    "intent": intent_result.intent,
                    "intent_classifier_version": _intent_classifier_version(self.intent_classifier),
                    "intent_confidence": intent_result.confidence,
                    "candidates_count": len(candidates),
                    "selected_count": len(selected_fact_ids),
                    "confidence": guardrail.answer.confidence,
                    "guardrail_action": guardrail.action,
                },
            )

        return reveal_contacts(guardrail.answer, context)


def _answerer_version(answerer: Any) -> str:
    if hasattr(answerer, "_model"):
        return LLM_ANSWERER_VERSION
    return AnswerFormatter.__name__.lower()


def _intent_classifier_version(intent_classifier: Any) -> str:
    return getattr(intent_classifier, "version", KeywordIntentClassifier.version)


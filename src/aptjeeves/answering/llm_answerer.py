from __future__ import annotations

import json
import time
from typing import Any

from langfuse.decorators import observe, langfuse_context
from langfuse.openai import OpenAI

from aptjeeves.answering.formatter import AnswerResponse, Citation
from aptjeeves.retrieval.context import FactContext, QueryContext


LLM_ANSWERER_VERSION = "llm_answerer_v1"

_SYSTEM_PROMPT = """\
You are AptJeeves, a privacy-aware apartment community assistant.
Answer the resident's question using ONLY the facts provided in the context below.

Rules:
- Answer ONLY from the supplied context. Do NOT use outside knowledge.
- Do NOT expose resident phone numbers, emails, or restricted contact details.
- Service contact numbers appear as CONTACTREF_n tokens in approved_contact_methods. Copy the token exactly where the number belongs; never write digits yourself. A value like PHONE_1 means the number is not available, so say so.
- Include source count and latest mention date when available.
- Say clearly when information is not available in the context.
- For government, legal, or admin processes, state this is community-discussed information, not officially verified.
- Be concise and practical.
"""


class LLMAnswerer:
    """Generates grounded answers using an OpenAI LLM with retrieved context."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        langfuse_client: Any = None,
    ) -> None:
        # Use the Langfuse-wrapped OpenAI client for automatic LLM tracing
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._langfuse_client = langfuse_client

    @observe(name="ask_answerer")
    def answer(self, context: QueryContext, *, query: str = "") -> AnswerResponse:
        """Generate a grounded answer from the retrieved query context."""

        if not context.facts:
            return AnswerResponse(
                answer="I don't have enough information in the community discussions to answer this question.",
                citations=[],
                confidence="none",
                privacy_note=None,
                query_id=context.query_id,
                intent=context.intent,
            )

        context_text = _build_context_text(context)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": f"Context:\n{context_text}"},
            {
                "role": "user",
                "content": query or "Please summarize the relevant information from the context.",
            },
        ]

        if self._langfuse_client:
            trace = self._langfuse_client.trace(name="ask_answerer", query_id=context.query_id)
            generation = trace.start_generation(
                name="answer_generation",
                model=self._model,
                input=messages,
            )
        else:
            generation = None
            kwargs = {}
            if getattr(context, "apartment", None):
                kwargs["session_id"] = context.apartment
            if getattr(context, "intent", None):
                kwargs["tags"] = [context.intent]
            if kwargs:
                langfuse_context.update_current_trace(**kwargs)

        # Langfuse automatically captures tokens, latency, inputs, and outputs here!
        response = self._client.chat.completions.create(
            name="answer_generation",
            model=self._model,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
        )

        answer_text = response.choices[0].message.content.strip()

        if generation:
            generation.end(
                output=answer_text,
                usage={
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                },
            )

        citations = [
            Citation(
                fact_id=f.fact_id,
                source_count=f.source_count,
                latest_seen=f.latest_seen,
                snippet=f.sanitized_snippets[0] if f.sanitized_snippets else f.summary,
            )
            for f in context.facts
        ]
        has_privacy_restriction = any(
            f.privacy_status in ("needs_review", "restricted", "blocked")
            for f in context.facts
        )
        privacy_note = (
            "Some contact details are restricted pending privacy review."
            if has_privacy_restriction
            else None
        )

        return AnswerResponse(
            answer=answer_text,
            citations=citations,
            confidence=_overall_confidence(context.facts),
            privacy_note=privacy_note,
            query_id=context.query_id,
            intent=context.intent,
        )


def _build_context_text(context: QueryContext) -> str:
    """Serialize the query context as a readable text block for the LLM prompt."""

    facts_data = []
    for fact in context.facts:
        entry: dict[str, Any] = {
            "fact_id": fact.fact_id,
            "fact_type": fact.fact_type,
            "title": fact.title,
            "summary": fact.summary,
            "source_count": fact.source_count,
            "latest_seen": fact.latest_seen,
            "confidence": fact.confidence,
            "privacy_status": fact.privacy_status,
        }
        if fact.approved_contact_methods:
            entry["approved_contact_methods"] = fact.approved_contact_methods
        if fact.sanitized_snippets:
            entry["sanitized_snippets"] = fact.sanitized_snippets[:3]
        if fact.caveats:
            entry["caveats"] = fact.caveats
        # Include type-specific detail keys
        relevant_keys = {
            "service_contact": ["service_type", "display_name", "area_or_scope", "price_hint"],
            "process_info": ["process_name", "category", "provider_or_authority"],
            "facility_info": ["facility_name", "info_type", "availability"],
        }.get(fact.fact_type, [])
        for key in relevant_keys:
            if fact.details.get(key):
                entry[key] = fact.details[key]
        facts_data.append(entry)

    return json.dumps({"query_intent": context.intent, "facts": facts_data}, indent=2)


def _overall_confidence(facts: list[FactContext]) -> str:
    if not facts:
        return "none"
    avg = sum(f.confidence for f in facts) / len(facts)
    if avg >= 0.8:
        return "high"
    if avg >= 0.5:
        return "medium"
    return "low"

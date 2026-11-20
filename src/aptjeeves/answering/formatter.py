from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aptjeeves.retrieval.context import FactContext, QueryContext


FORMATTER_VERSION = "template_formatter_v1"


@dataclass(frozen=True)
class Citation:
    """One citation backing an answer."""

    fact_id: str
    source_count: int
    latest_seen: str
    snippet: str


@dataclass(frozen=True)
class AnswerResponse:
    """Structured answer returned by the formatter."""

    answer: str
    citations: list[Citation]
    confidence: str
    privacy_note: str | None
    query_id: str
    intent: str


class AnswerFormatter:
    """Deterministic template-based answer generator (no LLM)."""

    def answer(self, context: QueryContext, *, query: str = "") -> AnswerResponse:
        """Produce a grounded answer from the structured query context."""

        if not context.facts:
            return AnswerResponse(
                answer="I don't have enough information to answer this question based on the community discussions I've seen.",
                citations=[],
                confidence="none",
                privacy_note=None,
                query_id=context.query_id,
                intent=context.intent,
            )

        parts: list[str] = []
        citations: list[Citation] = []
        has_privacy_restriction = False

        for fact in context.facts:
            text = self._format_fact(fact, context.intent)
            parts.append(text)

            snippet = fact.sanitized_snippets[0] if fact.sanitized_snippets else fact.summary
            citations.append(
                Citation(
                    fact_id=fact.fact_id,
                    source_count=fact.source_count,
                    latest_seen=fact.latest_seen,
                    snippet=snippet,
                )
            )
            if fact.privacy_status in ("needs_review", "restricted", "blocked"):
                has_privacy_restriction = True

        answer = "\n\n".join(parts)
        confidence = self._overall_confidence(context.facts)
        privacy_note = (
            "Some contact details are restricted pending privacy review."
            if has_privacy_restriction
            else None
        )

        return AnswerResponse(
            answer=answer,
            citations=citations,
            confidence=confidence,
            privacy_note=privacy_note,
            query_id=context.query_id,
            intent=context.intent,
        )

    def _format_fact(self, fact: FactContext, intent: str) -> str:
        """Render one fact into a human-readable text block."""

        lines: list[str] = [fact.summary]

        if fact.fact_type == "service_contact":
            lines.extend(self._format_service_contact(fact))
        elif fact.fact_type == "process_info":
            lines.extend(self._format_process_info(fact))
        elif fact.fact_type == "facility_info":
            lines.extend(self._format_facility_info(fact))

        if fact.source_count > 0:
            lines.append(f"Mentioned by {fact.source_count} source(s), last seen {fact.latest_seen}.")

        for caveat in fact.caveats:
            lines.append(f"Note: {caveat}")

        return "\n".join(lines)

    def _format_service_contact(self, fact: FactContext) -> list[str]:
        lines: list[str] = []
        details = fact.details
        service_type = details.get("service_type", "")
        display_name = details.get("display_name")
        if service_type:
            label = f"{service_type.replace('_', ' ').title()}"
            if display_name:
                label += f" — {display_name}"
            lines.append(label)

        if fact.approved_contact_methods:
            for method in fact.approved_contact_methods:
                mtype = method.get("type", "contact")
                value = method.get("contact_ref") or method.get("value_placeholder", "")
                lines.append(f"{mtype.title()}: {value}")
        elif fact.privacy_status in ("needs_review", "restricted", "blocked"):
            lines.append("Contact details are not shareable at this time.")
        return lines

    def _format_process_info(self, fact: FactContext) -> list[str]:
        lines: list[str] = []
        details = fact.details
        steps = _json_list(details.get("steps_json"))
        if steps:
            lines.append("Steps:")
            for i, step in enumerate(steps, 1):
                lines.append(f"  {i}. {step}")
        docs = _json_list(details.get("required_documents_json"))
        if docs:
            lines.append("Required documents: " + ", ".join(docs))
        fees = _json_list(details.get("fees_json"))
        if fees:
            lines.append("Fees: " + ", ".join(fees))
        return lines

    def _format_facility_info(self, fact: FactContext) -> list[str]:
        lines: list[str] = []
        details = fact.details
        avail = details.get("availability")
        if avail:
            lines.append(f"Availability: {avail}")
        rules = _json_list(details.get("rules_or_steps_json"))
        if rules:
            for rule in rules:
                lines.append(f"• {rule}")
        return lines

    def _overall_confidence(self, facts: list[FactContext]) -> str:
        if not facts:
            return "none"
        avg = sum(f.confidence for f in facts) / len(facts)
        if avg >= 0.8:
            return "high"
        if avg >= 0.5:
            return "medium"
        return "low"

    def to_json(self, response: AnswerResponse) -> dict[str, Any]:
        """Serialize the answer for CLI/API output."""

        return {
            "answer": response.answer,
            "citations": [
                {
                    "fact_id": c.fact_id,
                    "source_count": c.source_count,
                    "latest_seen": c.latest_seen,
                    "snippet": c.snippet,
                }
                for c in response.citations
            ],
            "confidence": response.confidence,
            "privacy_note": response.privacy_note,
            "query_id": response.query_id,
            "intent": response.intent,
        }


def _json_list(value: Any) -> list[str]:
    """Parse a JSON list column into strings."""

    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]

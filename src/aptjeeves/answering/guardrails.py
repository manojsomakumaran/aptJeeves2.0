from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass

from aptjeeves.answering.formatter import AnswerResponse
from aptjeeves.privacy.detectors import ADDRESS_PATTERN, EMAIL_PATTERN, FLAT_PATTERN, PHONE_PATTERN
from aptjeeves.privacy.redactor import redact_text
from aptjeeves.retrieval.context import QueryContext
from aptjeeves.storage.db import utc_now_iso


GUARDRAIL_VERSION = "final_guardrails_v1"
SAFE_FALLBACK = (
    "I found related discussion, but the contact or details appear restricted or "
    "unverified, so I cannot share them. I can share the general service/process "
    "information from the discussion."
)
_PLACEHOLDER_PATTERN = re.compile(r"\b(?:PHONE|EMAIL|URL|FLAT|ADDRESS|CONTACT)_\d+\b")
_HIGH_CERTAINTY_PATTERN = re.compile(r"\b(?:guaranteed|definitely|confirmed|officially|must)\b", re.I)


@dataclass(frozen=True)
class GuardrailDecision:
    """Final answer after deterministic privacy validation."""

    answer: AnswerResponse
    action: str
    reasons: list[str]


class GuardrailValidator:
    """Validate final answers against privacy and grounding constraints."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def validate(
        self,
        answer: AnswerResponse,
        *,
        context: QueryContext,
        trace_id: str,
    ) -> GuardrailDecision:
        reasons = self._detect_reasons(answer.answer, context)
        action = self._pick_action(reasons, context)
        guarded_answer = answer

        if action == "redact":
            guarded_answer = AnswerResponse(
                answer=redact_text(answer.answer).text,
                citations=answer.citations,
                confidence=answer.confidence,
                privacy_note=answer.privacy_note,
                query_id=answer.query_id,
                intent=answer.intent,
            )
        elif action == "refuse_safely":
            guarded_answer = AnswerResponse(
                answer=SAFE_FALLBACK,
                citations=answer.citations,
                confidence="low" if answer.confidence != "none" else "none",
                privacy_note="Restricted details were withheld by the final privacy guardrail.",
                query_id=answer.query_id,
                intent=answer.intent,
            )

        self._record_event(
            trace_id=trace_id,
            query_id=answer.query_id,
            action=action,
            reasons=reasons or ["passed"],
            sanitized_answer=guarded_answer.answer,
        )
        return GuardrailDecision(answer=guarded_answer, action=action, reasons=reasons)

    def _detect_reasons(self, answer_text: str, context: QueryContext) -> list[str]:
        reasons: list[str] = []
        has_restricted_facts = any(
            fact.privacy_status in ("needs_review", "restricted", "blocked")
            for fact in context.facts
        )
        has_process_facts = any(fact.fact_type == "process_info" for fact in context.facts)

        if PHONE_PATTERN.search(answer_text):
            reasons.append("resident_phone_leakage")
        if EMAIL_PATTERN.search(answer_text):
            reasons.append("restricted_email_leakage")
        if FLAT_PATTERN.search(answer_text) or ADDRESS_PATTERN.search(answer_text):
            reasons.append("flat_or_address_leakage")
        if has_restricted_facts and _PLACEHOLDER_PATTERN.search(answer_text):
            reasons.append("restricted_contact_placeholder_exposure")
        if has_process_facts and _HIGH_CERTAINTY_PATTERN.search(answer_text):
            lowered = answer_text.casefold()
            if "not officially verified" not in lowered and "community-discussed" not in lowered:
                reasons.append("government_process_over_certainty")
        return reasons

    def _pick_action(self, reasons: list[str], context: QueryContext) -> str:
        if not reasons:
            return "pass"
        restricted = any(
            fact.privacy_status in ("needs_review", "restricted", "blocked")
            for fact in context.facts
        )
        if restricted or "government_process_over_certainty" in reasons:
            return "refuse_safely"
        return "redact"

    def _record_event(
        self,
        *,
        trace_id: str,
        query_id: str,
        action: str,
        reasons: list[str],
        sanitized_answer: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO guardrail_events (
              guardrail_event_id, trace_id, query_id, fact_id,
              guardrail_name, action, reason, sanitized_payload_json, created_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                f"guardrail_{uuid.uuid4().hex}",
                trace_id,
                query_id,
                GUARDRAIL_VERSION,
                action,
                "; ".join(reasons),
                (
                    '{"reasons": ' +
                    str(reasons).replace("'", '"') +
                    ', "sanitized_answer_preview": ' +
                    '"' + sanitized_answer[:160].replace('"', "'") + '"}'
                ),
                utc_now_iso(),
            ),
        )
from __future__ import annotations

from aptjeeves.answering.formatter import AnswerResponse
from aptjeeves.answering.guardrails import GuardrailValidator
from aptjeeves.retrieval.context import FactContext, QueryContext
from aptjeeves.storage.db import apply_migrations, connect


def _make_fact(**overrides) -> FactContext:
    defaults = dict(
        fact_id="fact_1",
        fact_type="service_contact",
        title="Plumber contact",
        summary="Residents mentioned a plumber.",
        source_count=2,
        latest_seen="2026-04-16T09:30:00Z",
        confidence=0.7,
        privacy_status="public_to_residents",
        approved_contact_methods=[],
        sanitized_snippets=["Call PHONE_1 for plumbing."],
        caveats=[],
        details={"service_type": "plumber"},
        final_score=0.8,
    )
    defaults.update(overrides)
    return FactContext(**defaults)


def _make_context(facts: list[FactContext]) -> QueryContext:
    return QueryContext(query_id="query_test", intent="find_service_contact", facts=facts)


def _make_answer(text: str) -> AnswerResponse:
    return AnswerResponse(
        answer=text,
        citations=[],
        confidence="medium",
        privacy_note=None,
        query_id="query_test",
        intent="find_service_contact",
    )


def test_guardrail_refuses_restricted_placeholder_exposure(tmp_path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)

    validator = GuardrailValidator(connection)
    fact = _make_fact(privacy_status="needs_review")
    decision = validator.validate(
        _make_answer("The plumber is available at PHONE_1."),
        context=_make_context([fact]),
        trace_id="trace_test",
    )

    assert decision.action == "refuse_safely"
    assert "cannot share" in decision.answer.answer.lower()


def test_guardrail_allows_public_placeholder_value(tmp_path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)

    validator = GuardrailValidator(connection)
    decision = validator.validate(
        _make_answer("Residents suggested PHONE_1 for plumbing."),
        context=_make_context([_make_fact(privacy_status="public_to_residents")]),
        trace_id="trace_test",
    )

    assert decision.action == "pass"
    assert decision.answer.answer == "Residents suggested PHONE_1 for plumbing."
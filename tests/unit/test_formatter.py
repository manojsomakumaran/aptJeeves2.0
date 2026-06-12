from __future__ import annotations

from aptjeeves.answering.formatter import AnswerFormatter, Citation
from aptjeeves.retrieval.context import FactContext, QueryContext


def _make_context(facts: list[FactContext] | None = None) -> QueryContext:
    return QueryContext(
        query_id="query_test",
        intent="find_service_contact",
        facts=facts or [],
    )


def _make_fact(**overrides) -> FactContext:
    defaults = dict(
        fact_id="fact_1",
        fact_type="service_contact",
        title="Plumber contact",
        summary="Residents mentioned a plumber.",
        source_count=3,
        latest_seen="2026-04-16T09:30:00Z",
        confidence=0.75,
        privacy_status="public_to_residents",
        approved_contact_methods=[],
        sanitized_snippets=["Call PHONE_1 for plumbing."],
        caveats=[],
        details={"service_type": "plumber"},
        final_score=0.8,
    )
    defaults.update(overrides)
    return FactContext(**defaults)


def test_no_facts_returns_no_info_answer() -> None:
    formatter = AnswerFormatter()
    answer = formatter.answer(_make_context())
    assert "don't have enough information" in answer.answer
    assert answer.confidence == "none"
    assert answer.citations == []


def test_single_fact_produces_answer_with_citation() -> None:
    fact = _make_fact()
    formatter = AnswerFormatter()
    answer = formatter.answer(_make_context([fact]))
    assert "plumber" in answer.answer.lower()
    assert len(answer.citations) == 1
    assert answer.citations[0].fact_id == "fact_1"
    assert answer.citations[0].source_count == 3


def test_privacy_restricted_fact_adds_privacy_note() -> None:
    fact = _make_fact(privacy_status="needs_review")
    formatter = AnswerFormatter()
    answer = formatter.answer(_make_context([fact]))
    assert answer.privacy_note is not None
    assert "restricted" in answer.privacy_note.lower() or "privacy" in answer.privacy_note.lower()


def test_process_info_includes_steps() -> None:
    fact = _make_fact(
        fact_type="process_info",
        title="Gas address update",
        summary="Residents discussed updating gas address.",
        details={
            "steps_json": '["Visit provider office", "Submit address proof"]',
            "required_documents_json": '["Address proof"]',
            "fees_json": "[]",
        },
        caveats=["Community-discussed information; not officially verified."],
    )
    formatter = AnswerFormatter()
    answer = formatter.answer(_make_context([fact]))
    assert "Visit provider office" in answer.answer
    assert "Address proof" in answer.answer


def test_to_json_serialization() -> None:
    fact = _make_fact()
    formatter = AnswerFormatter()
    answer = formatter.answer(_make_context([fact]))
    output = formatter.to_json(answer)
    assert output["query_id"] == "query_test"
    assert output["intent"] == "find_service_contact"
    assert isinstance(output["citations"], list)
    assert output["citations"][0]["fact_id"] == "fact_1"

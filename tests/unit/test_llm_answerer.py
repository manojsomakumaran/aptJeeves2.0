from __future__ import annotations

from unittest.mock import MagicMock, patch

from aptjeeves.answering.llm_answerer import LLMAnswerer, _overall_confidence
from aptjeeves.retrieval.context import FactContext, QueryContext


def _make_context(facts=None):
    return QueryContext(
        query_id="query_abc123",
        intent="find_service_contact",
        facts=facts or [],
    )


def _make_fact(**overrides):
    defaults = dict(
        fact_id="fact_1",
        fact_type="service_contact",
        title="Plumber",
        summary="Residents mentioned a plumber.",
        source_count=3,
        latest_seen="2026-04-16T09:30:00Z",
        confidence=0.75,
        privacy_status="public_to_residents",
        approved_contact_methods=[],
        sanitized_snippets=["Plumber available."],
        caveats=[],
        details={"service_type": "plumber"},
        final_score=0.8,
    )
    defaults.update(overrides)
    return FactContext(**defaults)


def _mock_openai_response(text: str):
    choice = MagicMock()
    choice.message.content = text
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def test_llm_answerer_empty_context_returns_no_info():
    with patch("aptjeeves.answering.llm_answerer.OpenAI"):
        answerer = LLMAnswerer(api_key="test-key", model="gpt-4.1-mini")
    result = answerer.answer(_make_context([]), query="plumber?")
    assert result.confidence == "none"
    assert result.citations == []
    assert "don't have enough" in result.answer.lower() or "not" in result.answer.lower()


def test_llm_answerer_calls_openai_with_query():
    with patch("aptjeeves.answering.llm_answerer.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "The plumber is available at [PHONE_1]."
        )
        answerer = LLMAnswerer(api_key="test-key", model="gpt-4.1-mini")
        result = answerer.answer(_make_context([_make_fact()]), query="Who is the plumber?")

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4.1-mini"
    assert call_kwargs["temperature"] == 0.1
    messages = call_kwargs["messages"]
    assert any("Who is the plumber?" in m.get("content", "") for m in messages)

    assert result.answer == "The plumber is available at [PHONE_1]."
    assert len(result.citations) == 1
    assert result.citations[0].fact_id == "fact_1"


def test_llm_answerer_with_langfuse_trace():
    null_trace = MagicMock()
    null_generation = MagicMock()
    null_trace.start_generation.return_value = null_generation
    null_langfuse = MagicMock()
    null_langfuse.trace.return_value = null_trace

    with patch("aptjeeves.answering.llm_answerer.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response("Plumber info.")
        answerer = LLMAnswerer(
            api_key="test-key",
            model="gpt-4.1-mini",
            langfuse_client=null_langfuse,
        )
        result = answerer.answer(_make_context([_make_fact()]), query="plumber?")

    null_langfuse.trace.assert_called_once()
    null_trace.start_generation.assert_called_once()
    null_generation.end.assert_called_once()
    assert result.answer == "Plumber info."


def test_overall_confidence_high():
    facts = [_make_fact(confidence=0.9), _make_fact(confidence=0.85)]
    assert _overall_confidence(facts) == "high"


def test_overall_confidence_medium():
    facts = [_make_fact(confidence=0.5), _make_fact(confidence=0.6)]
    assert _overall_confidence(facts) == "medium"


def test_overall_confidence_low():
    facts = [_make_fact(confidence=0.2), _make_fact(confidence=0.3)]
    assert _overall_confidence(facts) == "low"


def test_overall_confidence_none():
    assert _overall_confidence([]) == "none"

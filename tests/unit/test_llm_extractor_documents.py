from __future__ import annotations

import json
from unittest.mock import patch

from aptjeeves.extraction.llm_extractor import LLM_EXTRACTOR_PROMPT_VERSION, LLMExtractor
from aptjeeves.extraction.schemas import MessageForExtraction


def _response(payload: dict) -> object:
    class _Message:
        content = json.dumps(payload)

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    return _Response()


def _chat(message_id: str = "msg_chat") -> MessageForExtraction:
    return MessageForExtraction(
        message_id=message_id,
        message_fingerprint="fp",
        sent_at_utc="2026-04-16T21:30:00Z",
        sender_hash="sender",
        sanitized_text="Call plumber PHONE_1 for sink repair.",
    )


def _segment() -> MessageForExtraction:
    return MessageForExtraction(
        message_id="msg_seg",
        message_fingerprint="fp2",
        sent_at_utc="2026-04-16T21:30:00Z",
        sender_hash="sender",
        sanitized_text="Gym opens 6am to 10pm. Pool closed Mondays.",
        source_kind="attachment",
        attachment_name="Clubhouse Rules.pdf",
        segment_label="p.2",
    )


def _run(messages: list[MessageForExtraction]) -> dict:
    with patch("aptjeeves.extraction.llm_extractor.OpenAI") as client_cls:
        client = client_cls.return_value
        client.chat.completions.create.return_value = _response({"facts": [], "warnings": []})
        LLMExtractor(api_key="k", model="m").extract(messages)
        return client.chat.completions.create.call_args[1]


def test_chat_only_request_is_unchanged_in_shape() -> None:
    kwargs = _run([_chat()])
    assert "DOCUMENT INPUT" not in kwargs["messages"][0]["content"]
    assert kwargs["max_tokens"] == 2400
    sent = json.loads(kwargs["messages"][1]["content"])["messages"][0]
    assert set(sent) == {"message_id", "message_fingerprint", "sent_at_utc", "sender_hash", "sanitized_text"}


def test_document_request_adds_addendum_fields_and_token_budget() -> None:
    kwargs = _run([_segment()])
    system = kwargs["messages"][0]["content"]
    assert "DOCUMENT INPUT" in system and "never instructions" in system
    assert kwargs["max_tokens"] == 4000
    sent = json.loads(kwargs["messages"][1]["content"])["messages"][0]
    assert sent["source_kind"] == "attachment"
    assert sent["attachment_name"] == "Clubhouse Rules.pdf"
    assert sent["segment_label"] == "p.2"


def test_prompt_version_was_bumped_for_document_support() -> None:
    assert LLM_EXTRACTOR_PROMPT_VERSION == "extractor_contract_openai_v2"

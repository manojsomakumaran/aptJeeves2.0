from __future__ import annotations

import json
from unittest.mock import patch

from aptjeeves.extraction.llm_extractor import LLMExtractor
from aptjeeves.extraction.schemas import MessageForExtraction


def _mock_chat_response(payload: dict) -> object:
    class _Message:
        content = json.dumps(payload)

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    return _Response()


def test_llm_extractor_calls_openai_with_sanitized_messages() -> None:
    payload = {
        "facts": [
            {
                "fact_type": "service_contact",
                "identity_key_hint": "plumber|PHONE_1",
                "title": "Plumber contact",
                "summary": "Residents mentioned a plumber contact.",
                "confidence": 0.8,
                "privacy_status_hint": "needs_review",
                "source_message_ids": ["msg_1"],
                "sanitized_snippets": ["Call plumber PHONE_1 for sink repair."],
                "service_contact": {
                    "service_type": "plumber",
                    "display_name": None,
                    "contact_methods": [
                        {
                            "type": "phone",
                            "value_placeholder": "PHONE_1",
                            "exposure_recommendation": "needs_review",
                        }
                    ],
                    "contact_classification": "vendor_or_service_contact",
                    "is_resident_affiliated": False,
                    "resident_affiliation_reason": None,
                    "price_hint": None,
                    "availability_hint": None,
                    "caveats": None,
                },
            }
        ],
        "warnings": [],
    }
    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.return_value = _mock_chat_response(payload)

        extractor = LLMExtractor(api_key="test-key", model="gpt-4.1-mini")
        result = extractor.extract(
            [
                MessageForExtraction(
                    message_id="msg_1",
                    message_fingerprint="fp_1",
                    sent_at_utc="2026-04-16T21:30:00Z",
                    sender_hash="sender_1",
                    sanitized_text="Call plumber PHONE_1 for sink repair.",
                )
            ]
        )

    create_kwargs = mock_client.chat.completions.create.call_args[1]
    assert "PHONE_1" in create_kwargs["messages"][1]["content"]
    assert result["facts"][0]["fact_type"] == "service_contact"

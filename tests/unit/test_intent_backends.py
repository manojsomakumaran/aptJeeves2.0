from __future__ import annotations

import json
from unittest.mock import patch

from aptjeeves.retrieval.intent import OpenAIIntentClassifier


def _mock_intent_response(payload: dict) -> object:
    class _Message:
        content = json.dumps(payload)

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    return _Response()


def test_openai_intent_classifier_maps_provider_output() -> None:
    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.return_value = _mock_intent_response(
            {
                "intent": "ask_process_steps",
                "confidence": 0.82,
                "matched_keywords": ["gas address"],
            }
        )
        classifier = OpenAIIntentClassifier(api_key="test-key", model="gpt-4.1-mini")
        result = classifier.classify("How to update gas address?")

    assert result.intent == "ask_process_steps"
    assert result.confidence == 0.82
    assert result.matched_keywords == ["gas address"]


def test_openai_intent_classifier_falls_back_to_keyword() -> None:
    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.side_effect = RuntimeError("provider down")
        classifier = OpenAIIntentClassifier(api_key="test-key", model="gpt-4.1-mini")
        result = classifier.classify("Who is a good plumber?")

    assert result.intent == "find_service_contact"

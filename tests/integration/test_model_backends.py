from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from aptjeeves.cli import main


def _mock_response(payload: dict) -> object:
    class _Message:
        content = json.dumps(payload)

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    return _Response()


def test_cli_extract_pending_uses_openai_backend(tmp_path: Path, capsys, monkeypatch) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APTJEEVES_EXTRACTION_BACKEND", "openai")

    with patch("aptjeeves.extraction.llm_extractor.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.return_value = _mock_response(
            {
                "facts": [
                    {
                        "fact_type": "service_contact",
                        "identity_key_hint": "plumber|PHONE_1",
                        "title": "Plumber contact",
                        "summary": "Residents mentioned a plumber contact.",
                        "confidence": 0.8,
                        "privacy_status_hint": "needs_review",
                        "source_message_ids": ["msg_bb210059cda2db0bc00f1e9c3a891d23"],
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
        )

        assert main(
            [
                "--db",
                str(db_path),
                "ingest",
                "--platform",
                "whatsapp",
                "--file",
                str(export_path),
                "--chat-name",
                "Main",
            ]
        ) == 0
        capsys.readouterr()
        assert main(["--db", str(db_path), "extract-pending"]) == 0
        output = json.loads(capsys.readouterr().out)

    assert output["extractor"] == "openai"
    assert output["facts_upserted"] == 1


def test_ask_falls_back_to_keyword_intent_when_provider_classifier_fails(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APTJEEVES_INTENT_BACKEND", "openai")
    monkeypatch.setenv("APTJEEVES_EMBEDDING_MODEL", "local")
    monkeypatch.setenv("APTJEEVES_LLM_PROVIDER", "disabled")

    assert main(
        [
            "--db",
            str(db_path),
            "ingest",
            "--platform",
            "whatsapp",
            "--file",
            str(export_path),
            "--chat-name",
            "Main",
        ]
    ) == 0
    capsys.readouterr()
    assert main(["--db", str(db_path), "extract-pending"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db_path), "index-facts"]) == 0
    capsys.readouterr()

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = mock_openai_cls.return_value
        mock_client.chat.completions.create.side_effect = RuntimeError("provider down")
        assert main(["--db", str(db_path), "ask", "Who is a good plumber?"]) == 0
        output = json.loads(capsys.readouterr().out)

    assert output["intent"] == "find_service_contact"
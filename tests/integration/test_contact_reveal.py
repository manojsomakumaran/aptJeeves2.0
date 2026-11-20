from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptjeeves.answering.llm_answerer import _build_context_text
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.retrieval.service import QueryService
from aptjeeves.storage.db import apply_migrations, connect

NUMBER = "9876543210"


class _HelpdeskExtractor:
    """Stub extractor that, like the real LLM, only ever sees placeholders."""

    prompt_version = "stub_v1"
    model_version = "stub_v1"

    def __init__(self, privacy_status: str) -> None:
        self.privacy_status = privacy_status
        self.seen_text: list[str] = []

    def extract(self, messages: list[Any]) -> dict[str, Any]:
        self.seen_text = [m.sanitized_text for m in messages]
        msg = next(m for m in messages if "PHONE_1" in m.sanitized_text)
        return {
            "facts": [
                {
                    "fact_type": "service_contact",
                    "identity_key_hint": "helpdesk",
                    "title": "Helpdesk contact",
                    "summary": "Residents mentioned the helpdesk contact.",
                    "confidence": 0.9,
                    "privacy_status_hint": self.privacy_status,
                    "source_message_ids": [msg.message_id],
                    "sanitized_snippets": [msg.sanitized_text],
                    "service_contact": {
                        "service_type": "helpdesk",
                        "display_name": "Folium Helpdesk",
                        "contact_methods": [{"type": "phone", "value_placeholder": "PHONE_1"}],
                    },
                }
            ],
            "warnings": [],
        }


def _setup(tmp_path: Path, privacy_status: str):
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    export = tmp_path / "chat.txt"
    export.write_text(
        f"16/04/26, 9:30 PM - Alice: Helpdesk number is {NUMBER} for any facility issue.\n",
        encoding="utf-8",
    )
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export, chat_name="Main")
    )
    extractor = _HelpdeskExtractor(privacy_status)
    ExtractionService(connection, extractor).extract_pending()
    VectorIndexingService(connection).index_pending()
    return connection, extractor


def test_service_number_is_restored_in_answer_but_never_seen_by_llm(tmp_path: Path) -> None:
    connection, extractor = _setup(tmp_path, "public_to_residents")

    # The extractor (LLM) only saw the placeholder.
    assert all(NUMBER not in text for text in extractor.seen_text)

    # The original number is kept locally on the service contact.
    methods = json.loads(
        connection.execute("SELECT contact_methods_json FROM service_contacts").fetchone()[0]
    )
    assert methods[0]["value"] == NUMBER

    # The answer LLM context carries an opaque token, not the number.
    qs = QueryService(connection)
    answer = qs.ask("helpdesk contact number")
    context = qs.context_builder.build(
        query_id="q", intent="find_service_contact", ranked_facts=qs.reranker.rerank(
            qs.retriever.retrieve("helpdesk contact number"), intent="find_service_contact"
        ),
    )
    prompt_text = _build_context_text(context)
    assert NUMBER not in prompt_text
    assert "CONTACTREF_1" in prompt_text

    # The final answer shows the real number and no placeholder or token.
    assert NUMBER in answer.answer
    assert "PHONE_1" not in answer.answer and "CONTACTREF" not in answer.answer


def test_non_public_contact_number_is_not_restored(tmp_path: Path) -> None:
    connection, _ = _setup(tmp_path, "restricted_resident_pii")

    methods = json.loads(
        connection.execute("SELECT contact_methods_json FROM service_contacts").fetchone()[0]
    )
    assert "value" not in methods[0]
    assert NUMBER not in QueryService(connection).ask("helpdesk contact number").answer


def test_reimport_backfills_numbers_for_existing_facts(tmp_path: Path) -> None:
    connection, _ = _setup(tmp_path, "public_to_residents")
    # Simulate facts/messages created before the vault existed.
    connection.execute("DELETE FROM message_pii")
    connection.execute(
        "UPDATE service_contacts SET contact_methods_json = ?",
        (json.dumps([{"type": "phone", "value_placeholder": "PHONE_1"}]),),
    )
    connection.commit()

    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=tmp_path / "chat.txt", chat_name="Main")
    )

    methods = json.loads(
        connection.execute("SELECT contact_methods_json FROM service_contacts").fetchone()[0]
    )
    assert methods[0]["value"] == NUMBER

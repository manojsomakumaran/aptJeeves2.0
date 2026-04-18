from __future__ import annotations

import json
from pathlib import Path

from aptjeeves.cli import main
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect, utc_now_iso
from aptjeeves.storage.repositories import CanonicalFactRepository, VectorEntryRepository


def test_vector_indexing_creates_sanitized_vector_entry(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    _ingest_and_extract_plumber(connection, tmp_path)

    vector_ids = VectorIndexingService(connection).index_pending()

    assert len(vector_ids) == 1
    vectors = VectorEntryRepository(connection).list_active()
    assert len(vectors) == 1
    assert vectors[0]["status"] == "active"
    assert vectors[0]["fact_type"] == "service_contact"
    assert "9876543210" not in vectors[0]["embedding_text"]
    assert "PHONE_1" in vectors[0]["embedding_text"]
    assert json.loads(vectors[0]["embedding_json"])


def test_vector_indexing_is_idempotent_when_fact_version_is_current(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    _ingest_and_extract_plumber(connection, tmp_path)
    service = VectorIndexingService(connection)

    first = service.index_pending()
    second = service.index_pending()

    assert len(first) == 1
    assert second == []
    assert VectorEntryRepository(connection).count_active() == 1


def test_vector_indexing_refreshes_when_fact_version_changes(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    _ingest_and_extract_plumber(connection, tmp_path)
    service = VectorIndexingService(connection)
    first_vector_id = service.index_pending()[0]
    fact = CanonicalFactRepository(connection).list_facts()[0]

    connection.execute(
        """
        UPDATE canonical_facts
        SET summary = ?, fact_version = fact_version + 1, updated_at = ?
        WHERE fact_id = ?
        """,
        ("Residents strongly recommended this plumber.", utc_now_iso(), fact["fact_id"]),
    )
    refreshed = service.index_pending()

    assert refreshed == [first_vector_id]
    vector = VectorEntryRepository(connection).get_active_by_fact_id(fact["fact_id"])
    assert vector["fact_version"] == fact["fact_version"] + 1
    assert "strongly recommended" in vector["embedding_text"]


def test_cli_index_facts_uses_local_embedding_model(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )

    assert (
        main(
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
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--db", str(db_path), "extract-pending"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db_path), "index-facts"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "completed"
    assert output["vectors_upserted"] == 1
    assert output["embedding_model"] == "local_token_vector_v1"


def _ingest_and_extract_plumber(connection, tmp_path: Path) -> None:
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )
    ExtractionService(connection, FakeExtractor()).extract_pending()

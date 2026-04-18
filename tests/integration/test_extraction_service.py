from __future__ import annotations

import json
from pathlib import Path

from aptjeeves.cli import main
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import CanonicalFactRepository, RawMessageRepository


def test_fake_extraction_upserts_service_contact_from_sanitized_message(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )

    fact_ids = ExtractionService(connection, FakeExtractor()).extract_pending()

    assert len(fact_ids) == 1
    fact_repo = CanonicalFactRepository(connection)
    fact = fact_repo.get_fact(fact_ids[0])
    assert fact["fact_type"] == "service_contact"
    assert fact["source_count"] == 1
    assert fact["privacy_status"] == "needs_review"
    evidence = fact_repo.list_evidence(fact_ids[0])
    assert len(evidence) == 1
    assert "9876543210" not in evidence[0]["sanitized_snippet"]
    assert "PHONE_1" in evidence[0]["sanitized_snippet"]
    assert RawMessageRepository(connection).list_all()[0]["processing_status"] == "extracted"


def test_fake_extraction_merges_same_service_contact_across_messages(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "\n".join(
            [
                "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
                "17/04/26, 9:30 PM - Bob: Same plumber PHONE_1 helped us too.",
            ]
        ),
        encoding="utf-8",
    )
    # The second message already contains the placeholder because this test is
    # about canonical merge behavior, not redaction detection.
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )

    fact_ids = ExtractionService(connection, FakeExtractor()).extract_pending()

    assert len(fact_ids) == 2
    facts = CanonicalFactRepository(connection).list_facts()
    assert len(facts) == 1
    assert facts[0]["source_count"] == 2


def test_fake_extraction_handles_process_and_facility_facts(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "\n".join(
            [
                "16/04/26, 9:30 PM - Alice: Gas address update needs address proof.",
                "16/04/26, 9:35 PM - Bob: Clubhouse booking is done at facility office.",
            ]
        ),
        encoding="utf-8",
    )
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )

    fact_ids = ExtractionService(connection, FakeExtractor()).extract_pending()

    assert len(fact_ids) == 2
    fact_types = {row["fact_type"] for row in CanonicalFactRepository(connection).list_facts()}
    assert fact_types == {"process_info", "facility_info"}


def test_fake_extraction_marks_no_extractable_info(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    export_path = tmp_path / "chat.txt"
    export_path.write_text("16/04/26, 9:30 PM - Alice: Thanks everyone.", encoding="utf-8")
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )

    fact_ids = ExtractionService(connection, FakeExtractor()).extract_pending()

    assert fact_ids == []
    assert RawMessageRepository(connection).list_all()[0]["processing_status"] == "no_extractable_info"


def test_cli_extract_pending_uses_fake_extractor(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
        encoding="utf-8",
    )

    ingest_exit = main(
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
    capsys.readouterr()
    extract_exit = main(["--db", str(db_path), "extract-pending"])
    output = json.loads(capsys.readouterr().out)

    assert ingest_exit == 0
    assert extract_exit == 0
    assert output["status"] == "completed"
    assert output["facts_upserted"] == 1
    assert output["extractor"] == "fake"

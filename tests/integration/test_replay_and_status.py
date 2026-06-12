from __future__ import annotations

import json
from pathlib import Path

from aptjeeves.cli import main
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect


def _setup_ingested_db(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "aptjeeves.sqlite3"
    connection = connect(db_path)
    apply_migrations(connection)

    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "\n".join(
            [
                "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
                "16/04/26, 9:35 PM - Bob: Gas address update needs address proof and ID.",
            ]
        ),
        encoding="utf-8",
    )
    summary = ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )
    connection.close()
    return db_path, summary.import_batch_id


def _setup_indexed_db(tmp_path: Path) -> Path:
    db_path, _ = _setup_ingested_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)
    ExtractionService(connection, FakeExtractor()).extract_pending()
    VectorIndexingService(connection).index_pending()
    connection.close()
    return db_path


def test_query_status_reports_query_summary(tmp_path: Path, capsys) -> None:
    db_path = _setup_indexed_db(tmp_path)

    assert main(["--db", str(db_path), "ask", "plumber contact"]) == 0
    ask_output = json.loads(capsys.readouterr().out)

    assert main(["--db", str(db_path), "query-status", "--query-id", ask_output["query_id"]]) == 0
    status = json.loads(capsys.readouterr().out)

    assert status["query_id"] == ask_output["query_id"]
    assert status["status"] == "completed"
    assert status["query_intent"] == "find_service_contact"
    assert status["guardrail_events_count"] == 1


def test_replay_query_creates_new_query_run(tmp_path: Path, capsys) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    assert main(["--db", str(db_path), "ask", "plumber 9876543210 contact"]) == 0
    first_output = json.loads(capsys.readouterr().out)

    assert main(["--db", str(db_path), "replay-query", "--query-id", first_output["query_id"]]) == 0
    replay_output = json.loads(capsys.readouterr().out)

    rows = connection.execute(
        "SELECT query_id, query_text_redacted FROM query_runs ORDER BY created_at, query_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["query_id"] == first_output["query_id"]
    assert rows[0]["query_text_redacted"] == rows[1]["query_text_redacted"]
    assert replay_output["query_id"] != first_output["query_id"]


def test_replay_import_reruns_extraction_and_indexing(tmp_path: Path, capsys) -> None:
    db_path, import_batch_id = _setup_ingested_db(tmp_path)

    assert main(
        [
            "--db",
            str(db_path),
            "replay-import",
            "--batch",
            import_batch_id,
            "--from-stage",
            "extraction",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["import_batch_id"] == import_batch_id
    assert output["extraction_failures"] == 0
    assert output["fact_ids"]
    assert output["vector_ids"]
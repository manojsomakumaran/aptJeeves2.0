from __future__ import annotations

import json
from pathlib import Path

from aptjeeves.cli import main
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.retrieval.service import QueryService
from aptjeeves.storage.db import apply_migrations, connect


def _setup_indexed_db(tmp_path: Path) -> Path:
    """Ingest, extract, and index a small test corpus. Return db path."""

    db_path = tmp_path / "aptjeeves.sqlite3"
    connection = connect(db_path)
    apply_migrations(connection)

    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "\n".join(
            [
                "16/04/26, 9:30 PM - Alice: Call plumber 9876543210 for sink repair.",
                "16/04/26, 9:35 PM - Bob: Gas address update needs address proof and ID.",
                "16/04/26, 9:40 PM - Carol: Clubhouse booking is done at the facility office.",
            ]
        ),
        encoding="utf-8",
    )
    ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )
    ExtractionService(connection, FakeExtractor()).extract_pending()
    VectorIndexingService(connection).index_pending()
    connection.close()
    return db_path


def test_ask_retrieves_plumber_fact(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("Who is a good plumber?")

    assert answer.confidence != "none"
    assert any("plumber" in c.snippet.lower() or "plumb" in c.snippet.lower() for c in answer.citations)
    assert answer.intent == "find_service_contact"


def test_ask_retrieves_gas_process(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("How to update gas address?")

    assert answer.confidence != "none"
    assert answer.intent == "ask_process_steps"


def test_ask_retrieves_facility_info(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("How do I book the clubhouse?")

    assert answer.confidence != "none"
    assert answer.intent == "ask_facility_info"


def test_ask_no_results_for_unknown_topic(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("xyzzy foobar quux")

    assert answer.confidence in ("none", "low")


def test_ask_writes_retrieval_trace(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("plumber contact")

    traces = connection.execute("SELECT * FROM retrieval_traces").fetchall()
    assert len(traces) == 1
    assert traces[0]["query_intent"] == "find_service_contact"
    assert answer.query_id == traces[0]["query_id"]


def test_ask_emits_pipeline_event(tmp_path: Path) -> None:
    db_path = _setup_indexed_db(tmp_path)
    connection = connect(db_path)
    apply_migrations(connection)

    answer = QueryService(connection).ask("plumber")

    events = connection.execute(
        "SELECT * FROM pipeline_events WHERE event_type = 'query_answered'"
    ).fetchall()
    assert len(events) == 1
    payload = json.loads(events[0]["sanitized_payload_json"])
    assert payload["intent"] == "find_service_contact"


def test_cli_ask_outputs_json(tmp_path: Path, capsys) -> None:
    db_path = _setup_indexed_db(tmp_path)

    exit_code = main(["--db", str(db_path), "ask", "plumber contact"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert "answer" in output
    assert "citations" in output
    assert "confidence" in output
    assert output["intent"] == "find_service_contact"

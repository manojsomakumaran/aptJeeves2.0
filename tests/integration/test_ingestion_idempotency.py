from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aptjeeves.cli import main
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import RawMessageRepository


def _write_export(path: Path, extra: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                "16/04/26, 9:30 PM - Alice: Contact Ramesh for plumbing.",
                "16/04/26, 9:35 PM - Bob: Thanks Alice.",
                "<media omitted>",
                extra,
            ]
        ).strip(),
        encoding="utf-8",
    )


def _write_telegram_export(path: Path, extra_message: dict | None = None) -> None:
    messages = [
        {
            "id": 101,
            "type": "message",
            "date_unixtime": "1776355200",
            "from": "Alice",
            "from_id": "user1",
            "text": "Contact Ramesh for plumbing.",
        },
        {
            "id": 102,
            "type": "message",
            "date_unixtime": "1776355500",
            "from": "Bob",
            "from_id": "user2",
            "text": "Thanks Alice.",
        },
    ]
    if extra_message is not None:
        messages.append(extra_message)
    path.write_text(
        json.dumps({"id": 98765, "name": "Apartment Main", "messages": messages}),
        encoding="utf-8",
    )


def test_ingesting_same_export_twice_skips_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    _write_export(export_path)

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    first = service.ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Apartment Main")
    )
    second = service.ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Apartment Main")
    )

    assert first.status == "completed"
    assert first.total_messages_seen == 2
    assert first.new_messages_inserted == 2
    assert first.duplicate_messages_skipped == 0
    assert second.status == "completed"
    assert second.total_messages_seen == 2
    assert second.new_messages_inserted == 0
    assert second.duplicate_messages_skipped == 2
    assert RawMessageRepository(connection).count() == 2

    event_counts = _event_counts(connection)
    assert event_counts["raw_message_inserted"] == 2
    assert event_counts["duplicate_message_skipped"] == 2


def test_ingesting_expanded_export_only_adds_new_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    _write_export(export_path)

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    service.ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Apartment Main")
    )
    _write_export(export_path, "16/04/26, 9:45 PM - Carol: Any electrician contact?")
    second = service.ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Apartment Main")
    )

    assert second.total_messages_seen == 3
    assert second.new_messages_inserted == 1
    assert second.duplicate_messages_skipped == 2
    assert RawMessageRepository(connection).count() == 3


def test_cli_ingest_outputs_import_summary(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    _write_export(export_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ingest",
            "--platform",
            "whatsapp",
            "--file",
            str(export_path),
            "--chat-name",
            "Apartment Main",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["new_messages_inserted"] == 2
    assert output["duplicate_messages_skipped"] == 0
    assert output["db_path"] == str(db_path)
    assert output["chat_name"] == "Apartment Main"


def test_cli_infers_chat_name_from_export_filename(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "WhatsApp Chat with Tower A Vendors.txt"
    _write_export(export_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ingest",
            "--platform",
            "whatsapp",
            "--file",
            str(export_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["chat_name"] == "Tower A Vendors"


def test_cli_apartment_selects_isolated_database(tmp_path: Path, capsys, monkeypatch) -> None:
    export_path = tmp_path / "chat.txt"
    data_dir = tmp_path / "data"
    _write_export(export_path)
    monkeypatch.setenv("APTJEEVES_DATA_DIR", str(data_dir))

    first_exit = main(
        [
            "ingest",
            "--platform",
            "whatsapp",
            "--file",
            str(export_path),
            "--apartment",
            "Green Acres",
        ]
    )
    first_output = json.loads(capsys.readouterr().out)

    second_exit = main(
        [
            "ingest",
            "--platform",
            "whatsapp",
            "--file",
            str(export_path),
            "--apartment",
            "Lake View",
        ]
    )
    second_output = json.loads(capsys.readouterr().out)

    assert first_exit == 0
    assert second_exit == 0
    assert first_output["new_messages_inserted"] == 2
    assert second_output["new_messages_inserted"] == 2
    assert first_output["db_path"] == str(
        data_dir / "apartments" / "green-acres" / "aptjeeves.sqlite3"
    )
    assert second_output["db_path"] == str(
        data_dir / "apartments" / "lake-view" / "aptjeeves.sqlite3"
    )
    assert Path(first_output["db_path"]).exists()
    assert Path(second_output["db_path"]).exists()


def test_ingesting_same_telegram_export_twice_skips_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "telegram-result.json"
    _write_telegram_export(export_path)

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    first = service.ingest(IngestRequest(platform="telegram", file_path=export_path))
    second = service.ingest(IngestRequest(platform="telegram", file_path=export_path))

    assert first.status == "completed"
    assert first.chat_name == "Apartment Main"
    assert first.total_messages_seen == 2
    assert first.new_messages_inserted == 2
    assert second.new_messages_inserted == 0
    assert second.duplicate_messages_skipped == 2
    assert RawMessageRepository(connection).count() == 2

    rows = RawMessageRepository(connection).list_all()
    assert [row["source_message_id"] for row in rows] == ["101", "102"]
    assert {row["platform"] for row in rows} == {"telegram"}


def test_ingesting_expanded_telegram_export_only_adds_new_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "telegram-result.json"
    _write_telegram_export(export_path)

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    service.ingest(IngestRequest(platform="telegram", file_path=export_path))
    _write_telegram_export(
        export_path,
        {
            "id": 103,
            "type": "message",
            "date_unixtime": "1776355800",
            "from": "Carol",
            "from_id": "user3",
            "text": "Any electrician contact?",
        },
    )
    second = service.ingest(IngestRequest(platform="telegram", file_path=export_path))

    assert second.total_messages_seen == 3
    assert second.new_messages_inserted == 1
    assert second.duplicate_messages_skipped == 2
    assert RawMessageRepository(connection).count() == 3


def test_cli_telegram_ingest_uses_chat_name_from_file(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "result.json"
    _write_telegram_export(export_path)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ingest",
            "--platform",
            "telegram",
            "--file",
            str(export_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["chat_name"] == "Apartment Main"
    assert output["new_messages_inserted"] == 2


def test_whatsapp_ingestion_stores_sanitized_text(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Call Ramesh 9876543210 from B-1204 or ramesh@example.com",
        encoding="utf-8",
    )

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    service.ingest(IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main"))

    row = RawMessageRepository(connection).list_all()[0]
    assert "9876543210" not in row["sanitized_text"]
    assert "B-1204" not in row["sanitized_text"]
    assert "ramesh@example.com" not in row["sanitized_text"]
    assert "Ramesh" not in row["sanitized_text"]
    assert "PHONE_1" in row["sanitized_text"]
    assert "FLAT_1" in row["sanitized_text"]
    assert "EMAIL_1" in row["sanitized_text"]
    assert "CONTACT_1" in row["sanitized_text"]

    redaction_event = connection.execute(
        """
        SELECT sanitized_payload_json
        FROM pipeline_events
        WHERE event_type = 'raw_message_inserted'
        """
    ).fetchone()
    payload = json.loads(redaction_event["sanitized_payload_json"])
    assert payload["redaction_counts"] == {"CONTACT": 1, "EMAIL": 1, "FLAT": 1, "PHONE": 1}


def test_telegram_ingestion_stores_sanitized_text(tmp_path: Path) -> None:
    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "telegram-result.json"
    _write_telegram_export(
        export_path,
        {
            "id": 103,
            "type": "message",
            "date_unixtime": "1776355800",
            "from": "Carol",
            "from_id": "user3",
            "text": "Use https://example.com and call 9876543210 from flat A-1001",
        },
    )

    connection = connect(db_path)
    apply_migrations(connection)
    service = ChatIngestionService(connection)

    service.ingest(IngestRequest(platform="telegram", file_path=export_path))

    rows = RawMessageRepository(connection).list_all()
    sanitized = rows[-1]["sanitized_text"]
    assert "https://example.com" not in sanitized
    assert "9876543210" not in sanitized
    assert "A-1001" not in sanitized
    assert "URL_1" in sanitized
    assert "PHONE_1" in sanitized
    assert "FLAT_1" in sanitized


def test_parse_failure_threshold_completed_with_errors_below_threshold(tmp_path: Path) -> None:
    """A failure rate below the threshold should produce completed_with_errors, not failed."""

    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    # 1 garbage line + 10 valid messages → 1/11 ≈ 9% failure rate
    lines = ["GARBAGE LINE NOT A MESSAGE"]
    for i in range(10):
        lines.append(f"16/04/26, {i + 1}:30 AM - Alice: Message number {i}.")
    export_path.write_text("\n".join(lines), encoding="utf-8")

    connection = connect(db_path)
    apply_migrations(connection)
    # Default threshold is 5%; 9% exceeds it — use a 20% threshold for this test.
    summary = ChatIngestionService(connection).ingest(
        IngestRequest(
            platform="whatsapp",
            file_path=export_path,
            chat_name="Main",
            max_parse_failure_rate=0.20,
        )
    )

    assert summary.status == "completed_with_errors"
    assert summary.parse_failures == 1
    assert summary.total_messages_seen == 10


def test_parse_failure_threshold_failed_when_rate_exceeded(tmp_path: Path) -> None:
    """A failure rate above the threshold should produce failed status."""

    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    # 5 garbage lines + 5 valid messages → 5/10 = 50% failure rate
    lines = [f"GARBAGE LINE {i}" for i in range(5)]
    for i in range(5):
        lines.append(f"16/04/26, {i + 1}:30 AM - Alice: Message number {i}.")
    export_path.write_text("\n".join(lines), encoding="utf-8")

    connection = connect(db_path)
    apply_migrations(connection)
    summary = ChatIngestionService(connection).ingest(
        IngestRequest(
            platform="whatsapp",
            file_path=export_path,
            chat_name="Main",
            max_parse_failure_rate=0.05,
        )
    )

    assert summary.status == "failed"
    assert summary.parse_failures == 5


def test_parse_failure_threshold_completed_when_no_failures(tmp_path: Path) -> None:
    """A clean export with zero failures should produce completed status."""

    db_path = tmp_path / "aptjeeves.sqlite3"
    export_path = tmp_path / "chat.txt"
    export_path.write_text(
        "16/04/26, 9:30 PM - Alice: Hello everyone.",
        encoding="utf-8",
    )

    connection = connect(db_path)
    apply_migrations(connection)
    summary = ChatIngestionService(connection).ingest(
        IngestRequest(platform="whatsapp", file_path=export_path, chat_name="Main")
    )

    assert summary.status == "completed"
    assert summary.parse_failures == 0


def _event_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM pipeline_events
        GROUP BY event_type
        """
    ).fetchall()
    return {row["event_type"]: row["count"] for row in rows}

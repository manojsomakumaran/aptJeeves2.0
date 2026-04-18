from __future__ import annotations

from aptjeeves.ingestion.parsers import TelegramJsonParser


def test_telegram_parser_reads_chat_metadata_and_messages() -> None:
    data = {
        "id": 123456,
        "name": "Apartment Main",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-04-16T21:30:00",
                "date_unixtime": "1776355200",
                "from": "Alice",
                "from_id": "user1",
                "text": "Hello",
            }
        ],
    }

    result = TelegramJsonParser().parse_data(data)

    assert result.failures == []
    assert result.chat_name == "Apartment Main"
    assert result.source_conversation_id == "123456"
    assert len(result.messages) == 1
    assert result.messages[0].source_message_id == "1"
    assert result.messages[0].sender == "user1"
    assert result.messages[0].sent_at_utc == "2026-04-16T16:00:00Z"


def test_telegram_parser_flattens_rich_text_parts() -> None:
    data = {
        "name": "Apartment Main",
        "messages": [
            {
                "id": 2,
                "type": "message",
                "date_unixtime": "1776355200",
                "from": "Alice",
                "text": [
                    "Call ",
                    {"type": "phone", "text": "PHONE_1"},
                    " for plumbing",
                ],
            }
        ],
    }

    result = TelegramJsonParser().parse_data(data)

    assert result.failures == []
    assert result.messages[0].text == "Call PHONE_1 for plumbing"


def test_telegram_parser_ignores_service_messages() -> None:
    data = {
        "name": "Apartment Main",
        "messages": [
            {"id": 1, "type": "service", "date_unixtime": "1776355200", "text": "title changed"},
            {"id": 2, "type": "message", "date_unixtime": "1776355200", "text": "Hi"},
        ],
    }

    result = TelegramJsonParser().parse_data(data)

    assert result.failures == []
    assert len(result.messages) == 1
    assert result.messages[0].source_message_id == "2"

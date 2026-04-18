from __future__ import annotations

from aptjeeves.ingestion.parsers import WhatsAppTextParser


def test_whatsapp_parser_handles_multiline_messages() -> None:
    text = "\n".join(
        [
            "16/04/26, 9:30 PM - Alice: First line",
            "second line",
            "16/04/26, 9:32 PM - Bob: Reply",
        ]
    )

    result = WhatsAppTextParser().parse_text(text)

    assert result.failures == []
    assert len(result.messages) == 2
    assert result.messages[0].sender == "Alice"
    assert result.messages[0].text == "First line\nsecond line"
    assert result.messages[0].source_line_start == 1
    assert result.messages[0].source_line_end == 2
    assert result.messages[1].sender == "Bob"


def test_whatsapp_parser_handles_bracketed_format() -> None:
    text = "[16/04/26, 9:30:10 PM] Alice: Hello"

    result = WhatsAppTextParser().parse_text(text)

    assert result.failures == []
    assert len(result.messages) == 1
    assert result.messages[0].time_text == "9:30:10 PM"

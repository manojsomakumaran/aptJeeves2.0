from __future__ import annotations

from aptjeeves.privacy.detectors import detect_sensitive_spans
from aptjeeves.privacy.redactor import redact_text


def test_redact_text_replaces_common_pii_with_placeholders() -> None:
    result = redact_text(
        "Call Ramesh 9876543210 or ramesh@example.com from B-1204. "
        "See https://example.com/form."
    )

    assert "9876543210" not in result.text
    assert "ramesh@example.com" not in result.text
    assert "B-1204" not in result.text
    assert "https://example.com/form" not in result.text
    assert "PHONE_1" in result.text
    assert "EMAIL_1" in result.text
    assert "FLAT_1" in result.text
    assert "URL_1" in result.text
    assert result.counts == {"PHONE": 1, "EMAIL": 1, "URL": 1, "FLAT": 1}


def test_redact_text_numbers_placeholders_per_type() -> None:
    result = redact_text("Call 9876543210 or 98765 43210, flats A-1001 and B-204.")

    assert "PHONE_1" in result.text
    assert "PHONE_2" in result.text
    assert "FLAT_1" in result.text
    assert "FLAT_2" in result.text
    assert result.counts == {"PHONE": 2, "FLAT": 2}


def test_flat_detector_does_not_redact_prices() -> None:
    result = redact_text("He charged Rs 500 and came at 4 pm.")

    assert result.text == "He charged Rs 500 and came at 4 pm."
    assert result.counts == {}


def test_address_detector_finds_tower_and_block_markers() -> None:
    spans = detect_sensitive_spans("Meet near Tower 2 or Block A.")

    assert [span.kind for span in spans] == ["ADDRESS", "ADDRESS"]

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from attachment_helpers import make_docx, make_pdf, make_xlsx

from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.extractors import (
    AttachmentExtractionError,
    extract_blocks,
    extract_blocks_isolated,
)

CONFIG = AttachmentConfig(isolate=False)


def test_pdf_pages_become_labeled_blocks(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "rules.pdf", [["Gym opens at 6am"], ["Pool closed Mondays"]])
    result = extract_blocks("pdf", pdf, CONFIG)
    assert result["page_count"] == 2
    assert [b["label"] for b in result["blocks"]] == ["p.1", "p.2"]
    assert "Gym opens at 6am" in result["blocks"][0]["text"]
    assert "Pool closed Mondays" in result["blocks"][1]["text"]
    assert result["truncated"] is False


def test_pdf_page_cap_marks_truncated(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "big.pdf", [[f"page {i} text"] for i in range(5)])
    result = extract_blocks("pdf", pdf, AttachmentConfig(isolate=False, max_pages=2))
    assert len(result["blocks"]) == 2
    assert result["page_count"] == 5
    assert result["truncated"] is True


def test_corrupt_pdf_reports_safe_category(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks("pdf", bad, CONFIG)
    assert info.value.category == "corrupt_or_unreadable"


def test_docx_splits_on_headings_and_includes_tables(tmp_path: Path) -> None:
    docx = make_docx(
        tmp_path / "guide.docx",
        [
            ("Heading 1", "Parking"),
            ("Normal", "Guest parking needs a permit from the security desk."),
            ("Heading 1", "Vendors"),
            ("Normal", "Approved vendors are listed below."),
        ],
        table=[["Plumber", "Ramesh", "9876543210"], ["Electrician", "Suresh", "9123456780"]],
    )
    result = extract_blocks("docx", docx, CONFIG)
    labels = [b["label"] for b in result["blocks"]]
    assert labels == ["section 1", "section 2"]
    assert "Guest parking needs a permit" in result["blocks"][0]["text"]
    assert "Plumber | Ramesh | 9876543210" in result["blocks"][1]["text"]


def test_xlsx_sheets_and_row_cap(tmp_path: Path) -> None:
    rows = [["Service", "Name", "Rate"]] + [["Plumber", f"P{i}", 100 + i] for i in range(10)]
    xlsx = make_xlsx(tmp_path / "rates.xlsx", {"Rates": rows, "Notes": [["Prices exclude GST"]]})
    result = extract_blocks("xlsx", xlsx, AttachmentConfig(isolate=False, spreadsheet_row_cap=4))
    assert [b["label"] for b in result["blocks"]] == ["sheet:Rates", "sheet:Notes"]
    assert result["blocks"][0]["text"].splitlines()[0] == "Service | Name | Rate"
    assert len(result["blocks"][0]["text"].splitlines()) == 4
    assert result["truncated"] is True


def test_csv_and_txt_decoding(tmp_path: Path) -> None:
    csv_file = tmp_path / "rates.csv"
    csv_file.write_text("Service,Name\nPlumber,Ramesh\n", encoding="utf-8")
    assert extract_blocks("csv", csv_file, CONFIG)["blocks"][0]["text"] == "Service | Name\nPlumber | Ramesh"

    txt = tmp_path / "notes.txt"
    txt.write_bytes("Caf\xe9 opens at 8am".encode("cp1252"))
    assert "Café opens at 8am" in extract_blocks("txt", txt, CONFIG)["blocks"][0]["text"]


def test_text_cap_truncates(tmp_path: Path) -> None:
    txt = tmp_path / "long.txt"
    txt.write_text("word " * 1000, encoding="utf-8")
    result = extract_blocks("txt", txt, AttachmentConfig(isolate=False, max_text_chars=100))
    assert len(result["blocks"][0]["text"]) == 100
    assert result["truncated"] is True


def test_unsupported_kind(tmp_path: Path) -> None:
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks("video", tmp_path / "x.mp4", CONFIG)
    assert info.value.category == "unsupported_kind"


def test_isolated_worker_matches_in_process(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "rules.pdf", [["Gym opens at 6am"]])
    isolated = extract_blocks_isolated("pdf", pdf, AttachmentConfig())
    assert isolated == extract_blocks("pdf", pdf, CONFIG)


def test_isolated_worker_reports_failure_category(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 nope")
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks_isolated("pdf", bad, AttachmentConfig())
    assert info.value.category == "corrupt_or_unreadable"


def test_isolated_worker_timeout(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "rules.pdf", [["hello"]])
    # Child interpreter start-up alone exceeds a near-zero timeout.
    config = replace(AttachmentConfig(), timeout_seconds=0.001)
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks_isolated("pdf", pdf, config)
    assert info.value.category == "timeout"

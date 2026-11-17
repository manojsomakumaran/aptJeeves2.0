from __future__ import annotations

from pathlib import Path

import pytest
from attachment_helpers import make_pdf, make_real_png

from aptjeeves.attachments import ocr
from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.extractors import AttachmentExtractionError, extract_blocks
from aptjeeves.attachments.ocr import OcrLine

LOCAL = AttachmentConfig(isolate=False, ocr_backend="local")


class FakeOcr:
    def __init__(self, lines: list[OcrLine]) -> None:
        self.lines = lines
        self.calls = 0

    def read_image(self, path: Path) -> list[OcrLine]:
        self.calls += 1
        return self.lines

    def read_bytes(self, data: bytes) -> list[OcrLine]:
        self.calls += 1
        return self.lines


@pytest.fixture(autouse=True)
def _reset_backend():
    yield
    ocr.set_backend_override(None)


def _use(lines: list[OcrLine]) -> FakeOcr:
    fake = FakeOcr(lines)
    ocr.set_backend_override(fake)
    return fake


def test_image_text_is_read_with_ocr_method(tmp_path: Path) -> None:
    _use([OcrLine("Society notice: water cut on Sunday 10am", 0.95)])
    result = extract_blocks("image", make_real_png(tmp_path / "a.png"), LOCAL)
    assert result["method"] == "local_ocr"
    assert "water cut" in result["blocks"][0]["text"]


def test_low_confidence_lines_are_dropped() -> None:
    text, mean = ocr.lines_to_text([OcrLine("good line", 0.9), OcrLine("noise", 0.2)], 0.6)
    assert text == "good line" and mean == pytest.approx(0.9)


def test_tiny_image_is_not_ocred(tmp_path: Path) -> None:
    fake = _use([OcrLine("should never be read by the engine", 0.99)])
    result = extract_blocks("image", make_real_png(tmp_path / "s.png", 100, 100), LOCAL)
    assert result["blocks"] == [] and fake.calls == 0


def test_image_with_little_text_yields_nothing(tmp_path: Path) -> None:
    _use([OcrLine("hi", 0.99)])
    result = extract_blocks("image", make_real_png(tmp_path / "meme.png"), LOCAL)
    assert result["blocks"] == []


def test_image_without_backend_reports_ocr_unavailable(tmp_path: Path) -> None:
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks("image", make_real_png(tmp_path / "a.png"), AttachmentConfig(isolate=False))
    assert info.value.category == "ocr_unavailable"


def test_corrupt_image_reports_safe_category(tmp_path: Path) -> None:
    _use([])
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nnot a png")
    with pytest.raises(AttachmentExtractionError) as info:
        extract_blocks("image", bad, LOCAL)
    assert info.value.category == "corrupt_or_unreadable"


def test_scanned_pdf_pages_fall_back_to_ocr(tmp_path: Path) -> None:
    fake = _use([OcrLine("Clubhouse booking rules apply to all residents", 0.9)])
    pdf = make_pdf(tmp_path / "scan.pdf", [[""]])
    result = extract_blocks("pdf", pdf, LOCAL)
    assert result["method"] == "local_ocr"
    assert "Clubhouse booking" in result["blocks"][0]["text"]
    assert fake.calls == 1


def test_text_pdf_pages_skip_ocr(tmp_path: Path) -> None:
    fake = _use([OcrLine("never used", 0.9)])
    pdf = make_pdf(tmp_path / "t.pdf", [["Gym opens at 6am for all residents"]])
    result = extract_blocks("pdf", pdf, LOCAL)
    assert result["method"] == "native_text" and fake.calls == 0


def test_ocr_page_cap_marks_truncated(tmp_path: Path) -> None:
    fake = _use([OcrLine("Scanned page with enough text to count", 0.9)])
    pdf = make_pdf(tmp_path / "scan.pdf", [[""], [""], [""]])
    result = extract_blocks("pdf", pdf, AttachmentConfig(isolate=False, ocr_backend="local", ocr_max_pages=2))
    assert fake.calls == 2 and result["truncated"] is True

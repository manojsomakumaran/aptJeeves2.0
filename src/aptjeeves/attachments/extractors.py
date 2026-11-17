from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from aptjeeves.attachments import ocr
from aptjeeves.attachments.config import AttachmentConfig

EXTRACTOR_VERSION = "attachment_text_v2"
METHOD_NATIVE_TEXT = "native_text"
METHOD_LOCAL_OCR = "local_ocr"

# Failure categories are the only error detail persisted (never exception text,
# which could echo document content).
ERR_DEPENDENCY = "dependency_missing"
ERR_ENCRYPTED = "encrypted"
ERR_CORRUPT = "corrupt_or_unreadable"
ERR_TIMEOUT = "timeout"
ERR_CRASH = "worker_crashed"
ERR_UNSUPPORTED = "unsupported_kind"
ERR_OCR_UNAVAILABLE = "ocr_unavailable"


class AttachmentExtractionError(Exception):
    """Raised with a privacy-safe failure category as the message."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def extract_blocks(kind: str, path: Path, config: AttachmentConfig) -> dict[str, Any]:
    """Extract text blocks from one document in this process.

    Returns ``{"blocks": [{"label", "text"}], "page_count", "truncated"}``.
    Raises AttachmentExtractionError with a safe category.
    """

    handlers = {
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "xlsx": _extract_xlsx,
        "csv": _extract_csv,
        "txt": _extract_txt,
        "image": _extract_image,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise AttachmentExtractionError(ERR_UNSUPPORTED)
    try:
        result = handler(path, config)
    except AttachmentExtractionError:
        raise
    except ocr.OcrUnavailableError as exc:
        raise AttachmentExtractionError(ERR_OCR_UNAVAILABLE) from exc
    except ImportError as exc:
        raise AttachmentExtractionError(ERR_DEPENDENCY) from exc
    except Exception as exc:  # noqa: BLE001 - parsers raise many library-specific types
        name = type(exc).__name__.lower()
        if "password" in name or "encrypt" in name:
            raise AttachmentExtractionError(ERR_ENCRYPTED) from exc
        raise AttachmentExtractionError(ERR_CORRUPT) from exc
    return _apply_text_cap(result, config.max_text_chars)


def extract_blocks_isolated(kind: str, path: Path, config: AttachmentConfig) -> dict[str, Any]:
    """Run extraction in a child process with a timeout."""

    request = json.dumps(
        {
            "kind": kind,
            "path": str(path),
            "max_pages": config.max_pages,
            "max_text_chars": config.max_text_chars,
            "spreadsheet_row_cap": config.spreadsheet_row_cap,
            "ocr_backend": config.ocr_backend,
            "ocr_min_confidence": config.ocr_min_confidence,
            "ocr_max_pages": config.ocr_max_pages,
            "ocr_page_min_chars": config.ocr_page_min_chars,
            "ocr_min_image_side": config.ocr_min_image_side,
            "ocr_min_text_chars": config.ocr_min_text_chars,
        }
    )
    timeout = config.ocr_timeout_seconds if config.ocr_backend != ocr.OCR_NONE else config.timeout_seconds
    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "aptjeeves.attachments.worker"],
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=env,
            cwd=str(path.parent),
        )
    except subprocess.TimeoutExpired as exc:
        raise AttachmentExtractionError(ERR_TIMEOUT) from exc
    if completed.returncode != 0:
        raise AttachmentExtractionError(ERR_CRASH)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AttachmentExtractionError(ERR_CRASH) from exc
    if "error" in payload:
        raise AttachmentExtractionError(str(payload["error"]))
    return payload


def _apply_text_cap(result: dict[str, Any], max_chars: int) -> dict[str, Any]:
    total = 0
    kept: list[dict[str, str]] = []
    truncated = bool(result.get("truncated"))
    for block in result["blocks"]:
        text = block["text"]
        if not text.strip():
            continue
        remaining = max_chars - total
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        kept.append({"label": block["label"], "text": text})
        total += len(text)
    return {
        "blocks": kept,
        "page_count": result.get("page_count"),
        "truncated": truncated,
        "method": result.get("method", METHOD_NATIVE_TEXT),
    }


def _extract_pdf(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    import pdfplumber

    backend = ocr.get_backend(config.ocr_backend)
    blocks: list[dict[str, str]] = []
    ocr_pages = 0
    ocr_capped = False
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for index, page in enumerate(pdf.pages[: config.max_pages], start=1):
            text = page.extract_text() or ""
            if backend is not None and len(text.strip()) < config.ocr_page_min_chars:
                if ocr_pages >= config.ocr_max_pages:
                    ocr_capped = True
                else:
                    ocr_pages += 1
                    text = _ocr_pdf_page(page, backend, config) or text
            blocks.append({"label": f"p.{index}", "text": text})
    return {
        "blocks": blocks,
        "page_count": page_count,
        "truncated": page_count > config.max_pages or ocr_capped,
        "method": METHOD_LOCAL_OCR if ocr_pages else METHOD_NATIVE_TEXT,
    }


def _ocr_pdf_page(page: Any, backend: ocr.OcrBackend, config: AttachmentConfig) -> str:
    buffer = io.BytesIO()
    page.to_image(resolution=200).original.save(buffer, format="PNG")
    text, _confidence = ocr.lines_to_text(
        backend.read_bytes(buffer.getvalue()), config.ocr_min_confidence
    )
    return text


def _extract_image(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    from PIL import Image

    backend = ocr.get_backend(config.ocr_backend)
    if backend is None:
        raise ocr.OcrUnavailableError("ocr disabled")
    with Image.open(path) as image:
        width, height = image.size
    # Icons, stickers and thumbnails: not worth running OCR on.
    if min(width, height) < config.ocr_min_image_side:
        return {"blocks": [], "page_count": None, "truncated": False, "method": METHOD_LOCAL_OCR}
    text, _confidence = ocr.lines_to_text(backend.read_image(path), config.ocr_min_confidence)
    if len(text.strip()) < config.ocr_min_text_chars:
        # Photos, memes and selfies produce little or noisy text; treat as no text.
        text = ""
    return {
        "blocks": [{"label": "image", "text": text}],
        "page_count": None,
        "truncated": False,
        "method": METHOD_LOCAL_OCR,
    }


def _extract_docx(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    sections: list[list[str]] = [[]]
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
            if style_name.lower().startswith(("heading", "title")) and text:
                if sections[-1]:
                    sections.append([])
            if text:
                sections[-1].append(text)
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = cell.text.strip().replace("\n", " ")
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                if cells:
                    sections[-1].append(" | ".join(cells))
    blocks = [
        {"label": f"section {number}", "text": "\n".join(lines)}
        for number, lines in enumerate((s for s in sections if s), start=1)
    ]
    return {"blocks": blocks, "page_count": None, "truncated": False}


def _extract_xlsx(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    blocks: list[dict[str, str]] = []
    truncated = False
    try:
        for sheet in workbook.worksheets:
            lines: list[str] = []
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_number > config.spreadsheet_row_cap:
                    truncated = True
                    break
                values = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if values:
                    lines.append(" | ".join(values))
            blocks.append({"label": f"sheet:{sheet.title}", "text": "\n".join(lines)})
    finally:
        workbook.close()
    return {"blocks": blocks, "page_count": None, "truncated": truncated}


def _extract_csv(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    text = _decode(path.read_bytes())
    lines: list[str] = []
    truncated = False
    for row_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if row_number > config.spreadsheet_row_cap:
            truncated = True
            break
        values = [cell.strip() for cell in row if cell.strip()]
        if values:
            lines.append(" | ".join(values))
    return {
        "blocks": [{"label": "rows", "text": "\n".join(lines)}],
        "page_count": None,
        "truncated": truncated,
    }


def _extract_txt(path: Path, config: AttachmentConfig) -> dict[str, Any]:
    # Read at most a bit more than the cap so a huge file cannot exhaust memory.
    with path.open("rb") as handle:
        data = handle.read(config.max_text_chars * 4 + 1)
    return {
        "blocks": [{"label": "text", "text": _decode(data)}],
        "page_count": None,
        "truncated": False,
    }


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")

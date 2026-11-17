"""Builders for small attachment fixtures (no binary files committed)."""

from __future__ import annotations

from pathlib import Path


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Write a minimal text-layer PDF; each page is a list of text lines."""

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # placeholder, patched below
    pages_obj = add(b"")  # placeholder, patched below
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    for lines in pages:
        ops = ["BT", "/F1 12 Tf", "14 TL", "50 750 Td"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({escaped}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = add(
            f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode()
        )
        page_ids.append(page)
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, paragraphs: list[tuple[str, str]], table: list[list[str]] | None = None) -> Path:
    """Write a DOCX. ``paragraphs`` are (style, text) pairs, e.g. ("Heading 1", "Rules")."""

    from docx import Document

    document = Document()
    for style, text in paragraphs:
        if style.startswith("Heading"):
            document.add_heading(text, level=int(style.split()[-1]))
        else:
            document.add_paragraph(text)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    document.save(str(path))
    return path


def make_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.save(str(path))
    return path


def make_png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return path


def make_real_png(path: Path, width: int = 400, height: int = 300) -> Path:
    """Write a decodable PNG (needed when the code opens it with Pillow)."""

    from PIL import Image

    Image.new("RGB", (width, height), "white").save(path, format="PNG")
    return path

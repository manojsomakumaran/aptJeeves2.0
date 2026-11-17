from __future__ import annotations

import zipfile
from pathlib import Path

DOC_KINDS = frozenset({"pdf", "docx", "xlsx", "csv", "txt"})
_TEXT_SUFFIXES = {".txt": "txt", ".md": "txt", ".csv": "csv"}


def sniff_kind(path: Path) -> str:
    """Return the real file kind from magic bytes, ignoring the extension.

    One of: pdf, docx, xlsx, csv, txt, image, vcard, other. Plain-text kinds
    still need a text-like extension so arbitrary binaries are never decoded.
    """

    try:
        with path.open("rb") as handle:
            head = handle.read(4096)
    except OSError:
        return "other"

    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip(path)
    if (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith((b"GIF87a", b"GIF89a"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    ):
        return "image"
    if head.lstrip().upper().startswith(b"BEGIN:VCARD"):
        return "vcard"

    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES and b"\x00" not in head and _looks_like_text(head):
        return _TEXT_SUFFIXES[suffix]
    return "other"


def _sniff_zip(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return "other"
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return "other"


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    try:
        head.decode("utf-8-sig")
        return True
    except UnicodeDecodeError:
        pass
    try:
        # The 4 KiB head may cut a multibyte character; tolerate a short tail.
        head[:-3].decode("utf-8-sig")
        return True
    except UnicodeDecodeError:
        pass
    printable = sum(1 for b in head if b in (9, 10, 13) or 32 <= b < 127 or b >= 160)
    return printable / len(head) > 0.95

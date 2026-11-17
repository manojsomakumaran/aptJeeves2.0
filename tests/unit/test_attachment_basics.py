from __future__ import annotations

from pathlib import Path

import pytest

from aptjeeves.attachments.chunking import split_text
from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.discovery import find_attachment_filenames, resolve_attachment_path
from aptjeeves.attachments.sniff import sniff_kind


# ------------------------------------------------------------------ discovery

def test_finds_android_file_attached_line() -> None:
    text = "Society Rules.pdf (file attached)\nPlease read before booking."
    assert find_attachment_filenames(text) == ["Society Rules.pdf"]


def test_finds_ios_attached_marker() -> None:
    assert find_attachment_filenames("<attached: 00000012-DOC-Rate Card.xlsx>") == ["00000012-DOC-Rate Card.xlsx"]


def test_strips_direction_marks_and_dedupes() -> None:
    text = "‎Rules.pdf (file attached)\n‎Rules.pdf (file attached)"
    assert find_attachment_filenames(text) == ["Rules.pdf"]


def test_bare_filename_message() -> None:
    assert find_attachment_filenames("rates.csv") == ["rates.csv"]


def test_plain_chat_and_vcards_are_not_attachments() -> None:
    assert find_attachment_filenames("Call the plumber at PHONE_1") == []
    assert find_attachment_filenames("Jaya Akka.vcf (file attached)") == []
    assert find_attachment_filenames("see you at rules.pdf tomorrow maybe") == []


def test_resolve_is_case_and_unicode_tolerant_and_stays_in_folder(tmp_path: Path) -> None:
    (tmp_path / "Rules.PDF").write_bytes(b"x")
    assert resolve_attachment_path(tmp_path, "rules.pdf").name.casefold() == "rules.pdf"
    # A hostile name cannot escape the folder.
    outside = tmp_path.parent / "secret.pdf"
    outside.write_bytes(b"x")
    resolved = resolve_attachment_path(tmp_path, "../secret.pdf")
    assert resolved.parent == tmp_path
    assert not resolved.is_file()


def test_resolve_ios_prefixed_file(tmp_path: Path) -> None:
    (tmp_path / "00000012-DOC-Rules.pdf").write_bytes(b"x")
    assert resolve_attachment_path(tmp_path, "Rules.pdf").name == "00000012-DOC-Rules.pdf"


# ---------------------------------------------------------------------- sniff

def test_sniff_uses_magic_bytes_not_extension(tmp_path: Path) -> None:
    from attachment_helpers import make_docx, make_pdf, make_png, make_xlsx

    pdf = make_pdf(tmp_path / "looks_like.txt", [["hello world"]])
    assert sniff_kind(pdf) == "pdf"
    assert sniff_kind(make_docx(tmp_path / "a.docx", [("Normal", "hi")])) == "docx"
    assert sniff_kind(make_xlsx(tmp_path / "a.xlsx", {"S": [["a", 1]]})) == "xlsx"
    assert sniff_kind(make_png(tmp_path / "pic.dat")) == "image"


def test_sniff_text_requires_text_extension_and_rejects_binary(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello there", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "blob.txt").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "blob.bin").write_bytes(b"plain ascii but odd extension")
    (tmp_path / "fake.docx").write_bytes(b"not a zip at all")
    assert sniff_kind(tmp_path / "notes.txt") == "txt"
    assert sniff_kind(tmp_path / "data.csv") == "csv"
    assert sniff_kind(tmp_path / "blob.txt") == "other"
    assert sniff_kind(tmp_path / "blob.bin") == "other"
    assert sniff_kind(tmp_path / "fake.docx") == "other"
    assert sniff_kind(tmp_path / "missing.pdf") == "other"


def test_sniff_vcard(tmp_path: Path) -> None:
    (tmp_path / "c.vcf").write_text("BEGIN:VCARD\nFN:A\nEND:VCARD\n", encoding="utf-8")
    assert sniff_kind(tmp_path / "c.vcf") == "vcard"


# ------------------------------------------------------------------- chunking

def test_short_text_is_one_chunk() -> None:
    assert split_text("hello\nworld", 100) == ["hello\nworld"]
    assert split_text("   ", 100) == []


def test_chunks_respect_limit_and_cover_all_lines() -> None:
    lines = [f"line {i:03d} " + "x" * 20 for i in range(60)]
    chunks = split_text("\n".join(lines), 300, overlap=0)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "\n".join(chunks).split("\n") == lines


def test_overlap_repeats_trailing_lines() -> None:
    lines = [f"row {i:02d}" for i in range(40)]
    chunks = split_text("\n".join(lines), 60, overlap=20)
    assert len(chunks) > 2
    assert all(len(chunk) <= 60 for chunk in chunks)
    for previous, current in zip(chunks, chunks[1:]):
        assert previous.split("\n")[-1] in current.split("\n")[:3]


def test_overlong_line_is_hard_split() -> None:
    chunks = split_text("a" * 250, 100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_invalid_limit_raises() -> None:
    with pytest.raises(ValueError):
        split_text("x", 0)


# --------------------------------------------------------------------- config

def test_config_from_env_validates_values(monkeypatch) -> None:
    monkeypatch.setenv("APTJEEVES_ATTACHMENT_RETENTION", "DELETE_AFTER_EXTRACT")
    monkeypatch.setenv("APTJEEVES_ATTACHMENT_MAX_PAGES", "12")
    monkeypatch.setenv("APTJEEVES_ATTACHMENT_TIMEOUT_SECONDS", "banana")
    config = AttachmentConfig.from_env()
    assert config.retention == "delete_after_extract"
    assert config.max_pages == 12
    assert config.timeout_seconds == AttachmentConfig().timeout_seconds

    monkeypatch.setenv("APTJEEVES_ATTACHMENT_RETENTION", "shred")
    assert AttachmentConfig.from_env().retention == "keep"

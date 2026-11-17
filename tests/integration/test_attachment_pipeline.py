from __future__ import annotations

import json
from pathlib import Path

from attachment_helpers import make_docx, make_pdf, make_png, make_xlsx

from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.repository import AttachmentRepository
from aptjeeves.attachments.service import AttachmentService
from aptjeeves.cli import main
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import CanonicalFactRepository, RawMessageRepository

NO_ISOLATION = AttachmentConfig(isolate=False)


def _setup(tmp_path: Path, chat_lines: list[str], config: AttachmentConfig = NO_ISOLATION):
    db_path = tmp_path / "apt" / "aptjeeves.sqlite3"
    connection = connect(db_path)
    apply_migrations(connection)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    export = tmp_path / "chat.txt"
    export.write_text("\n".join(chat_lines), encoding="utf-8")
    return connection, uploads, export, config


def _ingest(connection, export: Path, uploads: Path, config: AttachmentConfig = NO_ISOLATION):
    return ChatIngestionService(connection, attachment_config=config).ingest(
        IngestRequest(platform="whatsapp", file_path=export, chat_name="Main", upload_dir=uploads)
    )


# One page with two lines of text.
RATE_CARD_LINES = [
    [
        "Vendor rate card (resident recommended)",
        "Plumber Ramesh 9876543210 - plumber Rs 400 per visit",
    ]
]


def test_pdf_attachment_flows_to_facts_with_document_evidence(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path, ["16/04/26, 9:30 PM - Alice: Vendor Rates.pdf (file attached)"]
    )
    make_pdf(uploads / "Vendor Rates.pdf", RATE_CARD_LINES)

    summary = _ingest(connection, export, uploads)
    assert summary.new_messages_inserted == 1

    attachments = AttachmentRepository(connection)
    assert attachments.count_by_status()["pending"] == 1
    row = attachments.list_by_status("pending")[0]
    assert Path(row["spool_path"]).is_file()  # originals are kept by default
    assert Path(row["spool_path"]).parent == tmp_path / "apt" / "attachments"
    assert "Vendor" not in Path(row["spool_path"]).name  # content-addressed, name-free

    result = AttachmentService(connection, config=config).process_pending()
    assert (result.text_extracted, result.failed, result.segments_inserted) == (1, 0, 1)
    assert attachments.count_by_status()["text_extracted"] == 1

    segments = [r for r in RawMessageRepository(connection).list_all() if r["source_kind"] == "attachment"]
    assert len(segments) == 1
    segment = segments[0]
    assert segment["segment_label"] == "p.1"
    assert segment["source_file"] == "attachment:Vendor Rates.pdf"
    assert segment["processing_status"] == "new"
    assert segment["parent_message_id"] is not None
    assert "9876543210" not in segment["sanitized_text"]  # redacted before storage
    assert "PHONE_1" in segment["sanitized_text"]

    extraction = ExtractionService(connection, FakeExtractor()).extract_pending()
    assert extraction.extraction_failures == 0
    facts = CanonicalFactRepository(connection)
    fact = facts.get_fact(extraction.fact_ids[0])
    assert fact["fact_type"] == "service_contact"
    evidence = facts.list_evidence(extraction.fact_ids[0])
    assert evidence[0]["message_id"] == segment["message_id"]


def test_same_file_forwarded_many_times_is_one_attachment(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Rates.pdf (file attached)",
            "17/04/26, 9:30 PM - Bob: Rates.pdf (file attached)",
            "18/04/26, 9:30 PM - Carol: Rates.pdf (file attached)",
        ],
    )
    make_pdf(uploads / "Rates.pdf", RATE_CARD_LINES)
    _ingest(connection, export, uploads)

    assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM attachment_links").fetchone()[0] == 3
    AttachmentService(connection, config=config).process_pending()
    segment = [r for r in RawMessageRepository(connection).list_all() if r["source_kind"] == "attachment"]
    assert len(segment) == 1
    # Segments inherit the earliest linked parent's timestamp.
    assert segment[0]["sent_at_utc"].startswith("2026-04-16")


def test_full_reimport_is_idempotent(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path, ["16/04/26, 9:30 PM - Alice: Rates.pdf (file attached)"]
    )
    make_pdf(uploads / "Rates.pdf", RATE_CARD_LINES)
    _ingest(connection, export, uploads)
    AttachmentService(connection, config=config).process_pending()
    before = RawMessageRepository(connection).count()

    second = _ingest(connection, export, uploads)
    assert second.new_messages_inserted == 0
    AttachmentService(connection, config=config).process_pending()

    assert RawMessageRepository(connection).count() == before
    assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM attachment_links").fetchone()[0] == 1


def test_reimport_with_files_present_backfills_previously_missing_attachment(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path, ["16/04/26, 9:30 PM - Alice: Rates.pdf (file attached)"]
    )
    _ingest(connection, export, uploads)  # file not there yet
    assert connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0

    make_pdf(uploads / "Rates.pdf", RATE_CARD_LINES)
    _ingest(connection, export, uploads)  # duplicate message, file now present
    assert AttachmentRepository(connection).count_by_status()["pending"] == 1


def test_sensitive_documents_are_skipped_and_leave_no_text(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Bill.pdf (file attached)",
            "16/04/26, 9:31 PM - Alice: Lease.docx (file attached)",
        ],
    )
    make_pdf(uploads / "Bill.pdf", [["Electricity bill", "Consumer No: 4455", "Amount due: 1250 rupees"]])
    make_docx(uploads / "Lease.docx", [("Heading 1", "RENT AGREEMENT"), ("Normal", "Between lessor and lessee.")])
    _ingest(connection, export, uploads)

    result = AttachmentService(connection, config=config).process_pending()
    assert result.skipped_sensitive == 2 and result.segments_inserted == 0
    reasons = {r["status_reason"] for r in connection.execute("SELECT status_reason FROM attachments")}
    assert reasons == {"bill_or_invoice", "lease_or_rental_agreement"}
    assert [r for r in RawMessageRepository(connection).list_all() if r["source_kind"] == "attachment"] == []
    stored = json.dumps([dict(r) for r in connection.execute("SELECT * FROM pipeline_events")])
    assert "4455" not in stored and "Consumer" not in stored


def test_image_is_spooled_but_skipped_until_ocr_exists(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path, ["16/04/26, 9:30 PM - Alice: IMG-0001.png (file attached)"]
    )
    make_png(uploads / "IMG-0001.png")
    _ingest(connection, export, uploads)

    row = connection.execute("SELECT * FROM attachments").fetchone()
    assert row["status"] == "skipped_unsupported"
    assert row["status_reason"] == "image_ocr_not_enabled"
    assert Path(row["spool_path"]).is_file()  # kept for the OCR phase


def test_missing_and_oversize_files(tmp_path: Path) -> None:
    config = AttachmentConfig(isolate=False, max_bytes=100)
    connection, uploads, export, _ = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Ghost.pdf (file attached)",
            "16/04/26, 9:31 PM - Alice: Huge.txt (file attached)",
        ],
        config,
    )
    (uploads / "Huge.txt").write_text("x" * 500, encoding="utf-8")
    _ingest(connection, export, uploads, config)

    rows = connection.execute("SELECT status, status_reason, spool_path FROM attachments").fetchall()
    assert [(r["status"], r["status_reason"], r["spool_path"]) for r in rows] == [
        ("skipped_too_large", "file_too_large", None)
    ]
    events = [r["event_type"] for r in connection.execute("SELECT event_type FROM pipeline_events")]
    assert "attachment_skipped" in events  # the missing file


def test_scanned_pdf_without_text_is_no_text_and_corrupt_is_failed_then_retried(tmp_path: Path) -> None:
    connection, uploads, export, config = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Empty.pdf (file attached)",
            "16/04/26, 9:31 PM - Alice: Broken.pdf (file attached)",
        ],
    )
    make_pdf(uploads / "Empty.pdf", [[]])
    (uploads / "Broken.pdf").write_bytes(b"%PDF-1.4 definitely not valid")
    _ingest(connection, export, uploads)

    service = AttachmentService(connection, config=config)
    result = service.process_pending()
    assert (result.no_text, result.failed) == (1, 1)
    counts = AttachmentRepository(connection).count_by_status()
    assert counts["no_text"] == 1 and counts["failed"] == 1

    # reset-failed puts it back in the queue; it is attempted again.
    with connection:
        assert AttachmentRepository(connection).reset_failed() == 1
    assert service.process_pending().failed == 1


def test_delete_after_extract_removes_spool_for_terminal_statuses_only(tmp_path: Path) -> None:
    config = AttachmentConfig(isolate=False, retention="delete_after_extract")
    connection, uploads, export, _ = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Rates.pdf (file attached)",
            "16/04/26, 9:31 PM - Alice: Scan.pdf (file attached)",
            "16/04/26, 9:32 PM - Alice: IMG-1.png (file attached)",
        ],
        config,
    )
    make_pdf(uploads / "Rates.pdf", RATE_CARD_LINES)
    make_pdf(uploads / "Scan.pdf", [[]])
    make_png(uploads / "IMG-1.png")
    _ingest(connection, export, uploads, config)
    AttachmentService(connection, config=config).process_pending()

    by_status = {
        r["status"]: r["spool_path"]
        for r in connection.execute("SELECT status, spool_path FROM attachments")
    }
    assert by_status["text_extracted"] is None  # deleted
    assert by_status["no_text"] is not None and Path(by_status["no_text"]).is_file()  # future OCR candidate
    assert by_status["skipped_unsupported"] is not None  # image kept for OCR


def test_xlsx_and_docx_are_extracted_end_to_end_via_isolated_worker(tmp_path: Path) -> None:
    config = AttachmentConfig()  # real subprocess isolation
    connection, uploads, export, _ = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: Rates.xlsx (file attached)",
            "16/04/26, 9:31 PM - Alice: Rules.docx (file attached)",
        ],
        config,
    )
    make_xlsx(uploads / "Rates.xlsx", {"Vendors": [["Service", "Phone"], ["Plumber", "9876543210"]]})
    make_docx(uploads / "Rules.docx", [("Heading 1", "Gym"), ("Normal", "The gym opens at 6am and closes at 10pm daily.")])
    _ingest(connection, export, uploads, config)

    result = AttachmentService(connection, config=config).process_pending()
    assert (result.text_extracted, result.failed) == (2, 0)
    labels = sorted(
        r["segment_label"] for r in RawMessageRepository(connection).list_all() if r["source_kind"] == "attachment"
    )
    assert labels == ["section 1", "sheet:Vendors"]


def test_long_document_is_chunked_into_multiple_segments(tmp_path: Path) -> None:
    config = AttachmentConfig(isolate=False, segment_chars=300, segment_overlap=0)
    connection, uploads, export, _ = _setup(
        tmp_path, ["16/04/26, 9:30 PM - Alice: Guide.txt (file attached)"], config
    )
    (uploads / "Guide.txt").write_text(
        "\n".join(f"Rule number {i}: keep the corridor clear of bicycles." for i in range(30)),
        encoding="utf-8",
    )
    _ingest(connection, export, uploads, config)
    result = AttachmentService(connection, config=config).process_pending()
    assert result.segments_inserted > 2
    labels = [
        r["segment_label"]
        for r in RawMessageRepository(connection).list_all()
        if r["source_kind"] == "attachment"
    ]
    assert labels[0] == "text (part 1)" and labels[1] == "text (part 2)"


def test_cli_process_attachments_and_reset_failed(tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.sqlite3"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    make_pdf(uploads / "Rates.pdf", RATE_CARD_LINES)
    (uploads / "Broken.pdf").write_bytes(b"%PDF-1.4 broken")
    export = tmp_path / "WhatsApp Chat with Main.txt"
    export.write_text(
        "16/04/26, 9:30 PM - Alice: Rates.pdf (file attached)\n"
        "16/04/26, 9:31 PM - Alice: Broken.pdf (file attached)",
        encoding="utf-8",
    )
    assert main(["--db", str(db), "ingest", "--platform", "whatsapp", "--file", str(export),
                 "--upload-dir", str(uploads)]) == 0
    capsys.readouterr()

    assert main(["--db", str(db), "process-attachments"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["text_extracted"] == 1 and out["failed"] == 1
    assert out["attachment_status_counts"]["failed"] == 1

    assert main(["--db", str(db), "reset-failed"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["attachments_reset"] == 1


def _ocr_config() -> AttachmentConfig:
    return AttachmentConfig(isolate=False, ocr_backend="local")


def test_image_ocr_creates_segments(tmp_path: Path) -> None:
    from attachment_helpers import make_real_png

    from aptjeeves.attachments import ocr

    ocr.set_backend_override(_FakeOcr("Pest control scheduled Saturday for all blocks"))
    try:
        config = _ocr_config()
        connection, uploads, export, _ = _setup(
            tmp_path, ["16/04/26, 9:30 PM - Alice: notice.png (file attached)"], config
        )
        make_real_png(uploads / "notice.png")
        _ingest(connection, export, uploads, config)
        assert connection.execute("SELECT status FROM attachments").fetchone()["status"] == "pending"

        result = AttachmentService(connection, config=config).process_pending()
        assert result.text_extracted == 1 and result.segments_inserted == 1
        row = connection.execute("SELECT * FROM attachments").fetchone()
        assert row["extraction_method"] == "local_ocr"
        segment = [m for m in RawMessageRepository(connection).list_all() if m["source_kind"] == "attachment"]
        assert "Pest control" in segment[0]["sanitized_text"]
    finally:
        ocr.set_backend_override(None)


def test_enabling_ocr_requeues_parked_images_and_scans(tmp_path: Path) -> None:
    from attachment_helpers import make_real_png

    from aptjeeves.attachments import ocr

    connection, uploads, export, _ = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: notice.png (file attached)",
            "16/04/26, 9:31 PM - Alice: scan.pdf (file attached)",
        ],
    )
    make_real_png(uploads / "notice.png")
    make_pdf(uploads / "scan.pdf", [[""]])
    _ingest(connection, export, uploads)
    AttachmentService(connection, config=NO_ISOLATION).process_pending()
    statuses = {r["mime_sniffed"]: r["status"] for r in connection.execute("SELECT * FROM attachments")}
    assert statuses == {"image": "skipped_unsupported", "pdf": "no_text"}

    ocr.set_backend_override(_FakeOcr("Water tanker timings posted by the association"))
    try:
        result = AttachmentService(connection, config=_ocr_config()).process_pending()
    finally:
        ocr.set_backend_override(None)
    assert result.processed == 2 and result.text_extracted == 2


def test_image_without_text_becomes_no_text_and_spool_is_cleaned(tmp_path: Path) -> None:
    from dataclasses import replace

    from attachment_helpers import make_real_png

    from aptjeeves.attachments import ocr

    ocr.set_backend_override(_FakeOcr(""))
    try:
        config = replace(_ocr_config(), retention="delete_after_extract")
        connection, uploads, export, _ = _setup(
            tmp_path, ["16/04/26, 9:30 PM - Alice: selfie.png (file attached)"], config
        )
        make_real_png(uploads / "selfie.png")
        _ingest(connection, export, uploads, config)
        AttachmentService(connection, config=config).process_pending()
        row = connection.execute("SELECT * FROM attachments").fetchone()
        assert row["status"] == "no_text" and row["status_reason"] == "no_text_after_ocr"
        assert row["spool_path"] is None
    finally:
        ocr.set_backend_override(None)


class _FakeOcr:
    def __init__(self, text: str) -> None:
        from aptjeeves.attachments.ocr import OcrLine

        self._lines = [OcrLine(text, 0.95)] if text else []

    def read_image(self, path: Path):
        return self._lines

    def read_bytes(self, data: bytes):
        return self._lines


def test_ocr_counts_reflect_parked_and_ocr_read_files(tmp_path: Path) -> None:
    from attachment_helpers import make_real_png

    from aptjeeves.attachments import ocr

    connection, uploads, export, _ = _setup(
        tmp_path,
        [
            "16/04/26, 9:30 PM - Alice: notice.png (file attached)",
            "16/04/26, 9:31 PM - Alice: scan.pdf (file attached)",
        ],
    )
    make_real_png(uploads / "notice.png")
    make_pdf(uploads / "scan.pdf", [[""]])
    _ingest(connection, export, uploads)
    AttachmentService(connection, config=NO_ISOLATION).process_pending()
    repo = AttachmentRepository(connection)
    assert repo.ocr_counts()["awaiting_ocr"] == 2

    ocr.set_backend_override(_FakeOcr("Water tanker timings posted by the association"))
    try:
        AttachmentService(connection, config=_ocr_config()).process_pending()
    finally:
        ocr.set_backend_override(None)
    counts = repo.ocr_counts()
    assert counts["text_extracted"] == 2 and counts["awaiting_ocr"] == 0

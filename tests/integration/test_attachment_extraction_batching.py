from __future__ import annotations

from pathlib import Path
from typing import Any

from attachment_helpers import make_pdf

from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.service import AttachmentService
from aptjeeves.extraction.schemas import MessageForExtraction
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.ingestion.service import ChatIngestionService, IngestRequest
from aptjeeves.storage.db import apply_migrations, connect
from aptjeeves.storage.repositories import RawMessageRepository


class RecordingExtractor:
    """Extractor that records each call's batch and returns no facts."""

    prompt_version = "recording_v1"
    model_version = "recording_v1"

    def __init__(self) -> None:
        self.batches: list[list[MessageForExtraction]] = []

    def extract(self, messages: list[MessageForExtraction]) -> dict[str, Any]:
        self.batches.append(list(messages))
        return {"facts": [], "warnings": []}


def test_chat_and_document_segments_are_never_mixed_and_carry_origin(tmp_path: Path) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    apply_migrations(connection)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    make_pdf(
        uploads / "Rules.pdf",
        [[f"Rule {i}: residents must keep the corridor clear of bicycles." for i in range(6)]],
    )
    export = tmp_path / "chat.txt"
    export.write_text(
        "16/04/26, 9:30 PM - Alice: Rules.pdf (file attached)\n"
        "16/04/26, 9:31 PM - Bob: Is the swimming pool open on Sundays this month?\n"
        "16/04/26, 9:32 PM - Bob: ok",
        encoding="utf-8",
    )
    config = AttachmentConfig(isolate=False, segment_chars=120, segment_overlap=0)
    ChatIngestionService(connection, attachment_config=config).ingest(
        IngestRequest(platform="whatsapp", file_path=export, chat_name="Main", upload_dir=uploads)
    )
    AttachmentService(connection, config=config).process_pending()

    extractor = RecordingExtractor()
    ExtractionService(connection, extractor).extract_pending(limit=100)

    assert extractor.batches, "expected extractor calls"
    for batch in extractor.batches:
        assert len({m.source_kind for m in batch}) == 1, "chat and document items must not share a call"

    documents = [m for batch in extractor.batches for m in batch if m.source_kind == "attachment"]
    assert len(documents) > 1
    assert {m.attachment_name for m in documents} == {"Rules.pdf"}
    assert all(m.segment_label and m.segment_label.startswith("p.1") for m in documents)

    chat = [m for batch in extractor.batches for m in batch if m.source_kind == "chat"]
    assert all(m.attachment_name is None and m.segment_label is None for m in chat)

    statuses = {r["message_id"]: r["processing_status"] for r in RawMessageRepository(connection).list_all()}
    assert "new" not in statuses.values()  # every row reached a terminal status


def test_document_text_starting_with_yes_or_no_is_not_dropped_as_chat_noise(tmp_path: Path) -> None:
    connection = connect(tmp_path / "db.sqlite3")
    apply_migrations(connection)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "Rules.txt").write_text(
        "No smoking is permitted inside the clubhouse or on the terrace at any time.",
        encoding="utf-8",
    )
    export = tmp_path / "chat.txt"
    export.write_text("16/04/26, 9:30 PM - Alice: Rules.txt (file attached)", encoding="utf-8")
    config = AttachmentConfig(isolate=False)
    ChatIngestionService(connection, attachment_config=config).ingest(
        IngestRequest(platform="whatsapp", file_path=export, chat_name="Main", upload_dir=uploads)
    )
    AttachmentService(connection, config=config).process_pending()

    extractor = RecordingExtractor()
    ExtractionService(connection, extractor).extract_pending()
    documents = [m for batch in extractor.batches for m in batch if m.source_kind == "attachment"]
    assert len(documents) == 1
    assert documents[0].sanitized_text.startswith("No smoking")

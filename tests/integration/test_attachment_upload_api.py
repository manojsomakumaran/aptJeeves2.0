from __future__ import annotations

from pathlib import Path

import pytest
from attachment_helpers import make_pdf
from fastapi.testclient import TestClient

from aptjeeves.api.server import app, get_settings
from aptjeeves.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "unused.sqlite3",
        data_dir=tmp_path / "data",
        embedding_model="local",
        extraction_backend="fake",
        llm_provider="disabled",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app), settings
    app.dependency_overrides.pop(get_settings, None)


def test_upload_registers_attachments_and_runs_pipeline_after_temp_dir_is_gone(client, tmp_path: Path) -> None:
    http, settings = client
    pdf = make_pdf(
        tmp_path / "Vendor Rates.pdf",
        [["Vendor rate card", "Plumber Ramesh 9876543210 plumber Rs 400 per visit"]],
    )
    chat = tmp_path / "WhatsApp Chat with Main.txt"
    chat.write_text("16/04/26, 9:30 PM - Alice: Vendor Rates.pdf (file attached)", encoding="utf-8")

    with chat.open("rb") as chat_file, pdf.open("rb") as pdf_file:
        response = http.post(
            "/api/att-apt/upload",
            data={"platform": "whatsapp", "primary_filename": chat.name},
            files=[
                ("files", (chat.name, chat_file, "text/plain")),
                ("files", (pdf.name, pdf_file, "application/pdf")),
            ],
        )
    assert response.status_code == 200, response.text

    # The upload's temp dir is deleted when the request returns; the attachment
    # must already be spooled so the background stage could still read it.
    spool = settings.data_dir / "apartments" / "att-apt" / "attachments"
    assert len(list(spool.glob("*.pdf"))) == 1

    status = http.get("/api/att-apt/status").json()
    assert status["attachments"]["text_extracted"] == 1
    assert status["attachments"]["pending"] == 0
    assert status["facts"]["total"] == 1  # the fake extractor found the plumber


def test_status_includes_attachment_counts_for_a_fresh_apartment(client) -> None:
    http, _ = client
    status = http.get("/api/fresh-apt/status").json()
    assert status["attachments"]["pending"] == 0
    assert set(status["attachments"]) >= {"pending", "text_extracted", "failed", "skipped_sensitive"}


def test_reset_failed_also_resets_attachments(client, tmp_path: Path) -> None:
    http, settings = client
    broken = tmp_path / "Broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not valid")
    chat = tmp_path / "chat.txt"
    chat.write_text("16/04/26, 9:30 PM - Alice: Broken.pdf (file attached)", encoding="utf-8")
    with chat.open("rb") as chat_file, broken.open("rb") as broken_file:
        http.post(
            "/api/fail-apt/upload",
            data={"platform": "whatsapp", "primary_filename": chat.name},
            files=[("files", (chat.name, chat_file, "text/plain")), ("files", (broken.name, broken_file, "application/pdf"))],
        )
    assert http.get("/api/fail-apt/status").json()["attachments"]["failed"] == 1

    reset = http.post("/api/fail-apt/reset-failed").json()
    assert reset["details"]["attachments_reset"] == 1
    assert http.get("/api/fail-apt/status").json()["attachments"]["pending"] == 1

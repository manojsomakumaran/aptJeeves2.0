from __future__ import annotations

from pathlib import Path

from aptjeeves.cli import infer_chat_name_from_file


def test_infer_chat_name_from_whatsapp_filename() -> None:
    assert (
        infer_chat_name_from_file(Path("WhatsApp Chat with Apartment Main.txt"))
        == "Apartment Main"
    )


def test_infer_chat_name_from_plain_filename() -> None:
    assert infer_chat_name_from_file(Path("tower-a-vendors.txt")) == "tower a vendors"

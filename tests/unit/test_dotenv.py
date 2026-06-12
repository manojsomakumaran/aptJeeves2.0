from __future__ import annotations

import os
from pathlib import Path

from aptjeeves.config import load_dotenv


def test_load_dotenv_sets_missing_vars(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_VAR=hello_world\n", encoding="utf-8")
    os.environ.pop("TEST_DOTENV_VAR", None)

    load_dotenv(env_file)

    assert os.environ.get("TEST_DOTENV_VAR") == "hello_world"
    os.environ.pop("TEST_DOTENV_VAR", None)


def test_load_dotenv_does_not_overwrite_existing_vars(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_KEEP=new_value\n", encoding="utf-8")
    os.environ["TEST_DOTENV_KEEP"] = "original"

    load_dotenv(env_file)

    assert os.environ["TEST_DOTENV_KEEP"] == "original"
    os.environ.pop("TEST_DOTENV_KEEP", None)


def test_load_dotenv_skips_comments_and_blanks(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nTEST_DOTENV_GOOD=yes\n", encoding="utf-8")
    os.environ.pop("TEST_DOTENV_GOOD", None)

    load_dotenv(env_file)

    assert os.environ.get("TEST_DOTENV_GOOD") == "yes"
    os.environ.pop("TEST_DOTENV_GOOD", None)


def test_load_dotenv_strips_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('TEST_DOTENV_QUOTED="some value"\n', encoding="utf-8")
    os.environ.pop("TEST_DOTENV_QUOTED", None)

    load_dotenv(env_file)

    assert os.environ.get("TEST_DOTENV_QUOTED") == "some value"
    os.environ.pop("TEST_DOTENV_QUOTED", None)


def test_load_dotenv_no_file_is_noop(tmp_path: Path) -> None:
    load_dotenv(tmp_path / "nonexistent.env")

from __future__ import annotations

from pathlib import Path

import pytest

from aptjeeves.config import Settings, apartment_db_path, resolve_db_path, slugify_apartment


def test_slugify_apartment_creates_filesystem_safe_name() -> None:
    assert slugify_apartment("Prestige Lake View - Tower A") == "prestige-lake-view-tower-a"


def test_slugify_apartment_rejects_empty_slug() -> None:
    with pytest.raises(ValueError):
        slugify_apartment("   !!!   ")


def test_apartment_db_path_uses_isolated_data_directory() -> None:
    settings = Settings(db_path=Path("fallback.sqlite3"), data_dir=Path("data"))

    assert apartment_db_path(settings, "Green Acres") == Path(
        "data/apartments/green-acres/aptjeeves.sqlite3"
    )


def test_resolve_db_path_prefers_explicit_db_over_apartment() -> None:
    settings = Settings(db_path=Path("fallback.sqlite3"), data_dir=Path("data"))

    assert (
        resolve_db_path(
            settings=settings,
            explicit_db_path=Path("manual.sqlite3"),
            apartment="Green Acres",
        )
        == Path("manual.sqlite3")
    )

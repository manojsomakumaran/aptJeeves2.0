from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    db_path: Path
    data_dir: Path
    default_timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Load AptJeeves settings with local-friendly defaults."""

    db_path = Path(os.environ.get("APTJEEVES_DB_PATH", "aptjeeves.sqlite3"))
    data_dir = Path(os.environ.get("APTJEEVES_DATA_DIR", "data"))
    default_timezone = os.environ.get("APTJEEVES_DEFAULT_TIMEZONE", "Asia/Kolkata")
    log_level = os.environ.get("APTJEEVES_LOG_LEVEL", "INFO")
    return Settings(
        db_path=db_path,
        data_dir=data_dir,
        default_timezone=default_timezone,
        log_level=log_level,
    )


def apartment_db_path(settings: Settings, apartment: str) -> Path:
    """Return the isolated SQLite DB path for one apartment chatbot."""

    return settings.data_dir / "apartments" / slugify_apartment(apartment) / "aptjeeves.sqlite3"


def resolve_db_path(
    *,
    settings: Settings,
    explicit_db_path: Path | None,
    apartment: str | None,
) -> Path:
    """Choose the DB path using explicit override, apartment, then default DB.

    `--db` is the escape hatch for tests or one-off local runs. In normal
    multi-apartment operation, `--apartment` selects an isolated database.
    """

    if explicit_db_path is not None:
        return explicit_db_path
    if apartment:
        return apartment_db_path(settings, apartment)
    return settings.db_path


def slugify_apartment(value: str) -> str:
    """Convert an apartment display name into a stable filesystem-safe slug."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("Apartment name must contain at least one letter or number")
    return slug

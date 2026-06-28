from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from langfuse import Langfuse


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    db_path: Path
    data_dir: Path
    default_timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    extraction_backend: str = "fake"
    extraction_model: str = "gpt-4.1-mini"
    intent_backend: str = "keyword"
    intent_model: str = "gpt-4.1-mini"
    langfuse_host: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None


_langfuse_client = None


def get_langfuse_client() -> Langfuse | None:
    """Return a singleton Langfuse client, initializing it if needed."""
    global _langfuse_client
    if _langfuse_client is None:
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            _langfuse_client = Langfuse()
    return _langfuse_client


def load_dotenv(env_path: Path | None = None) -> None:
    """Load key=value pairs from a .env file into os.environ.

    Existing environment variables are NOT overwritten. Lines starting with #
    or that are blank are skipped. Supports optional quoting of values.
    """

    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    """Load AptJeeves settings with local-friendly defaults.

    Reads .env from the project root first so that env vars defined there are
    available before we look them up.
    """

    load_dotenv()
    db_path = Path(os.environ.get("APTJEEVES_DB_PATH", "aptjeeves.sqlite3"))
    data_dir = Path(os.environ.get("APTJEEVES_DATA_DIR", "data"))
    default_timezone = os.environ.get("APTJEEVES_DEFAULT_TIMEZONE", "Asia/Kolkata")
    log_level = os.environ.get("APTJEEVES_LOG_LEVEL", "INFO")
    llm_provider = os.environ.get("APTJEEVES_LLM_PROVIDER", "openai")
    llm_model = os.environ.get("APTJEEVES_LLM_MODEL", "gpt-4.1-mini")
    embedding_model = os.environ.get("APTJEEVES_EMBEDDING_MODEL", "text-embedding-3-small")
    extraction_backend = os.environ.get("APTJEEVES_EXTRACTION_BACKEND", "fake")
    extraction_model = os.environ.get("APTJEEVES_EXTRACTION_MODEL", "gpt-4.1-mini")
    intent_backend = os.environ.get("APTJEEVES_INTENT_BACKEND", "keyword")
    intent_model = os.environ.get("APTJEEVES_INTENT_MODEL", "gpt-4.1-mini")
    langfuse_secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    langfuse_public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_host = os.environ.get("LANGFUSE_HOST")
    return Settings(
        db_path=db_path,
        data_dir=data_dir,
        default_timezone=default_timezone,
        log_level=log_level,
        llm_provider=llm_provider,
        llm_model=llm_model,
        embedding_model=embedding_model,
        extraction_backend=extraction_backend,
        extraction_model=extraction_model,
        intent_backend=intent_backend,
        intent_model=intent_model,
        langfuse_secret_key=langfuse_secret_key,
        langfuse_public_key=langfuse_public_key,
        langfuse_host=langfuse_host,
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

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utc_now_iso() -> str:
    """Return a UTC timestamp string with second precision."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection configured for AptJeeves repositories."""

    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=30.0)
    # Row objects make repository code clearer than tuple indexes.
    connection.row_factory = sqlite3.Row
    # SQLite leaves foreign keys disabled by default; turn them on per connection.
    connection.execute("PRAGMA foreign_keys = ON")
    # Enable Write-Ahead Logging (WAL) mode for safe concurrent read/writes.
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply SQL migrations that have not yet been recorded."""

    # Bootstrap the migration ledger here so the first SQL migration can also be
    # rerun safely during tests and fresh database creation.
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration_file in migration_files:
        version = migration_file.stem
        if version in applied:
            continue
        sql = migration_file.read_text(encoding="utf-8")
        with connection:
            # executescript lets each migration define multiple tables/indexes.
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now_iso()),
            )

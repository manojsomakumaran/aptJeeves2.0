from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_text(value: str) -> str:
    """Return a SHA-256 hex digest for UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return a SHA-256 hex digest for a file without loading it all at once."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

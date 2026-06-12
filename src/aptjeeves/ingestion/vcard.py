from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_vcard(path: Path) -> dict[str, Any] | None:
    """Very small vCard parser: returns the first vCard's FN, TEL, EMAIL lists.

    Not a full-featured parser but sufficient for common exported .vcf files.
    """
    if not path.is_file():
        return None

    name = None
    phones: list[str] = []
    emails: list[str] = []
    in_vcard = False

    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if line.upper() == "BEGIN:VCARD":
                    in_vcard = True
                    continue
                if line.upper() == "END:VCARD":
                    break
                if not in_vcard:
                    continue
                # Simplistic key parsing: KEY[:;]
                if line.upper().startswith("FN:"):
                    name = line[3:].strip()
                elif line.upper().startswith("TEL"):
                    # Split on ':' to get value after params
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        phones.append(parts[1].strip())
                elif line.upper().startswith("EMAIL"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        emails.append(parts[1].strip())
    except Exception:
        return None

    if not (name or phones or emails):
        return None
    return {"name": name, "phones": phones, "emails": emails}

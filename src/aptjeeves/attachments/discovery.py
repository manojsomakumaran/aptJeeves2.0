from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_DIRECTION_MARKS = "‎‏‪‫‬‭‮﻿"

_SUPPORTED_EXTENSIONS = (
    "pdf", "docx", "xlsx", "csv", "txt", "md",
    "jpg", "jpeg", "png", "webp", "gif",
)
_EXT_ALT = "|".join(_SUPPORTED_EXTENSIONS)

# Android: "Rules.pdf (file attached)"; iOS: "<attached: 0001-DOC-Rules.pdf>"
_FILE_ATTACHED = re.compile(
    rf"^[ \t{_DIRECTION_MARKS}]*(?P<name>[^\r\n<>]+?\.(?:{_EXT_ALT}))[ \t]*\(file attached\)",
    re.IGNORECASE | re.MULTILINE,
)
_IOS_ATTACHED = re.compile(
    rf"<attached:\s*(?P<name>[^>\r\n]+?\.(?:{_EXT_ALT}))\s*>",
    re.IGNORECASE,
)
_BARE_FILENAME = re.compile(rf"^[^\r\n<>:/\\]+\.(?:{_EXT_ALT})$", re.IGNORECASE)


def find_attachment_filenames(text: str) -> list[str]:
    """Return attachment filenames referenced by one chat message.

    vCard files are intentionally excluded; the existing vCard flow owns them.
    """

    found: list[str] = []
    for pattern in (_FILE_ATTACHED, _IOS_ATTACHED):
        for match in pattern.finditer(text):
            found.append(_clean_name(match.group("name")))
    if not found:
        bare = _clean_name(text)
        if _BARE_FILENAME.match(bare):
            found.append(bare)

    unique: list[str] = []
    for name in found:
        if name and name not in unique:
            unique.append(name)
    return unique


def resolve_attachment_path(attachment_dir: Path, filename: str) -> Path:
    """Resolve an export filename in a folder, tolerating case/Unicode quirks.

    Only direct children of the folder are considered, so a hostile filename
    cannot escape it.
    """

    safe_name = Path(filename.replace("\\", "/")).name
    direct = attachment_dir / safe_name
    if direct.is_file():
        return direct

    target = _normalized_filename(safe_name)
    try:
        candidates = [c for c in attachment_dir.iterdir() if c.is_file()]
    except OSError:
        return direct
    for candidate in candidates:
        if _normalized_filename(candidate.name) == target:
            return candidate
    # iOS folders often prefix names (e.g. "00000012-DOC-Rules.pdf").
    for candidate in candidates:
        if _normalized_filename(candidate.name).endswith(target):
            return candidate
    return direct


def _clean_name(value: str) -> str:
    return value.strip(_DIRECTION_MARKS + " \t\r\n")


def _normalized_filename(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip(_DIRECTION_MARKS + " ").casefold()

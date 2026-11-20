from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.ingestion.parsers import ParsedMessage
from aptjeeves.privacy.redactor import REDACTOR_VERSION, redact_text


NORMALIZER_VERSION = "normalizer_v1"

_MEDIA_PLACEHOLDERS = {
    "<media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "gif omitted",
    "document omitted",
}


@dataclass(frozen=True)
class NormalizedMessage:
    """Canonical message fields ready for fingerprinting and storage."""

    canonical_sender: str
    sender_hash: str
    sender_display_hint: str
    sent_at_utc: str
    source_timezone: str
    normalized_text: str
    normalized_text_hash: str
    sanitized_text: str
    redaction_counts: dict[str, int]
    # placeholder -> original text for PHONE/EMAIL spans (local vault only).
    redaction_values: dict[str, str] = field(default_factory=dict, repr=False)


def normalize_message(
    parsed: ParsedMessage,
    *,
    default_timezone: str,
    date_order: str = "DMY",
) -> NormalizedMessage | None:
    """Normalize a parsed message into the durable ingestion shape.

    Returns `None` for messages that should not be stored, such as empty
    messages or media-only placeholders. Dedupe hashes use normalized text, while
    stored/extractor-bound text uses privacy-redacted sanitized text.
    """

    normalized_text = normalize_text(parsed.text)
    if not normalized_text or _is_media_only(normalized_text):
        return None

    # The canonical sender is hashed for storage; sender_display_hint remains a
    # short human clue for local debugging without becoming an identity source.
    canonical_sender = normalize_sender(parsed.sender)
    # Telegram JSON can provide a normalized UTC timestamp directly. WhatsApp
    # text exports still need date/time parsing with the configured timezone.
    sent_at_utc = parsed.sent_at_utc or normalize_timestamp(
        parsed.date_text,
        parsed.time_text,
        default_timezone=default_timezone,
        date_order=date_order,
    )
    redaction = redact_text(normalized_text)
    return NormalizedMessage(
        canonical_sender=canonical_sender,
        sender_hash=sha256_text(canonical_sender),
        sender_display_hint=_sender_display_hint(parsed.sender),
        sent_at_utc=sent_at_utc,
        source_timezone=default_timezone,
        normalized_text=normalized_text,
        normalized_text_hash=sha256_text(normalized_text),
        sanitized_text=redaction.text,
        redaction_counts=redaction.counts,
        redaction_values={
            placeholder: value
            for placeholder, value in redaction.values.items()
            if redaction.placeholders[placeholder] in {"PHONE", "EMAIL"}
        },
    )


def normalize_text(value: str) -> str:
    """Canonicalize message text while preserving meaningful line breaks."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def normalize_sender(value: str) -> str:
    """Normalize a sender name before hashing or fingerprint construction."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return normalized


def normalize_timestamp(
    date_text: str,
    time_text: str,
    *,
    default_timezone: str,
    date_order: str = "DMY",
) -> str:
    """Convert a chat-export timestamp to second-precision UTC ISO text."""

    day, month, year = _parse_date_parts(date_text, date_order=date_order)
    hour, minute, second = _parse_time_parts(time_text)
    local_dt = datetime(year, month, day, hour, minute, second, tzinfo=ZoneInfo(default_timezone))
    return local_dt.astimezone(ZoneInfo("UTC")).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def detect_date_order(date_texts: Iterable[str], *, fallback: str = "DMY") -> str:
    """Infer DMY vs MDY from slash-separated dates in a whole export.

    A first field above 12 proves DMY; a second field above 12 proves MDY.
    If every date is ambiguous (or the file is inconsistent), use `fallback`.
    """

    first_gt_12 = second_gt_12 = False
    for text in date_texts:
        parts = text.split("/")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        first_gt_12 |= int(parts[0]) > 12
        second_gt_12 |= int(parts[1]) > 12
    if second_gt_12 and not first_gt_12:
        return "MDY"
    if first_gt_12 and not second_gt_12:
        return "DMY"
    return fallback


def _parse_date_parts(date_text: str, *, date_order: str) -> tuple[int, int, int]:
    """Parse DMY or MDY date text from WhatsApp exports."""

    parts = [int(part) for part in date_text.split("/")]
    if len(parts) != 3:
        raise ValueError(f"Unsupported date format: {date_text}")

    first, second, year = parts
    if year < 100:
        # WhatsApp commonly exports two-digit years. Keep modern chat exports in
        # the 2000s while still mapping large values like 99 to the 1900s.
        year += 2000 if year < 70 else 1900

    order = date_order.upper()
    if order == "DMY":
        day, month = first, second
    elif order == "MDY":
        month, day = first, second
    else:
        raise ValueError(f"Unsupported date order: {date_order}")

    return day, month, year


def _parse_time_parts(time_text: str) -> tuple[int, int, int]:
    """Parse 12-hour or 24-hour WhatsApp time text."""

    value = re.sub(r"\s+", " ", time_text.strip())
    meridiem_match = re.search(r"\s*(AM|PM)$", value, flags=re.IGNORECASE)
    meridiem = meridiem_match.group(1).upper() if meridiem_match else None
    if meridiem:
        value = value[: meridiem_match.start()].strip()

    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        hour, minute = parts
        second = 0
    elif len(parts) == 3:
        hour, minute, second = parts
    else:
        raise ValueError(f"Unsupported time format: {time_text}")

    if meridiem == "AM" and hour == 12:
        hour = 0
    elif meridiem == "PM" and hour != 12:
        hour += 12

    return hour, minute, second


def _is_media_only(text: str) -> bool:
    """Return true for placeholder-only messages ignored in Phase 1."""

    cleaned = text.strip().casefold()
    return cleaned in _MEDIA_PLACEHOLDERS


def _sender_display_hint(sender: str) -> str:
    """Return a short non-canonical sender label for local debugging."""

    cleaned = re.sub(r"\s+", " ", sender).strip()
    if len(cleaned) <= 48:
        return cleaned
    return f"{cleaned[:45]}..."

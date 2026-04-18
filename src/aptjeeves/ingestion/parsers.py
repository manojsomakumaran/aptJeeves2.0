from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WHATSAPP_PARSER_VERSION = "whatsapp_text_v1"
TELEGRAM_PARSER_VERSION = "telegram_json_v1"
PARSER_VERSION = WHATSAPP_PARSER_VERSION


@dataclass(frozen=True)
class ParsedMessage:
    """One parsed chat message plus source-position metadata for traceability."""

    date_text: str
    time_text: str
    sender: str
    text: str
    source_offset: int
    source_line_start: int
    source_line_end: int
    source_message_id: str | None = None
    sent_at_utc: str | None = None


@dataclass(frozen=True)
class ParseFailure:
    """A non-fatal line-level parsing problem."""

    line_number: int
    source_offset: int
    reason: str
    text_preview: str


@dataclass(frozen=True)
class ParseResult:
    """All parsed messages and recoverable parse failures from one export."""

    messages: list[ParsedMessage]
    failures: list[ParseFailure]
    chat_name: str | None = None
    source_conversation_id: str | None = None


class WhatsAppTextParser:
    """Parser for common WhatsApp text export formats.

    Supports both common export prefixes:

    - `16/04/26, 9:30 PM - Alice: message`
    - `[16/04/26, 9:30 PM] Alice: message`

    Lines that do not start a new message are appended to the current message.
    That preserves multiline chat messages while still recording source line
    numbers for later debugging.
    """

    _patterns = [
        re.compile(
            r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s+"
            r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\s+-\s+"
            r"(?P<sender>[^:]+):\s?(?P<text>.*)$"
        ),
        re.compile(
            r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s+"
            r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\]\s+"
            r"(?P<sender>[^:]+):\s?(?P<text>.*)$"
        ),
    ]

    def parse_file(self, path: Path) -> ParseResult:
        """Read a WhatsApp text export and parse it into message records."""

        text = path.read_text(encoding="utf-8-sig")
        return self.parse_text(text)

    def parse_text(self, text: str) -> ParseResult:
        """Parse WhatsApp export text.

        The parser is intentionally permissive: malformed leading lines become
        parse failures, but malformed continuation lines are treated as part of
        the previous message because WhatsApp messages can span multiple lines.
        """

        messages: list[ParsedMessage] = []
        failures: list[ParseFailure] = []
        current: dict[str, object] | None = None
        offset = 0

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            # Store byte-ish character offsets for source tracing. Exact byte
            # offsets are not required yet because exports are read as text.
            line_offset = offset
            offset += len(raw_line) + 1
            line = raw_line.rstrip("\r")
            match = self._match_message_start(line)

            if match:
                # A new timestamped line closes the previous message, if any.
                if current is not None:
                    messages.append(self._finalize(current))
                current = {
                    "date_text": match.group("date"),
                    "time_text": match.group("time"),
                    "sender": match.group("sender"),
                    "lines": [match.group("text")],
                    "source_offset": line_offset,
                    "source_line_start": line_number,
                    "source_line_end": line_number,
                }
                continue

            if current is not None:
                # Non-header lines after a message header are multiline content.
                current["lines"].append(line)  # type: ignore[index, union-attr]
                current["source_line_end"] = line_number
                continue

            if line.strip():
                # Leading garbage is surfaced as a recoverable parse failure.
                failures.append(
                    ParseFailure(
                        line_number=line_number,
                        source_offset=line_offset,
                        reason="line_does_not_match_whatsapp_message_format",
                        text_preview=line[:80],
                    )
                )

        if current is not None:
            messages.append(self._finalize(current))

        return ParseResult(messages=messages, failures=failures)

    def _match_message_start(self, line: str) -> re.Match[str] | None:
        """Return the first WhatsApp message-start match for a line."""

        for pattern in self._patterns:
            match = pattern.match(line)
            if match:
                return match
        return None

    def _finalize(self, current: dict[str, object]) -> ParsedMessage:
        """Convert the mutable in-progress parse state into a ParsedMessage."""

        return ParsedMessage(
            date_text=str(current["date_text"]),
            time_text=str(current["time_text"]),
            sender=str(current["sender"]).strip(),
            text="\n".join(current["lines"]),  # type: ignore[arg-type]
            source_offset=int(current["source_offset"]),
            source_line_start=int(current["source_line_start"]),
            source_line_end=int(current["source_line_end"]),
        )


class TelegramJsonParser:
    """Parser for Telegram Desktop JSON exports.

    Telegram JSON exports usually include stable message IDs and top-level chat
    metadata. The ingestion layer uses those IDs for stronger dedupe than the
    WhatsApp text fallback can provide.
    """

    def parse_file(self, path: Path) -> ParseResult:
        """Read a Telegram JSON export and parse message records."""

        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        return self.parse_data(data)

    def parse_data(self, data: dict[str, Any]) -> ParseResult:
        """Parse a Telegram export object loaded from JSON."""

        messages: list[ParsedMessage] = []
        failures: list[ParseFailure] = []
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            return ParseResult(
                messages=[],
                failures=[
                    ParseFailure(
                        line_number=0,
                        source_offset=0,
                        reason="telegram_messages_not_a_list",
                        text_preview="messages",
                    )
                ],
                chat_name=_string_or_none(data.get("name")),
                source_conversation_id=_string_or_none(data.get("id")),
            )

        for index, item in enumerate(raw_messages):
            if not isinstance(item, dict):
                failures.append(
                    ParseFailure(
                        line_number=index + 1,
                        source_offset=index,
                        reason="telegram_message_not_an_object",
                        text_preview=str(item)[:80],
                    )
                )
                continue

            # Telegram service messages describe membership/title changes. They
            # are useful audit context later, but not chat content for Milestone 1.
            if item.get("type") != "message":
                continue

            text = _telegram_text_to_string(item.get("text"))
            if not text.strip():
                continue

            sent_at_utc = _telegram_sent_at_utc(item)
            if sent_at_utc is None:
                failures.append(
                    ParseFailure(
                        line_number=index + 1,
                        source_offset=index,
                        reason="telegram_message_missing_date",
                        text_preview=text[:80],
                    )
                )
                continue

            sender = _telegram_sender(item)
            messages.append(
                ParsedMessage(
                    date_text="",
                    time_text="",
                    sender=sender,
                    text=text,
                    source_offset=index,
                    source_line_start=index + 1,
                    source_line_end=index + 1,
                    source_message_id=_string_or_none(item.get("id")),
                    sent_at_utc=sent_at_utc,
                )
            )

        return ParseResult(
            messages=messages,
            failures=failures,
            chat_name=_string_or_none(data.get("name")),
            source_conversation_id=_string_or_none(data.get("id")),
        )


def _telegram_text_to_string(value: Any) -> str:
    """Flatten Telegram text fields, which can be strings or rich-text lists."""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _telegram_sent_at_utc(item: dict[str, Any]) -> str | None:
    """Return Telegram message time as UTC ISO text."""

    date_unixtime = item.get("date_unixtime")
    if date_unixtime is not None:
        try:
            timestamp = int(str(date_unixtime))
        except ValueError:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")

    date_value = item.get("date")
    if isinstance(date_value, str):
        try:
            parsed = datetime.fromisoformat(date_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    return None


def _telegram_sender(item: dict[str, Any]) -> str:
    """Return the most stable sender label available in a Telegram message."""

    from_id = _string_or_none(item.get("from_id"))
    if from_id:
        return from_id
    sender = _string_or_none(item.get("from"))
    if sender:
        return sender
    return "unknown"


def _string_or_none(value: Any) -> str | None:
    """Return a stripped string for scalar JSON values, otherwise None."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None

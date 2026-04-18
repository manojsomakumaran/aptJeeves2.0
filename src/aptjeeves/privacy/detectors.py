from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SensitiveSpan:
    """A detected sensitive text range."""

    kind: str
    start: int
    end: int
    text: str


PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?91[\s-]?)?(?:0[\s-]?)?"
    r"(?:[6-9]\d{4}[\s-]\d{5}|[6-9]\d{2}[\s-]?\d{3}[\s-]?\d{4}|[6-9]\d{9})(?!\w)"
)
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>()]+")
FLAT_PATTERN = re.compile(
    r"(?ix)"
    r"(?<!\w)("
    r"(?:flat|apt|apartment|unit)\s*[A-Z]?\s*[-/]?\s*\d{2,4}[A-Z]?"
    r"|[A-Z]\s*[-/]\s*\d{3,4}[A-Z]?"
    r")(?!\w)"
)
ADDRESS_PATTERN = re.compile(
    r"(?i)\b(?:tower|block|building)\s+[A-Z0-9]{1,4}\b"
)


def detect_sensitive_spans(text: str) -> list[SensitiveSpan]:
    """Return non-overlapping sensitive spans in the order they appear.

    Detection is intentionally deterministic. The patterns favor common Indian
    apartment-chat formats: phone numbers, emails, URLs, flat/unit numbers, and
    simple tower/block markers.
    """

    candidates: list[SensitiveSpan] = []
    for kind, pattern in (
        ("PHONE", PHONE_PATTERN),
        ("EMAIL", EMAIL_PATTERN),
        ("URL", URL_PATTERN),
        ("FLAT", FLAT_PATTERN),
        ("ADDRESS", ADDRESS_PATTERN),
    ):
        for match in pattern.finditer(text):
            span_text = match.group(0).strip()
            if not span_text:
                continue
            if kind == "FLAT" and _looks_like_phone(span_text):
                continue
            candidates.append(
                SensitiveSpan(
                    kind=kind,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                )
            )

    return _without_overlaps(candidates)


def _without_overlaps(spans: list[SensitiveSpan]) -> list[SensitiveSpan]:
    """Keep earlier/higher-priority spans when detector matches overlap."""

    priority = {"URL": 0, "EMAIL": 1, "PHONE": 2, "FLAT": 3, "ADDRESS": 4}
    ordered = sorted(spans, key=lambda span: (span.start, priority[span.kind], -(span.end - span.start)))
    selected: list[SensitiveSpan] = []
    occupied: list[range] = []

    for span in ordered:
        current = range(span.start, span.end)
        if any(_ranges_overlap(current, existing) for existing in occupied):
            continue
        selected.append(span)
        occupied.append(current)

    return sorted(selected, key=lambda span: span.start)


def _ranges_overlap(left: range, right: range) -> bool:
    """Return true when two half-open ranges overlap."""

    return left.start < right.stop and right.start < left.stop


def _looks_like_phone(value: str) -> bool:
    """Avoid redacting phone-like strings twice as flat numbers."""

    digits = re.sub(r"\D", "", value)
    return len(digits) >= 10

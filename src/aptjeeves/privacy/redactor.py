from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from aptjeeves.privacy.detectors import SensitiveSpan, detect_sensitive_spans


REDACTOR_VERSION = "privacy_redactor_v1"


@dataclass(frozen=True)
class RedactionResult:
    """Privacy-redacted text and safe metadata about what changed."""

    text: str
    counts: dict[str, int]
    placeholders: dict[str, str]


def redact_text(text: str) -> RedactionResult:
    """Replace sensitive values with typed placeholders.

    Placeholder numbering is per message and per sensitive type. The result
    keeps counts for observability but never exposes the original values.
    """

    spans = detect_sensitive_spans(text)
    if not spans:
        return RedactionResult(text=text, counts={}, placeholders={})

    counters: Counter[str] = Counter()
    parts: list[str] = []
    placeholders: dict[str, str] = {}
    cursor = 0

    for span in spans:
        counters[span.kind] += 1
        placeholder = f"{span.kind}_{counters[span.kind]}"
        parts.append(text[cursor : span.start])
        parts.append(placeholder)
        placeholders[placeholder] = span.kind
        cursor = span.end

    parts.append(text[cursor:])
    return RedactionResult(
        text="".join(parts),
        counts=dict(counters),
        placeholders=placeholders,
    )


def redact_preview(text: str, *, max_length: int = 80) -> str:
    """Return a short privacy-safe preview for logs/events."""

    return redact_text(text).text[:max_length]

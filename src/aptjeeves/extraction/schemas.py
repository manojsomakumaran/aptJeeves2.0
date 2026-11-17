from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


EXTRACTOR_PROMPT_VERSION = "extractor_contract_v1"
FAKE_LLM_MODEL_VERSION = "fake_extractor_v1"


@dataclass(frozen=True)
class MessageForExtraction:
    """Sanitized message input passed to an extractor."""

    message_id: str
    message_fingerprint: str
    sent_at_utc: str
    sender_hash: str
    sanitized_text: str
    # Attachment-derived segments carry their origin; chat messages keep defaults.
    source_kind: str = "chat"
    attachment_name: str | None = None
    segment_label: str | None = None


@dataclass(frozen=True)
class ExtractedFact:
    """Validated extracted fact in the shared extraction contract."""

    fact_type: str
    identity_key_hint: str
    title: str
    summary: str
    confidence: float
    privacy_status_hint: str
    source_message_ids: list[str]
    sanitized_snippets: list[str]
    details: dict[str, Any]


@dataclass(frozen=True)
class ExtractionResult:
    """Validated extraction response."""

    facts: list[ExtractedFact]
    warnings: list[str]


class Extractor(Protocol):
    """Protocol for fake or LLM-backed extractors."""

    prompt_version: str
    model_version: str

    def extract(self, messages: list[MessageForExtraction]) -> dict[str, Any]:
        """Return an extraction payload following the JSON contract."""

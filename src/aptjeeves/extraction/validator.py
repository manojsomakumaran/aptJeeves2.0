from __future__ import annotations

import re
from typing import Any

from aptjeeves.extraction.schemas import ExtractedFact, ExtractionResult


SUPPORTED_FACT_TYPES = {"service_contact", "process_info", "facility_info"}
SUPPORTED_PRIVACY_STATUSES = {
    "public_to_residents",
    "restricted_resident_pii",
    "restricted_unknown_contact",
    "restricted_sensitive",
    "needs_review",
}


class ExtractionValidationError(ValueError):
    """Raised when an extractor response does not follow the contract."""


def validate_extraction_payload(
    payload: dict[str, Any],
    *,
    allowed_message_ids: set[str],
) -> ExtractionResult:
    """Validate extractor JSON and return typed facts.

    This is deliberately dependency-free for now. When a real LLM extractor is
    added, it should pass raw JSON through this same validator before storage.
    """

    if not isinstance(payload, dict):
        raise ExtractionValidationError("Extraction payload must be an object")
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        raise ExtractionValidationError("Extraction payload must contain a facts list")

    facts: list[ExtractedFact] = []
    for index, raw_fact in enumerate(raw_facts):
        if not isinstance(raw_fact, dict):
            raise ExtractionValidationError(f"facts[{index}] must be an object")
        facts.append(_validate_fact(raw_fact, index=index, allowed_message_ids=allowed_message_ids))

    warnings = payload.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ExtractionValidationError("warnings must be a list of strings")
    return ExtractionResult(facts=facts, warnings=warnings)


def _validate_fact(
    raw_fact: dict[str, Any],
    *,
    index: int,
    allowed_message_ids: set[str],
) -> ExtractedFact:
    fact_type = _required_string(raw_fact, "fact_type", index=index)
    if fact_type not in SUPPORTED_FACT_TYPES:
        raise ExtractionValidationError(f"facts[{index}].fact_type is unsupported: {fact_type}")

    confidence = raw_fact.get("confidence")
    if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
        raise ExtractionValidationError(f"facts[{index}].confidence must be between 0 and 1")

    privacy_status_hint = _required_string(raw_fact, "privacy_status_hint", index=index)
    if privacy_status_hint not in SUPPORTED_PRIVACY_STATUSES:
        raise ExtractionValidationError(
            f"facts[{index}].privacy_status_hint is unsupported: {privacy_status_hint}"
        )

    source_message_ids = _required_string_list(raw_fact, "source_message_ids", index=index)
    unknown_ids = set(source_message_ids) - allowed_message_ids
    if unknown_ids:
        raise ExtractionValidationError(
            f"facts[{index}].source_message_ids contains unknown IDs: {sorted(unknown_ids)}"
        )

    snippets = _required_string_list(raw_fact, "sanitized_snippets", index=index)
    if any(_looks_unsanitized(snippet) for snippet in snippets):
        raise ExtractionValidationError(f"facts[{index}].sanitized_snippets contain raw-looking PII")

    details = raw_fact.get(fact_type)
    if not isinstance(details, dict):
        raise ExtractionValidationError(f"facts[{index}].{fact_type} must be an object")

    return ExtractedFact(
        fact_type=fact_type,
        identity_key_hint=_required_string(raw_fact, "identity_key_hint", index=index),
        title=_required_string(raw_fact, "title", index=index),
        summary=_required_string(raw_fact, "summary", index=index),
        confidence=float(confidence),
        privacy_status_hint=privacy_status_hint,
        source_message_ids=source_message_ids,
        sanitized_snippets=snippets,
        details=details,
    )


def _required_string(raw: dict[str, Any], key: str, *, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionValidationError(f"facts[{index}].{key} must be a non-empty string")
    return value.strip()


def _required_string_list(raw: dict[str, Any], key: str, *, index: int) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ExtractionValidationError(f"facts[{index}].{key} must be a non-empty string list")
    return [item.strip() for item in value if item.strip()]


def _looks_unsanitized(value: str) -> bool:
    """Catch obvious raw phone/email values in snippets before storage."""

    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value):
        return True
    return bool(re.search(r"(?<!\w)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\w)", value))

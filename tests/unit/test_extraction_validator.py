from __future__ import annotations

import pytest

from aptjeeves.extraction.validator import ExtractionValidationError, validate_extraction_payload


def test_validate_extraction_payload_accepts_service_contact() -> None:
    result = validate_extraction_payload(
        {
            "facts": [
                {
                    "fact_type": "service_contact",
                    "identity_key_hint": "plumber|PHONE_1",
                    "title": "Plumber contact",
                    "summary": "Residents mentioned a plumber.",
                    "confidence": 0.8,
                    "privacy_status_hint": "needs_review",
                    "source_message_ids": ["msg_1"],
                    "sanitized_snippets": ["Call PHONE_1 for plumbing."],
                    "service_contact": {
                        "service_type": "plumber",
                        "contact_methods": [{"type": "phone", "value_placeholder": "PHONE_1"}],
                    },
                }
            ],
            "warnings": [],
        },
        allowed_message_ids={"msg_1"},
    )

    assert len(result.facts) == 1
    assert result.facts[0].fact_type == "service_contact"


def test_validate_extraction_payload_rejects_unknown_source_message_id() -> None:
    with pytest.raises(ExtractionValidationError):
        validate_extraction_payload(
            {
                "facts": [
                    {
                        "fact_type": "facility_info",
                        "identity_key_hint": "clubhouse",
                        "title": "Clubhouse booking",
                        "summary": "Residents discussed clubhouse booking.",
                        "confidence": 0.8,
                        "privacy_status_hint": "public_to_residents",
                        "source_message_ids": ["missing"],
                        "sanitized_snippets": ["Clubhouse booking details."],
                        "facility_info": {"facility_name": "Clubhouse", "info_type": "booking"},
                    }
                ],
                "warnings": [],
            },
            allowed_message_ids={"msg_1"},
        )


def test_validate_extraction_payload_rejects_raw_pii_in_snippets() -> None:
    with pytest.raises(ExtractionValidationError):
        validate_extraction_payload(
            {
                "facts": [
                    {
                        "fact_type": "service_contact",
                        "identity_key_hint": "plumber|raw",
                        "title": "Plumber contact",
                        "summary": "Residents mentioned a plumber.",
                        "confidence": 0.8,
                        "privacy_status_hint": "needs_review",
                        "source_message_ids": ["msg_1"],
                        "sanitized_snippets": ["Call 9876543210 for plumbing."],
                        "service_contact": {"service_type": "plumber"},
                    }
                ],
                "warnings": [],
            },
            allowed_message_ids={"msg_1"},
        )

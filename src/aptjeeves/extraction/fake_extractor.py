from __future__ import annotations

import re
from typing import Any

from aptjeeves.extraction.schemas import (
    EXTRACTOR_PROMPT_VERSION,
    FAKE_LLM_MODEL_VERSION,
    MessageForExtraction,
)


class FakeExtractor:
    """Deterministic extractor used for local tests before real LLM calls."""

    prompt_version = EXTRACTOR_PROMPT_VERSION
    model_version = FAKE_LLM_MODEL_VERSION

    def extract(self, messages: list[MessageForExtraction]) -> dict[str, Any]:
        """Return fake extraction JSON based on simple keyword heuristics."""

        facts: list[dict[str, Any]] = []
        for message in messages:
            text = message.sanitized_text
            lowered = text.casefold()
            phone_placeholder = _first_placeholder(text, "PHONE")

            if phone_placeholder and ("plumb" in lowered or "electric" in lowered):
                service_type = "electrician" if "electric" in lowered else "plumber"
                facts.append(
                    {
                        "fact_type": "service_contact",
                        "identity_key_hint": f"{service_type}|{phone_placeholder}",
                        "title": f"{service_type.title()} contact",
                        "summary": f"Residents mentioned a {service_type} contact.",
                        "confidence": 0.75,
                        "privacy_status_hint": "needs_review",
                        "source_message_ids": [message.message_id],
                        "sanitized_snippets": [text],
                        "service_contact": {
                            "service_type": service_type,
                            "display_name": None,
                            "contact_methods": [
                                {
                                    "type": "phone",
                                    "value_placeholder": phone_placeholder,
                                    "exposure_recommendation": "needs_review",
                                }
                            ],
                            "contact_classification": "vendor_or_service_contact",
                            "is_resident_affiliated": False,
                            "resident_affiliation_reason": None,
                            "price_hint": None,
                            "availability_hint": None,
                            "caveats": None,
                        },
                    }
                )

            if "gas" in lowered and "address" in lowered:
                facts.append(
                    {
                        "fact_type": "process_info",
                        "identity_key_hint": "gas-address-update",
                        "title": "Gas address update",
                        "summary": "Residents discussed updating the address for a gas connection.",
                        "confidence": 0.7,
                        "privacy_status_hint": "public_to_residents",
                        "source_message_ids": [message.message_id],
                        "sanitized_snippets": [text],
                        "process_info": {
                            "process_name": "Gas address update",
                            "category": "utilities",
                            "provider_or_authority": "Gas provider",
                            "steps": ["Check the provider process shared by residents."],
                            "required_documents": [],
                            "fees": [],
                            "locations_or_portals": [],
                            "deadlines": [],
                            "caveats": "Community-discussed information only; not officially verified.",
                            "staleness_risk": "high",
                        },
                    }
                )

            if "clubhouse" in lowered and ("book" in lowered or "booking" in lowered):
                facts.append(
                    {
                        "fact_type": "facility_info",
                        "identity_key_hint": "clubhouse-booking",
                        "title": "Clubhouse booking",
                        "summary": "Residents discussed clubhouse booking.",
                        "confidence": 0.7,
                        "privacy_status_hint": "public_to_residents",
                        "source_message_ids": [message.message_id],
                        "sanitized_snippets": [text],
                        "facility_info": {
                            "facility_name": "Clubhouse",
                            "info_type": "booking_process",
                            "location_hint": None,
                            "availability": None,
                            "rules_or_steps": ["Check availability with the facility office."],
                            "caveats": None,
                        },
                    }
                )

        return {"facts": facts, "warnings": []}


def _first_placeholder(text: str, kind: str) -> str | None:
    """Return the first placeholder like PHONE_1 from sanitized text."""

    match = re.search(rf"\b{kind}_\d+\b", text)
    return match.group(0) if match else None

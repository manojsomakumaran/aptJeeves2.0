from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any
import langfuse.openai

from langfuse.decorators import observe
from langfuse.openai import OpenAI
from aptjeeves.extraction.schemas import MessageForExtraction

logger = logging.getLogger(__name__)


LLM_EXTRACTOR_PROMPT_VERSION = "extractor_contract_openai_v1"

_SYSTEM_PROMPT = """\
You extract structured community facts from sanitized apartment chat messages.
Return JSON only with this exact shape:
{"facts": [fact1, fact2, ...], "warnings": ["optional", "warnings"]}

FACT STRUCTURE:
{
  "fact_type": "service_contact" | "process_info" | "facility_info",
  "identity_key_hint": "unique_identifier",
  "title": "Short title",
  "summary": "Detailed description of the fact",
  "confidence": 0.8,  // decimal between 0 and 1
  "privacy_status_hint": "public_to_residents" | "restricted_resident_pii" | "restricted_unknown_contact" | "restricted_sensitive" | "needs_review",
  "source_message_ids": ["msg_id1", "msg_id2"],  // list of actual message IDs from input
  "sanitized_snippets": ["relevant text snippet 1", "relevant text snippet 2"],
  "service_contact": {  // Include ONLY if fact_type is "service_contact", otherwise null
    "service_type": "plumber",
    "contact_methods": [{"type": "phone" | "email" | "website" | "other", "value_placeholder": "PHONE_1"}]
  },
  "process_info": {  // Include ONLY if fact_type is "process_info", otherwise null
    "process_name": "Name of the process",
    "category": "category (string or null)",
    "provider_or_authority": "authority name (string or null)",
    "steps": ["Step 1", "Step 2"],  // array of strings, empty array if none
    "required_documents": ["Doc 1"],  // array of strings, empty array if none
    "fees": ["Fee 1"],  // array of strings, empty array if none
    "locations_or_portals": ["Location 1"],  // array of strings, empty array if none
    "deadlines": ["Deadline 1"],  // array of strings, empty array if none
    "caveats": "caveats (string or null)",
    "staleness_risk": "low" | "medium" | "high",  // default "medium"
    "official_verification_status": "verified" | "not_verified"  // default "not_verified"
  },
  "facility_info": {  // Include ONLY if fact_type is "facility_info", otherwise null
    "facility_name": "Name of the facility",
    "info_type": "general" | "rules" | "booking" | "hours",  // default "general"
    "location_hint": "location (string or null)",
    "availability": "hours or availability (string or null)",
    "rules_or_steps": ["Rule 1"],  // array of strings, empty array if none
    "caveats": "caveats (string or null)"
  }
}

CRITICAL RULES:
- Extract ONLY factual data explicitly mentioned in the input messages. Do NOT assume, extrapolate, or hallucinate.
- If an optional field (marked as "or null") or list field is not explicitly present in the input, set it to null or an empty list [] respectively. Do NOT populate them with guessed or placeholder info.
- source_message_ids MUST be a list of the exact message_id strings from the input messages. Do NOT use the message_fingerprint values or prepend 'msg_' to them.
- confidence MUST be a decimal between 0 and 1 (e.g., 0.85, NOT 85 or 100)
- Use only input messages for source_message_ids - never invent IDs
- Preserve placeholder values like PHONE_1, EMAIL_1 exactly as provided
- Do not include facts with confidence < 0.1

FEW-SHOT EXAMPLES FOR GUIDANCE:

Example 1 (service_contact and facility_info):
Input:
{"messages": [
  {"message_id": "msg_1", "sender_hash": "user_a", "sanitized_text": "Hey everyone, if you need a plumber, call Alice at PHONE_1. She fixed my leak today."},
  {"message_id": "msg_2", "sender_hash": "user_b", "sanitized_text": "Is the swimming pool open today?"},
  {"message_id": "msg_3", "sender_hash": "user_c", "sanitized_text": "Yes, pool is open from 8am to 8pm daily. You need to book slot on portal."}
]}
Output:
{
  "facts": [
    {
      "fact_type": "service_contact",
      "identity_key_hint": "plumber_alice",
      "title": "Plumber Alice",
      "summary": "Alice is a plumber recommended by residents for fixing leaks.",
      "confidence": 0.95,
      "privacy_status_hint": "public_to_residents",
      "source_message_ids": ["msg_1"],
      "sanitized_snippets": ["if you need a plumber, call Alice at PHONE_1"],
      "service_contact": {
        "service_type": "plumber",
        "contact_methods": [{"type": "phone", "value_placeholder": "PHONE_1"}]
      },
      "process_info": null,
      "facility_info": null
    },
    {
      "fact_type": "facility_info",
      "identity_key_hint": "swimming_pool",
      "title": "Swimming Pool Booking and Hours",
      "summary": "The community swimming pool is open daily from 8am to 8pm. Slot booking is required via the resident portal.",
      "confidence": 0.9,
      "privacy_status_hint": "public_to_residents",
      "source_message_ids": ["msg_2", "msg_3"],
      "sanitized_snippets": ["pool is open from 8am to 8pm daily", "You need to book slot on portal"],
      "service_contact": null,
      "process_info": null,
      "facility_info": {
        "facility_name": "Swimming Pool",
        "info_type": "booking",
        "location_hint": null,
        "availability": "8am to 8pm daily",
        "rules_or_steps": ["Slot booking required on the resident portal"],
        "caveats": null
      }
    }
  ],
  "warnings": []
}

Example 2 (process_info):
Input:
{"messages": [
  {"message_id": "msg_4", "sender_hash": "user_a", "sanitized_text": "How do we get a guest parking permit?"},
  {"message_id": "msg_5", "sender_hash": "user_b", "sanitized_text": "Fill the guest permit form in the lobby, pay $10, and submit it to the security desk. It takes 1 day."}
]}
Output:
{
  "facts": [
    {
      "fact_type": "process_info",
      "identity_key_hint": "guest_parking_permit",
      "title": "Guest Parking Permit Process",
      "summary": "Process to obtain a guest parking permit by filling a form in the lobby, paying a fee, and submitting it to security.",
      "confidence": 0.95,
      "privacy_status_hint": "public_to_residents",
      "source_message_ids": ["msg_4", "msg_5"],
      "sanitized_snippets": ["Fill the guest permit form in the lobby, pay $10, and submit it to the security desk. It takes 1 day."],
      "service_contact": null,
      "process_info": {
        "process_name": "Guest Parking Permit",
        "category": "Parking",
        "provider_or_authority": "Security Desk",
        "steps": ["Fill the guest permit form in the lobby", "Pay $10 fee", "Submit form to the security desk"],
        "required_documents": ["Guest permit form"],
        "fees": ["$10"],
        "locations_or_portals": ["Lobby", "Security desk"],
        "deadlines": [],
        "caveats": "Processing takes 1 day",
        "staleness_risk": "low",
        "official_verification_status": "not_verified"
      },
      "facility_info": null
    }
  ],
  "warnings": []
}
"""


class LLMExtractor:
    """OpenAI-backed extractor that returns the shared JSON extraction contract."""

    prompt_version = LLM_EXTRACTOR_PROMPT_VERSION

    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self.model_version = f"openai_extractor_{model}_v1"

    @observe(name="llm_extract_facts")
    def extract(self, messages: list[MessageForExtraction], trace_id: str | None = None) -> dict[str, Any]:
        logger.info(f"Sending {len(messages)} messages to OpenAI extractor ({self._model})")
        payload = {"messages": [asdict(message) for message in messages]}
        request = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
            "temperature": 0.1,
            "max_tokens": 2400,
            "response_format": {"type": "json_object"},
        }

        try:
            response = self._client.chat.completions.create(**request)
        except TypeError:
            request.pop("response_format", None)
            response = self._client.chat.completions.create(**request)
        except Exception as e:
            logger.error("Error during LLM extraction request to OpenAI", exc_info=True)
            raise

        content = response.choices[0].message.content
        if not content:
            logger.error("Extractor returned empty content")
            raise ValueError("Extractor returned empty content")
        
        logger.debug("Successfully received response from OpenAI extractor")
        return _parse_extractor_json(content)


def _parse_extractor_json(content: str) -> dict[str, Any]:
    """Parse extractor output, tolerating fenced JSON responses."""

    body = content.strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
        body = body.strip()

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        end = body.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(body[start:end + 1])
        raise

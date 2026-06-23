from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any
import langfuse.openai

from langfuse.decorators import observe
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
  "service_contact": {  // for service_contact fact_type only
    "service_type": "plumber",
    "contact_methods": [{"type": "phone", "value_placeholder": "PHONE_1"}]
  },
  "process_info": {...},  // for process_info fact_type
  "facility_info": {...}   // for facility_info fact_type
}

CRITICAL RULES:
- source_message_ids MUST be a list of message_id strings from the input messages
- confidence MUST be a decimal between 0 and 1 (e.g., 0.85, NOT 85 or 100)
- Use only input messages for source_message_ids - never invent IDs
- Preserve placeholder values like PHONE_1, EMAIL_1 exactly as provided
- Do not include facts with confidence < 0.1
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

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol


INTENT_VERSION = "keyword_intent_v1"
SUPPORTED_INTENTS = {
    "find_service_contact",
    "ask_process_steps",
    "ask_facility_info",
    "ask_policy_or_rule",
    "ask_alert_or_issue",
    "general_or_unknown",
}


@dataclass(frozen=True)
class IntentResult:
    """Classified query intent with confidence."""

    intent: str
    confidence: float
    matched_keywords: list[str]


class IntentClassifier(Protocol):
    """Shared interface for keyword and provider-backed intent classifiers."""

    version: str

    def classify(self, query: str) -> IntentResult:
        """Classify a resident query into a supported intent."""


# Keyword sets mapped to intent types.  Order matters: first match wins.
_INTENT_RULES: list[tuple[str, list[str]]] = [
    (
        "find_service_contact",
        [
            "plumber", "electrician", "carpenter", "painter", "maid",
            "cook", "driver", "pest control", "pest", "cleaner",
            "cleaning", "gardener", "ac repair", "ac service",
            "washing machine", "appliance", "repair", "service",
            "technician", "mechanic", "beautician", "salon",
            "masseuse", "massage", "doctor", "dentist", "vet",
            "contact", "phone", "number", "call",
        ],
    ),
    (
        "ask_process_steps",
        [
            "how to", "how do", "process", "steps", "procedure",
            "renewal", "registration", "apply", "application",
            "address update", "address change", "transfer",
            "gas connection", "gas address", "e-khata", "ekhata",
            "bbmp", "bescom", "property tax", "voter id",
            "school admission", "admission", "document",
            "portal", "online", "form", "fee",
        ],
    ),
    (
        "ask_facility_info",
        [
            "clubhouse", "club house", "gym", "swimming pool",
            "pool", "parking", "lift", "elevator",
            "generator", "water tank", "water supply",
            "gate", "security", "intercom", "maintenance",
            "facility", "amenity", "amenities", "booking",
            "book", "timings", "timing", "hours",
            "open", "close", "available", "availability",
        ],
    ),
    (
        "ask_policy_or_rule",
        [
            "rule", "policy", "regulation", "guideline",
            "allowed", "not allowed", "prohibited", "banned",
            "fine", "penalty", "pet", "pets", "noise",
            "visitor", "guest", "parking rule",
        ],
    ),
    (
        "ask_alert_or_issue",
        [
            "alert", "warning", "issue", "problem",
            "broken", "leak", "outage", "power cut",
            "water cut", "maintenance scheduled",
            "construction", "notice",
        ],
    ),
]


def classify_intent(query: str) -> IntentResult:
    """Classify a resident query into an intent type using keyword matching.

    Returns general_or_unknown when no keywords match.
    """

    lowered = query.casefold()
    # Normalize whitespace for multi-word keyword matching.
    normalized = re.sub(r"\s+", " ", lowered).strip()

    best_intent = "general_or_unknown"
    best_score = 0.0
    best_keywords: list[str] = []

    for intent, keywords in _INTENT_RULES:
        matched = [kw for kw in keywords if kw in normalized]
        if not matched:
            continue
        score = min(len(matched) / 3.0, 1.0)
        if score > best_score:
            best_intent = intent
            best_score = score
            best_keywords = matched

    confidence = max(best_score, 0.3) if best_intent != "general_or_unknown" else 0.1
    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        matched_keywords=best_keywords,
    )


class KeywordIntentClassifier:
    """Adapter exposing the deterministic classifier through a shared protocol."""

    version = INTENT_VERSION

    def classify(self, query: str) -> IntentResult:
        return classify_intent(query)


class OpenAIIntentClassifier:
    """OpenAI-backed intent classifier with deterministic fallback."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4.1-mini",
        fallback: IntentClassifier | None = None,
    ) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self.fallback = fallback or KeywordIntentClassifier()
        self.version = f"openai_intent_{model}_v1"

    def classify(self, query: str) -> IntentResult:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the resident query into one of these labels only: "
                            + ", ".join(sorted(SUPPORTED_INTENTS))
                            + ". Return JSON with keys intent, confidence, matched_keywords."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty intent response")
            payload = json.loads(content)
            intent = str(payload.get("intent", "")).strip()
            if intent not in SUPPORTED_INTENTS:
                raise ValueError(f"unsupported intent: {intent}")
            confidence = float(payload.get("confidence", 0.1))
            matched_keywords = payload.get("matched_keywords") or []
            if not isinstance(matched_keywords, list):
                matched_keywords = []
            return IntentResult(
                intent=intent,
                confidence=round(min(max(confidence, 0.0), 1.0), 2),
                matched_keywords=[str(item) for item in matched_keywords],
            )
        except Exception:
            return self.fallback.classify(query)

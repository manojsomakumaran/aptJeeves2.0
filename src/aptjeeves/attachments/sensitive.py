from __future__ import annotations

import re
from dataclasses import dataclass

from aptjeeves.privacy.detectors import detect_sensitive_spans

# Reason categories only; matched text is never returned or stored.
REASON_GOVERNMENT_ID = "government_id"
REASON_BANK_OR_CARD = "bank_or_card_details"
REASON_BILL = "bill_or_invoice"
REASON_LEASE = "lease_or_rental_agreement"
REASON_RESIDENT_LISTING = "resident_listing"

_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_AADHAAR_NUMBER = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_AADHAAR_KEYWORDS = re.compile(r"(?i)\b(?:aadhaar|aadhar|uidai|passport\s*(?:no|number))\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_ACCOUNT = re.compile(r"(?i)\b(?:a/c|acc(?:ount)?)\s*(?:no\.?|number|#)?\s*[:\-]?\s*\d{9,18}\b")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[\s-]){3}\d{4}(?!\d)")

_BILL_MARKERS = (
    "amount due", "bill date", "due date", "consumer no", "consumer number",
    "invoice no", "invoice number", "bill no", "bill number", "meter reading",
    "amount payable", "total amount payable", "units consumed",
    "previous reading", "current reading", "tax invoice",
)
_LEASE_TITLES = (
    "rent agreement", "rental agreement", "lease agreement",
    "leave and license", "leave & license", "tenancy agreement",
)
_LEASE_TERMS = (
    "lessor", "lessee", "licensor", "licensee", "landlord", "tenant",
    "tenancy", "security deposit", "witnesseth",
)


@dataclass(frozen=True)
class SensitivityResult:
    """Outcome of the document-level privacy check."""

    is_sensitive: bool
    reason: str | None = None


def assess_sensitivity(text: str, *, flat_listing_threshold: int = 8) -> SensitivityResult:
    """Decide whether a document is too sensitive to extract from at all.

    Documents like bills, leases, ID proofs and resident listings are skipped
    entirely rather than redacted. This runs locally on text that is never
    persisted or sent to a provider.
    """

    lowered = text.casefold()

    if _PAN.search(text) or (_AADHAAR_KEYWORDS.search(text) and _AADHAAR_NUMBER.search(text)):
        return SensitivityResult(True, REASON_GOVERNMENT_ID)

    if _IFSC.search(text) or _ACCOUNT.search(text) or _has_card_number(text):
        return SensitivityResult(True, REASON_BANK_OR_CARD)

    if sum(1 for marker in _BILL_MARKERS if marker in lowered) >= 2:
        return SensitivityResult(True, REASON_BILL)

    head = lowered[:600]
    if any(title in head for title in _LEASE_TITLES) or (
        sum(1 for term in _LEASE_TERMS if term in lowered) >= 3
    ):
        return SensitivityResult(True, REASON_LEASE)

    flat_spans = sum(1 for span in detect_sensitive_spans(text) if span.kind == "FLAT")
    if flat_spans >= flat_listing_threshold:
        return SensitivityResult(True, REASON_RESIDENT_LISTING)

    return SensitivityResult(False)


def _has_card_number(text: str) -> bool:
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if _luhn_valid(digits):
            return True
    return False


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0

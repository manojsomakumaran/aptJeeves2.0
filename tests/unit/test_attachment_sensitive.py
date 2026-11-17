from __future__ import annotations

from aptjeeves.attachments.sensitive import (
    REASON_BANK_OR_CARD,
    REASON_BILL,
    REASON_GOVERNMENT_ID,
    REASON_LEASE,
    REASON_RESIDENT_LISTING,
    assess_sensitivity,
)

RATE_CARD = """Vendor rate card
Plumber Ramesh - 9876543210 - Rs 400 per visit
Electrician Suresh - 9123456780 - Rs 350 per visit
Carpenter Anil - 9988776655
"""

RULES = """Clubhouse rules
1. Bookings open 7 days in advance at the office.
2. Gym hours are 6am to 10pm. No outside guests after 9pm.
3. The pool is closed on Mondays for cleaning.
"""


def test_clean_documents_pass() -> None:
    assert not assess_sensitivity(RATE_CARD).is_sensitive
    assert not assess_sensitivity(RULES).is_sensitive


def test_pan_is_government_id() -> None:
    result = assess_sensitivity("Applicant PAN ABCDE1234F submitted")
    assert result.is_sensitive and result.reason == REASON_GOVERNMENT_ID


def test_aadhaar_needs_keyword_and_number() -> None:
    assert assess_sensitivity("Aadhaar number 1234 5678 9012").reason == REASON_GOVERNMENT_ID
    # A bare 12-digit number without context is not an ID.
    assert not assess_sensitivity("Ticket reference 1234 5678 9012 for the lift").is_sensitive


def test_bank_details_and_cards() -> None:
    assert assess_sensitivity("IFSC: HDFC0001234 branch").reason == REASON_BANK_OR_CARD
    assert assess_sensitivity("A/c No: 501001234567890").reason == REASON_BANK_OR_CARD
    assert assess_sensitivity("card 4111 1111 1111 1111 exp").reason == REASON_BANK_OR_CARD
    # Fails the Luhn check, so it is not treated as a card.
    assert not assess_sensitivity("code 1234 5678 9012 3456 for the gate").is_sensitive


def test_bills_need_two_markers() -> None:
    bill = "Electricity bill\nConsumer No: 4455\nBill date: 01/04\nAmount due: 1,250"
    assert assess_sensitivity(bill).reason == REASON_BILL
    assert not assess_sensitivity("Please pay the amount due at the office").is_sensitive


def test_lease_by_title_or_terms() -> None:
    assert assess_sensitivity("RENT AGREEMENT\nThis agreement is made between").reason == REASON_LEASE
    terms = "The landlord and the tenant agree on the security deposit and tenancy period."
    assert assess_sensitivity(terms).reason == REASON_LEASE
    assert not assess_sensitivity("Tenants must park in their own slot.").is_sensitive


def test_resident_listing_by_flat_count() -> None:
    listing = "\n".join(f"Flat A-{100 + i} dues pending" for i in range(10))
    assert assess_sensitivity(listing).reason == REASON_RESIDENT_LISTING
    assert not assess_sensitivity(listing, flat_listing_threshold=50).is_sensitive


def test_result_never_exposes_matched_text() -> None:
    result = assess_sensitivity("PAN ABCDE1234F")
    assert "ABCDE1234F" not in repr(result)

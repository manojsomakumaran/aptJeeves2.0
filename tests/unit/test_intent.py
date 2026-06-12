from __future__ import annotations

from aptjeeves.retrieval.intent import classify_intent


def test_plumber_query_classified_as_find_service_contact() -> None:
    result = classify_intent("Who is a good plumber?")
    assert result.intent == "find_service_contact"
    assert result.confidence >= 0.3
    assert "plumber" in result.matched_keywords


def test_electrician_contact_query() -> None:
    result = classify_intent("I need an electrician contact number")
    assert result.intent == "find_service_contact"
    assert "electrician" in result.matched_keywords
    assert "contact" in result.matched_keywords or "number" in result.matched_keywords


def test_gas_address_update_classified_as_process() -> None:
    result = classify_intent("How to update gas connection address?")
    assert result.intent == "ask_process_steps"
    assert "how to" in result.matched_keywords or "address update" in result.matched_keywords


def test_clubhouse_booking_classified_as_facility() -> None:
    result = classify_intent("What are the clubhouse booking timings?")
    assert result.intent == "ask_facility_info"
    assert "clubhouse" in result.matched_keywords


def test_pet_policy_classified_as_policy() -> None:
    result = classify_intent("Are pets allowed in the apartment?")
    assert result.intent == "ask_policy_or_rule"
    assert "pets" in result.matched_keywords or "allowed" in result.matched_keywords


def test_power_outage_classified_as_alert() -> None:
    result = classify_intent("Is there a power cut scheduled?")
    assert result.intent == "ask_alert_or_issue"
    assert "power cut" in result.matched_keywords


def test_generic_greeting_classified_as_unknown() -> None:
    result = classify_intent("Hello, thanks!")
    assert result.intent == "general_or_unknown"
    assert result.confidence == 0.1
    assert result.matched_keywords == []


def test_multiple_keyword_hits_increase_confidence() -> None:
    result = classify_intent("I need a plumber to repair the sink, can I get a contact number?")
    assert result.intent == "find_service_contact"
    assert result.confidence > 0.3
    assert len(result.matched_keywords) >= 3

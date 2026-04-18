from __future__ import annotations

from pathlib import Path

from aptjeeves.storage.db import apply_migrations, connect, utc_now_iso
from aptjeeves.storage.models import (
    FacilityInfoUpsert,
    FactEvidenceInput,
    ProcessInfoUpsert,
    RawMessageInsert,
    ServiceContactUpsert,
)
from aptjeeves.storage.repositories import CanonicalFactRepository, RawMessageRepository


def test_service_contact_upsert_merges_by_identity_key(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    raw_repo = RawMessageRepository(connection)
    fact_repo = CanonicalFactRepository(connection)
    msg1 = _insert_raw(raw_repo, message_id="msg_1", sent_at_utc="2026-04-16T10:00:00Z")
    msg2 = _insert_raw(raw_repo, message_id="msg_2", sent_at_utc="2026-04-17T10:00:00Z")

    first_fact_id = fact_repo.upsert_service_contact(
        _service_contact(first_seen=msg1.sent_at_utc, latest_seen=msg1.sent_at_utc),
        [_evidence(msg1)],
    )
    second_fact_id = fact_repo.upsert_service_contact(
        _service_contact(first_seen=msg1.sent_at_utc, latest_seen=msg2.sent_at_utc, confidence=0.9),
        [_evidence(msg1), _evidence(msg2)],
    )

    assert first_fact_id == second_fact_id
    fact = fact_repo.get_fact(first_fact_id)
    assert fact is not None
    assert fact["source_count"] == 2
    assert fact["confidence"] == 0.9
    assert fact["first_seen"] == "2026-04-16T10:00:00Z"
    assert fact["latest_seen"] == "2026-04-17T10:00:00Z"
    assert len(fact_repo.list_facts()) == 1
    assert len(fact_repo.list_evidence(first_fact_id)) == 2


def test_duplicate_evidence_does_not_increment_source_count(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    raw_repo = RawMessageRepository(connection)
    fact_repo = CanonicalFactRepository(connection)
    msg = _insert_raw(raw_repo, message_id="msg_1", sent_at_utc="2026-04-16T10:00:00Z")

    fact_id = fact_repo.upsert_service_contact(
        _service_contact(first_seen=msg.sent_at_utc, latest_seen=msg.sent_at_utc),
        [_evidence(msg)],
    )
    fact_repo.upsert_service_contact(
        _service_contact(first_seen=msg.sent_at_utc, latest_seen=msg.sent_at_utc),
        [_evidence(msg)],
    )

    fact = fact_repo.get_fact(fact_id)
    assert fact is not None
    assert fact["source_count"] == 1
    assert len(fact_repo.list_evidence(fact_id)) == 1


def test_process_and_facility_facts_can_be_upserted(tmp_path: Path) -> None:
    connection = connect(tmp_path / "aptjeeves.sqlite3")
    apply_migrations(connection)
    raw_repo = RawMessageRepository(connection)
    fact_repo = CanonicalFactRepository(connection)
    msg = _insert_raw(raw_repo, message_id="msg_1", sent_at_utc="2026-04-16T10:00:00Z")

    process_id = fact_repo.upsert_process_info(_process_info(msg.sent_at_utc), [_evidence(msg)])
    facility_id = fact_repo.upsert_facility_info(_facility_info(msg.sent_at_utc), [_evidence(msg)])

    assert fact_repo.get_fact(process_id)["fact_type"] == "process_info"
    assert fact_repo.get_fact(facility_id)["fact_type"] == "facility_info"
    assert len(fact_repo.list_facts()) == 2


def _insert_raw(
    raw_repo: RawMessageRepository,
    *,
    message_id: str,
    sent_at_utc: str,
) -> RawMessageInsert:
    message = RawMessageInsert(
        message_id=message_id,
        message_fingerprint=f"fingerprint_{message_id}",
        import_batch_id="import_test",
        platform="whatsapp",
        source_conversation_id="conversation_1",
        chat_name="Apartment Main",
        source_message_id=None,
        sender_hash=f"sender_{message_id}",
        sender_display_hint="Resident",
        sent_at_utc=sent_at_utc,
        source_timezone="Asia/Kolkata",
        normalized_text_hash=f"text_hash_{message_id}",
        sanitized_text="Call PHONE_1 for plumbing.",
        raw_text_debug_ref=None,
        source_file="chat.txt",
        source_offset=1,
        source_line_start=1,
        source_line_end=1,
        processing_status="new",
        first_seen_at=utc_now_iso(),
        processed_at=None,
        parser_version="test_parser",
        normalizer_version="test_normalizer",
        redactor_version="test_redactor",
    )
    connection = raw_repo.connection
    connection.execute(
        """
        INSERT OR IGNORE INTO import_runs (
          import_batch_id, source_platform, source_file, source_file_hash,
          chat_name, started_at, status, parser_version, normalizer_version,
          redactor_version
        )
        VALUES ('import_test', 'whatsapp', 'chat.txt', 'hash', 'Apartment Main',
                ?, 'running', 'test_parser', 'test_normalizer', 'test_redactor')
        """,
        (utc_now_iso(),),
    )
    raw_repo.insert_if_new(message)
    return message


def _evidence(message: RawMessageInsert) -> FactEvidenceInput:
    return FactEvidenceInput(
        message_id=message.message_id,
        message_fingerprint=message.message_fingerprint,
        sanitized_snippet=message.sanitized_text,
        evidence_type="mention",
        confidence=0.8,
    )


def _service_contact(
    *,
    first_seen: str,
    latest_seen: str,
    confidence: float = 0.8,
) -> ServiceContactUpsert:
    return ServiceContactUpsert(
        fact_identity_key="service_contact|plumber|phone_hash_1",
        title="Plumber contact",
        summary="Residents mentioned a plumber.",
        privacy_status="needs_review",
        confidence=confidence,
        first_seen=first_seen,
        latest_seen=latest_seen,
        extractor_prompt_version="test_prompt",
        llm_model_version="fake",
        service_type="plumber",
        display_name="Ramesh",
        normalized_name="ramesh",
        contact_methods=[{"type": "phone", "value_placeholder": "PHONE_1"}],
        contact_method_hashes=["phone_hash_1"],
        contact_classification="vendor_or_service_contact",
        is_resident_affiliated=False,
        resident_affiliation_reason=None,
        area_or_scope=None,
        price_hint=None,
        availability_hint=None,
        caveats=None,
    )


def _process_info(seen_at: str) -> ProcessInfoUpsert:
    return ProcessInfoUpsert(
        fact_identity_key="process_info|gas-address-update",
        title="Gas address update",
        summary="Residents discussed gas address update steps.",
        privacy_status="public_to_residents",
        confidence=0.7,
        first_seen=seen_at,
        latest_seen=seen_at,
        extractor_prompt_version="test_prompt",
        llm_model_version="fake",
        process_name="Gas address update",
        category="utilities",
        provider_or_authority="Gas provider",
        steps=["Submit address proof"],
        required_documents=["Address proof"],
        fees=[],
        locations_or_portals=[],
        deadlines=[],
        caveats="Community-discussed information only.",
        staleness_risk="high",
        official_verification_status="not_verified",
    )


def _facility_info(seen_at: str) -> FacilityInfoUpsert:
    return FacilityInfoUpsert(
        fact_identity_key="facility_info|clubhouse|booking",
        title="Clubhouse booking",
        summary="Residents discussed clubhouse booking.",
        privacy_status="public_to_residents",
        confidence=0.7,
        first_seen=seen_at,
        latest_seen=seen_at,
        extractor_prompt_version="test_prompt",
        llm_model_version="fake",
        facility_name="Clubhouse",
        info_type="booking_process",
        location_hint=None,
        availability=None,
        rules_or_steps=["Contact facility office"],
        caveats=None,
    )

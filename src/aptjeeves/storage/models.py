from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RawMessageInsert:
    """All fields required to insert a normalized raw message ledger row."""

    message_id: str
    message_fingerprint: str
    import_batch_id: str
    platform: str
    source_conversation_id: str
    chat_name: str | None
    source_message_id: str | None
    sender_hash: str
    sender_display_hint: str | None
    sent_at_utc: str
    source_timezone: str | None
    normalized_text_hash: str
    sanitized_text: str
    raw_text_debug_ref: str | None
    source_file: str
    source_offset: int | None
    source_line_start: int | None
    source_line_end: int | None
    processing_status: str
    first_seen_at: str
    processed_at: str | None
    parser_version: str
    normalizer_version: str
    redactor_version: str
    # Attachment-derived segments reuse this ledger; chat rows keep the defaults.
    source_kind: str = "chat"
    parent_message_id: str | None = None
    attachment_id: str | None = None
    segment_label: str | None = None


@dataclass(frozen=True)
class ImportSummary:
    """Compact import result returned by the service and CLI."""

    import_batch_id: str
    status: str
    chat_name: str | None
    total_messages_seen: int
    new_messages_inserted: int
    duplicate_messages_skipped: int
    parse_failures: int


@dataclass(frozen=True)
class QuerySummary:
    """Compact query status returned by the service and CLI."""

    query_id: str
    status: str
    query_text_redacted: str
    query_intent: str | None
    final_action: str | None
    retrieval_trace_id: str | None
    guardrail_events_count: int
    created_at: str
    completed_at: str | None


@dataclass(frozen=True)
class FactEvidenceInput:
    """Evidence linking a canonical fact to one source message."""

    message_id: str
    message_fingerprint: str
    sanitized_snippet: str
    evidence_type: str
    confidence: float


@dataclass(frozen=True)
class ServiceContactUpsert:
    """Canonical service-contact fact and subtype details."""

    fact_identity_key: str
    title: str
    summary: str
    privacy_status: str
    confidence: float
    first_seen: str
    latest_seen: str
    extractor_prompt_version: str | None
    llm_model_version: str | None
    service_type: str
    display_name: str | None
    normalized_name: str | None
    contact_methods: list[dict[str, Any]]
    contact_method_hashes: list[str]
    contact_classification: str
    is_resident_affiliated: bool
    resident_affiliation_reason: str | None
    area_or_scope: str | None
    price_hint: str | None
    availability_hint: str | None
    caveats: str | None


@dataclass(frozen=True)
class ProcessInfoUpsert:
    """Canonical process-info fact and subtype details."""

    fact_identity_key: str
    title: str
    summary: str
    privacy_status: str
    confidence: float
    first_seen: str
    latest_seen: str
    extractor_prompt_version: str | None
    llm_model_version: str | None
    process_name: str
    category: str | None
    provider_or_authority: str | None
    steps: list[str]
    required_documents: list[str]
    fees: list[str]
    locations_or_portals: list[str]
    deadlines: list[str]
    caveats: str | None
    staleness_risk: str
    official_verification_status: str


@dataclass(frozen=True)
class FacilityInfoUpsert:
    """Canonical facility-info fact and subtype details."""

    fact_identity_key: str
    title: str
    summary: str
    privacy_status: str
    confidence: float
    first_seen: str
    latest_seen: str
    extractor_prompt_version: str | None
    llm_model_version: str | None
    facility_name: str
    info_type: str
    location_hint: str | None
    availability: str | None
    rules_or_steps: list[str]
    caveats: str | None


@dataclass(frozen=True)
class VectorEntryUpsert:
    """Vector index row for one canonical fact version."""

    fact_id: str
    fact_type: str
    fact_version: int
    embedding_text: str
    embedding_hash: str
    embedding_model_version: str
    embedding_json: str
    vector_store_ref: str | None


@dataclass(frozen=True)
class ExtractionSummary:
    """Result returned by ExtractionService after processing a batch of messages."""

    fact_ids: list[str]
    extraction_failures: int
    total_pending_before: int = 0
    remaining_pending: int = 0
    estimated_batches_remaining: int = 0
    limit_applied: int = 0


@dataclass(frozen=True)
class IndexSummary:
    """Result returned by VectorIndexingService after processing a batch of facts."""

    vector_ids: list[str]
    total_pending_before: int = 0
    remaining_pending: int = 0
    estimated_batches_remaining: int = 0
    limit_applied: int = 0

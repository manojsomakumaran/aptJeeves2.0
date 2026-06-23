﻿from __future__ import annotations

import sqlite3
import logging
import math
import uuid
from collections import defaultdict
from typing import Any

from aptjeeves.extraction.schemas import ExtractedFact, Extractor, MessageForExtraction
from aptjeeves.extraction.validator import validate_extraction_payload
from aptjeeves.ingestion.hashing import sha256_text
from aptjeeves.observability.events import ObservabilityService
from aptjeeves.storage.models import (
    ExtractionSummary,
    FacilityInfoUpsert,
    FactEvidenceInput,
    ProcessInfoUpsert,
    ServiceContactUpsert,
)
from aptjeeves.storage.repositories import CanonicalFactRepository, ImportRunRepository, RawMessageRepository
logger = logging.getLogger(__name__)


class ExtractionService:
    """Validates extracted facts and upserts them into canonical storage."""

    def __init__(self, connection: sqlite3.Connection, extractor: Extractor) -> None:
        """Create an extraction service using a fake or LLM-backed extractor."""

        self.connection = connection
        self.extractor = extractor
        self.import_runs = ImportRunRepository(connection)
        self.raw_messages = RawMessageRepository(connection)
        self.facts = CanonicalFactRepository(connection)
        self.events = ObservabilityService(connection)

    def extract_rows(self, rows: list[sqlite3.Row]) -> ExtractionSummary:
        """Extract facts from raw message rows and return an ExtractionSummary.

        If the extractor or validator raises, all messages in the batch are
        counted as extraction failures and the error is surfaced as a pipeline
        event rather than crashing the caller.
        """

        if not rows:
            return ExtractionSummary(fact_ids=[], extraction_failures=0)

        logger.info(f"Extracting facts for a batch of {len(rows)} messages")
        trace_id = f"trace_{uuid.uuid4().hex}"
        messages = [_message_for_extraction(row) for row in rows]
        allowed_ids = {message.message_id for message in messages}

        try:
            import inspect
            sig = inspect.signature(self.extractor.extract)
            if "trace_id" in sig.parameters:
                payload = self.extractor.extract(messages, trace_id=trace_id)
            else:
                payload = self.extractor.extract(messages)
            result = validate_extraction_payload(payload, allowed_message_ids=allowed_ids)
        except Exception as exc:
            logger.error(f"Extraction batch failed: {exc}", exc_info=True)
            self.events.emit(
                trace_id=trace_id,
                event_type="extraction_batch_failed",
                stage="extraction",
                severity="error",
                payload={
                    "message_count": len(rows),
                    "error": str(exc),
                    "extractor_prompt_version": self.extractor.prompt_version,
                    "llm_model_version": self.extractor.model_version,
                },
            )
            with self.connection:
                for row in rows:
                    self.raw_messages.mark_processing_status(row["message_id"], "failed")
            return ExtractionSummary(fact_ids=[], extraction_failures=len(rows))

        rows_by_id = {row["message_id"]: row for row in rows}
        fact_ids: list[str] = []
        referenced_message_ids: set[str] = set()

        with self.connection:
            for extracted in result.facts:
                evidence = _evidence_for_fact(extracted, rows_by_id)
                referenced_message_ids.update(item.message_id for item in evidence)
                fact_id = self._upsert_fact(extracted, evidence, rows_by_id)
                logger.debug(f"Upserted canonical fact {fact_id} of type {extracted.fact_type}")
                fact_ids.append(fact_id)
                self.events.emit(
                    trace_id=trace_id,
                    event_type="canonical_fact_upserted",
                    stage="extraction",
                    fact_id=fact_id,
                    payload={
                        "fact_type": extracted.fact_type,
                        "source_message_ids": extracted.source_message_ids,
                        "extractor_prompt_version": self.extractor.prompt_version,
                        "llm_model_version": self.extractor.model_version,
                    },
                )

            for row in rows:
                status = (
                    "extracted"
                    if row["message_id"] in referenced_message_ids
                    else "no_extractable_info"
                )
                self.raw_messages.mark_processing_status(row["message_id"], status)

        return ExtractionSummary(fact_ids=fact_ids, extraction_failures=0)

    def extract_pending(self, *, limit: int = 100) -> ExtractionSummary:
        """Extract facts from raw messages still marked as `new`.

        Messages are grouped by import_batch_id so extraction failures can be
        attributed back to the correct import run record.
        """

        total_pending = self.raw_messages.count_by_processing_status("new")
        all_rows = self.raw_messages.list_by_processing_status("new", limit=limit)
        processed_count = len(all_rows)
        remaining_pending = max(0, total_pending - processed_count)
        estimated_batches_remaining = math.ceil(remaining_pending / limit) if limit > 0 else 0

        logger.info(f"Extracting pending messages with limit {limit}. Found {processed_count} new messages out of {total_pending} total pending.")
        if not all_rows:
            return ExtractionSummary(
                fact_ids=[],
                extraction_failures=0,
                total_pending_before=total_pending,
                remaining_pending=remaining_pending,
                estimated_batches_remaining=estimated_batches_remaining,
                limit_applied=limit,
            )

        by_batch: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in all_rows:
            by_batch[row["import_batch_id"]].append(row)

        all_fact_ids: list[str] = []
        total_failures = 0

        for batch_id, batch_rows in by_batch.items():
            batch_failures = 0
            for chunk_rows in _chunk_rows(batch_rows, chunk_size=25, overlap=5):
                summary = self.extract_rows(chunk_rows)
                all_fact_ids.extend(summary.fact_ids)
                batch_failures += summary.extraction_failures
                total_failures += summary.extraction_failures
            if batch_failures > 0:
                with self.connection:
                    self.import_runs.increment_extraction_failures(
                        batch_id, batch_failures
                    )

        return ExtractionSummary(
            fact_ids=all_fact_ids,
            extraction_failures=total_failures,
            total_pending_before=total_pending,
            remaining_pending=remaining_pending,
            estimated_batches_remaining=estimated_batches_remaining,
            limit_applied=limit,
        )

    def _upsert_fact(
        self,
        extracted: ExtractedFact,
        evidence: list[FactEvidenceInput],
        rows_by_id: dict[str, sqlite3.Row],
    ) -> str:
        """Dispatch a validated extracted fact to the right repository upsert."""

        first_seen, latest_seen = _seen_window(extracted.source_message_ids, rows_by_id)
        if extracted.fact_type == "service_contact":
            return self.facts.upsert_service_contact(
                _service_contact_upsert(
                    extracted,
                    first_seen=first_seen,
                    latest_seen=latest_seen,
                    prompt_version=self.extractor.prompt_version,
                    model_version=self.extractor.model_version,
                ),
                evidence,
            )
        if extracted.fact_type == "process_info":
            return self.facts.upsert_process_info(
                _process_info_upsert(
                    extracted,
                    first_seen=first_seen,
                    latest_seen=latest_seen,
                    prompt_version=self.extractor.prompt_version,
                    model_version=self.extractor.model_version,
                ),
                evidence,
            )
        if extracted.fact_type == "facility_info":
            return self.facts.upsert_facility_info(
                _facility_info_upsert(
                    extracted,
                    first_seen=first_seen,
                    latest_seen=latest_seen,
                    prompt_version=self.extractor.prompt_version,
                    model_version=self.extractor.model_version,
                ),
                evidence,
            )
        raise ValueError(f"Unsupported extracted fact type: {extracted.fact_type}")


def _message_for_extraction(row: sqlite3.Row) -> MessageForExtraction:
    """Convert a raw_messages row into the extractor input contract."""

    return MessageForExtraction(
        message_id=row["message_id"],
        message_fingerprint=row["message_fingerprint"],
        sent_at_utc=row["sent_at_utc"],
        sender_hash=row["sender_hash"],
        sanitized_text=row["sanitized_text"],
    )


def _evidence_for_fact(
    extracted: ExtractedFact,
    rows_by_id: dict[str, sqlite3.Row],
) -> list[FactEvidenceInput]:
    """Build fact_evidence inputs from validated source_message_ids."""

    evidence: list[FactEvidenceInput] = []
    for message_id in extracted.source_message_ids:
        row = rows_by_id[message_id]
        evidence.append(
            FactEvidenceInput(
                message_id=message_id,
                message_fingerprint=row["message_fingerprint"],
                sanitized_snippet=_snippet_for_message(extracted, message_id, row),
                evidence_type="mention",
                confidence=extracted.confidence,
            )
        )
    return evidence


def _snippet_for_message(
    extracted: ExtractedFact,
    message_id: str,
    row: sqlite3.Row,
) -> str:
    """Choose a sanitized snippet for one evidence row."""

    if len(extracted.source_message_ids) == 1 and extracted.sanitized_snippets:
        return extracted.sanitized_snippets[0]
    return row["sanitized_text"]


def _seen_window(
    source_message_ids: list[str],
    rows_by_id: dict[str, sqlite3.Row],
) -> tuple[str, str]:
    """Return earliest/latest source timestamps for a fact."""

    timestamps = [rows_by_id[message_id]["sent_at_utc"] for message_id in source_message_ids]
    return min(timestamps), max(timestamps)


def _service_contact_upsert(
    extracted: ExtractedFact,
    *,
    first_seen: str,
    latest_seen: str,
    prompt_version: str,
    model_version: str,
) -> ServiceContactUpsert:
    details = extracted.details
    service_type = _string(details, "service_type", "unknown_service")
    display_name = _optional_string(details, "display_name")
    contact_methods = _list_of_dicts(details.get("contact_methods"))
    contact_hashes = [
        sha256_text(
            "|".join(
                [
                    _string(method, "type", "unknown"),
                    _string(method, "value_hash", _string(method, "value_placeholder", "")),
                ]
            )
        )
        for method in contact_methods
    ]
    return ServiceContactUpsert(
        fact_identity_key=_identity_key("service_contact", service_type, display_name, contact_hashes),
        title=extracted.title,
        summary=extracted.summary,
        privacy_status=extracted.privacy_status_hint,
        confidence=extracted.confidence,
        first_seen=first_seen,
        latest_seen=latest_seen,
        extractor_prompt_version=prompt_version,
        llm_model_version=model_version,
        service_type=service_type,
        display_name=display_name,
        normalized_name=display_name.casefold() if display_name else None,
        contact_methods=contact_methods,
        contact_method_hashes=contact_hashes,
        contact_classification=_string(details, "contact_classification", "unknown_contact"),
        is_resident_affiliated=bool(details.get("is_resident_affiliated", False)),
        resident_affiliation_reason=_optional_string(details, "resident_affiliation_reason"),
        area_or_scope=_optional_string(details, "area_or_scope"),
        price_hint=_optional_string(details, "price_hint"),
        availability_hint=_optional_string(details, "availability_hint"),
        caveats=_optional_string(details, "caveats"),
    )


def _process_info_upsert(
    extracted: ExtractedFact,
    *,
    first_seen: str,
    latest_seen: str,
    prompt_version: str,
    model_version: str,
) -> ProcessInfoUpsert:
    details = extracted.details
    process_name = _string(details, "process_name", extracted.title)
    provider = _optional_string(details, "provider_or_authority")
    return ProcessInfoUpsert(
        fact_identity_key=_identity_key("process_info", process_name, provider),
        title=extracted.title,
        summary=extracted.summary,
        privacy_status=extracted.privacy_status_hint,
        confidence=extracted.confidence,
        first_seen=first_seen,
        latest_seen=latest_seen,
        extractor_prompt_version=prompt_version,
        llm_model_version=model_version,
        process_name=process_name,
        category=_optional_string(details, "category"),
        provider_or_authority=provider,
        steps=_list_of_strings(details.get("steps")),
        required_documents=_list_of_strings(details.get("required_documents")),
        fees=_list_of_strings(details.get("fees")),
        locations_or_portals=_list_of_strings(details.get("locations_or_portals")),
        deadlines=_list_of_strings(details.get("deadlines")),
        caveats=_optional_string(details, "caveats"),
        staleness_risk=_string(details, "staleness_risk", "medium"),
        official_verification_status=_string(details, "official_verification_status", "not_verified"),
    )


def _facility_info_upsert(
    extracted: ExtractedFact,
    *,
    first_seen: str,
    latest_seen: str,
    prompt_version: str,
    model_version: str,
) -> FacilityInfoUpsert:
    details = extracted.details
    facility_name = _string(details, "facility_name", extracted.title)
    info_type = _string(details, "info_type", "general")
    return FacilityInfoUpsert(
        fact_identity_key=_identity_key("facility_info", facility_name, info_type),
        title=extracted.title,
        summary=extracted.summary,
        privacy_status=extracted.privacy_status_hint,
        confidence=extracted.confidence,
        first_seen=first_seen,
        latest_seen=latest_seen,
        extractor_prompt_version=prompt_version,
        llm_model_version=model_version,
        facility_name=facility_name,
        info_type=info_type,
        location_hint=_optional_string(details, "location_hint"),
        availability=_optional_string(details, "availability"),
        rules_or_steps=_list_of_strings(details.get("rules_or_steps")),
        caveats=_optional_string(details, "caveats"),
    )


def _identity_key(*parts: object) -> str:
    """Build a stable app-computed fact identity key."""

    canonical = "|".join(str(part or "").strip().casefold() for part in parts)
    return sha256_text(canonical)


def _string(source: dict[str, Any], key: str, default: str) -> str:
    """Read a string field from details with a default."""

    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _optional_string(source: dict[str, Any], key: str) -> str | None:
    """Read an optional string field from details."""

    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _list_of_strings(value: object) -> list[str]:
    """Normalize a detail field into a string list."""

    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    """Normalize a detail field into a dictionary list."""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _chunk_rows(rows: list[sqlite3.Row], *, chunk_size: int, overlap: int = 0) -> list[list[sqlite3.Row]]:
    """Split a row list into smaller overlapping extractor batches."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and less than chunk_size")

    chunks = []
    step = chunk_size - overlap
    for index in range(0, len(rows), step):
        chunks.append(rows[index:index + chunk_size])
        if index + chunk_size >= len(rows):
            break
    return chunks

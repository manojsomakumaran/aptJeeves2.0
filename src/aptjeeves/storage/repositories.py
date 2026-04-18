from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
import uuid

from aptjeeves.storage.db import utc_now_iso
from aptjeeves.storage.models import (
    FacilityInfoUpsert,
    FactEvidenceInput,
    ImportSummary,
    ProcessInfoUpsert,
    RawMessageInsert,
    ServiceContactUpsert,
)


class ImportRunRepository:
    """Persistence operations for import_runs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create a repository bound to a SQLite connection."""

        self.connection = connection

    def create(
        self,
        *,
        import_batch_id: str,
        source_platform: str,
        source_file: str,
        source_file_hash: str,
        chat_name: str | None,
        parser_version: str,
        normalizer_version: str,
        redactor_version: str,
    ) -> None:
        """Create a running import record before parsing starts."""

        self.connection.execute(
            """
            INSERT INTO import_runs (
              import_batch_id, source_platform, source_file, source_file_hash,
              chat_name, started_at, status, parser_version, normalizer_version,
              redactor_version
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            (
                import_batch_id,
                source_platform,
                source_file,
                source_file_hash,
                chat_name,
                utc_now_iso(),
                parser_version,
                normalizer_version,
                redactor_version,
            ),
        )

    def complete(
        self,
        *,
        import_batch_id: str,
        status: str,
        total_messages_seen: int,
        new_messages_inserted: int,
        duplicate_messages_skipped: int,
        parse_failures: int,
        notes: str | None = None,
    ) -> None:
        """Mark an import as finished and store final counters."""

        self.connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?,
                status = ?,
                total_messages_seen = ?,
                new_messages_inserted = ?,
                duplicate_messages_skipped = ?,
                parse_failures = ?,
                notes = ?
            WHERE import_batch_id = ?
            """,
            (
                utc_now_iso(),
                status,
                total_messages_seen,
                new_messages_inserted,
                duplicate_messages_skipped,
                parse_failures,
                notes,
                import_batch_id,
            ),
        )

    def get_summary(self, import_batch_id: str) -> ImportSummary | None:
        """Return the user-facing import summary, or None if it is unknown."""

        row = self.connection.execute(
            """
            SELECT import_batch_id, status, chat_name, total_messages_seen, new_messages_inserted,
                   duplicate_messages_skipped, parse_failures
            FROM import_runs
            WHERE import_batch_id = ?
            """,
            (import_batch_id,),
        ).fetchone()
        if row is None:
            return None
        return ImportSummary(
            import_batch_id=row["import_batch_id"],
            status=row["status"],
            chat_name=row["chat_name"],
            total_messages_seen=row["total_messages_seen"],
            new_messages_inserted=row["new_messages_inserted"],
            duplicate_messages_skipped=row["duplicate_messages_skipped"],
            parse_failures=row["parse_failures"],
        )


class RawMessageRepository:
    """Persistence operations for the raw message idempotency ledger."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create a repository bound to a SQLite connection."""

        self.connection = connection

    def insert_if_new(self, message: RawMessageInsert) -> bool:
        """Insert a message and return true only when it was not a duplicate."""

        values = asdict(message)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        # The UNIQUE(message_fingerprint) constraint is the source of truth for
        # dedupe. INSERT OR IGNORE avoids races and keeps duplicate imports cheap.
        cursor = self.connection.execute(
            f"INSERT OR IGNORE INTO raw_messages ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        return cursor.rowcount == 1

    def count(self) -> int:
        """Return the number of unique raw messages stored."""

        row = self.connection.execute("SELECT COUNT(*) AS count FROM raw_messages").fetchone()
        return int(row["count"])

    def list_all(self) -> list[sqlite3.Row]:
        """Return raw messages in conversation-time order for diagnostics/tests."""

        return self.connection.execute(
            "SELECT * FROM raw_messages ORDER BY sent_at_utc, source_offset"
        ).fetchall()

    def get_by_ids(self, message_ids: list[str]) -> dict[str, sqlite3.Row]:
        """Return raw messages keyed by message_id."""

        if not message_ids:
            return {}
        placeholders = ", ".join("?" for _ in message_ids)
        rows = self.connection.execute(
            f"SELECT * FROM raw_messages WHERE message_id IN ({placeholders})",
            tuple(message_ids),
        ).fetchall()
        return {row["message_id"]: row for row in rows}

    def list_by_processing_status(self, status: str, *, limit: int = 100) -> list[sqlite3.Row]:
        """Return raw messages waiting at a specific processing stage."""

        return self.connection.execute(
            """
            SELECT * FROM raw_messages
            WHERE processing_status = ?
            ORDER BY sent_at_utc, source_offset
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()

    def mark_processing_status(self, message_id: str, status: str) -> None:
        """Update one raw message processing status."""

        self.connection.execute(
            """
            UPDATE raw_messages
            SET processing_status = ?, processed_at = ?
            WHERE message_id = ?
            """,
            (status, utc_now_iso(), message_id),
        )


class CanonicalFactRepository:
    """Persistence and merge operations for canonical facts and evidence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create a repository bound to a SQLite connection."""

        self.connection = connection

    def upsert_service_contact(
        self,
        fact: ServiceContactUpsert,
        evidence: list[FactEvidenceInput],
    ) -> str:
        """Insert or merge a service-contact fact and its source evidence."""

        fact_id = self._upsert_canonical_fact("service_contact", fact)
        self.connection.execute(
            """
            INSERT INTO service_contacts (
              fact_id, service_type, display_name, normalized_name,
              contact_methods_json, contact_method_hashes_json,
              contact_classification, is_resident_affiliated,
              resident_affiliation_reason, area_or_scope, price_hint,
              availability_hint, caveats
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
              service_type = excluded.service_type,
              display_name = excluded.display_name,
              normalized_name = excluded.normalized_name,
              contact_methods_json = excluded.contact_methods_json,
              contact_method_hashes_json = excluded.contact_method_hashes_json,
              contact_classification = excluded.contact_classification,
              is_resident_affiliated = excluded.is_resident_affiliated,
              resident_affiliation_reason = excluded.resident_affiliation_reason,
              area_or_scope = excluded.area_or_scope,
              price_hint = excluded.price_hint,
              availability_hint = excluded.availability_hint,
              caveats = excluded.caveats
            """,
            (
                fact_id,
                fact.service_type,
                fact.display_name,
                fact.normalized_name,
                _json(fact.contact_methods),
                _json(fact.contact_method_hashes),
                fact.contact_classification,
                int(fact.is_resident_affiliated),
                fact.resident_affiliation_reason,
                fact.area_or_scope,
                fact.price_hint,
                fact.availability_hint,
                fact.caveats,
            ),
        )
        self._insert_evidence(fact_id, evidence)
        self._refresh_source_count(fact_id)
        return fact_id

    def upsert_process_info(
        self,
        fact: ProcessInfoUpsert,
        evidence: list[FactEvidenceInput],
    ) -> str:
        """Insert or merge a process-info fact and its source evidence."""

        fact_id = self._upsert_canonical_fact("process_info", fact)
        self.connection.execute(
            """
            INSERT INTO process_info (
              fact_id, process_name, category, provider_or_authority, steps_json,
              required_documents_json, fees_json, locations_or_portals_json,
              deadlines_json, caveats, staleness_risk, official_verification_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
              process_name = excluded.process_name,
              category = excluded.category,
              provider_or_authority = excluded.provider_or_authority,
              steps_json = excluded.steps_json,
              required_documents_json = excluded.required_documents_json,
              fees_json = excluded.fees_json,
              locations_or_portals_json = excluded.locations_or_portals_json,
              deadlines_json = excluded.deadlines_json,
              caveats = excluded.caveats,
              staleness_risk = excluded.staleness_risk,
              official_verification_status = excluded.official_verification_status
            """,
            (
                fact_id,
                fact.process_name,
                fact.category,
                fact.provider_or_authority,
                _json(fact.steps),
                _json(fact.required_documents),
                _json(fact.fees),
                _json(fact.locations_or_portals),
                _json(fact.deadlines),
                fact.caveats,
                fact.staleness_risk,
                fact.official_verification_status,
            ),
        )
        self._insert_evidence(fact_id, evidence)
        self._refresh_source_count(fact_id)
        return fact_id

    def upsert_facility_info(
        self,
        fact: FacilityInfoUpsert,
        evidence: list[FactEvidenceInput],
    ) -> str:
        """Insert or merge a facility-info fact and its source evidence."""

        fact_id = self._upsert_canonical_fact("facility_info", fact)
        self.connection.execute(
            """
            INSERT INTO facility_info (
              fact_id, facility_name, info_type, location_hint,
              availability, rules_or_steps_json, caveats
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
              facility_name = excluded.facility_name,
              info_type = excluded.info_type,
              location_hint = excluded.location_hint,
              availability = excluded.availability,
              rules_or_steps_json = excluded.rules_or_steps_json,
              caveats = excluded.caveats
            """,
            (
                fact_id,
                fact.facility_name,
                fact.info_type,
                fact.location_hint,
                fact.availability,
                _json(fact.rules_or_steps),
                fact.caveats,
            ),
        )
        self._insert_evidence(fact_id, evidence)
        self._refresh_source_count(fact_id)
        return fact_id

    def get_fact_by_identity_key(self, fact_identity_key: str) -> sqlite3.Row | None:
        """Return one canonical fact by stable identity key."""

        return self.connection.execute(
            "SELECT * FROM canonical_facts WHERE fact_identity_key = ?",
            (fact_identity_key,),
        ).fetchone()

    def get_fact(self, fact_id: str) -> sqlite3.Row | None:
        """Return one canonical fact by ID."""

        return self.connection.execute(
            "SELECT * FROM canonical_facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()

    def list_facts(self) -> list[sqlite3.Row]:
        """Return canonical facts in creation order."""

        return self.connection.execute(
            "SELECT * FROM canonical_facts ORDER BY created_at, fact_id"
        ).fetchall()

    def list_evidence(self, fact_id: str) -> list[sqlite3.Row]:
        """Return all evidence rows for one fact."""

        return self.connection.execute(
            "SELECT * FROM fact_evidence WHERE fact_id = ? ORDER BY created_at, evidence_id",
            (fact_id,),
        ).fetchall()

    def _upsert_canonical_fact(self, fact_type: str, fact: object) -> str:
        """Insert or merge the shared canonical_facts row."""

        existing = self.get_fact_by_identity_key(fact.fact_identity_key)  # type: ignore[attr-defined]
        now = utc_now_iso()
        if existing is None:
            fact_id = f"fact_{uuid.uuid4().hex}"
            self.connection.execute(
                """
                INSERT INTO canonical_facts (
                  fact_id, fact_type, fact_identity_key, title, summary,
                  privacy_status, confidence, source_count, first_seen,
                  latest_seen, created_at, updated_at, fact_version,
                  extractor_prompt_version, llm_model_version, merge_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 1, ?, ?, 'active')
                """,
                (
                    fact_id,
                    fact_type,
                    fact.fact_identity_key,  # type: ignore[attr-defined]
                    fact.title,  # type: ignore[attr-defined]
                    fact.summary,  # type: ignore[attr-defined]
                    fact.privacy_status,  # type: ignore[attr-defined]
                    fact.confidence,  # type: ignore[attr-defined]
                    fact.first_seen,  # type: ignore[attr-defined]
                    fact.latest_seen,  # type: ignore[attr-defined]
                    now,
                    now,
                    fact.extractor_prompt_version,  # type: ignore[attr-defined]
                    fact.llm_model_version,  # type: ignore[attr-defined]
                ),
            )
            return fact_id

        fact_id = existing["fact_id"]
        # Merge conservatively: keep earliest first_seen, latest latest_seen,
        # highest confidence, and bump fact_version when fact text/details change.
        text_changed = existing["title"] != fact.title or existing["summary"] != fact.summary  # type: ignore[attr-defined]
        self.connection.execute(
            """
            UPDATE canonical_facts
            SET title = ?,
                summary = ?,
                privacy_status = ?,
                confidence = MAX(confidence, ?),
                first_seen = MIN(first_seen, ?),
                latest_seen = MAX(latest_seen, ?),
                updated_at = ?,
                fact_version = fact_version + ?,
                extractor_prompt_version = COALESCE(?, extractor_prompt_version),
                llm_model_version = COALESCE(?, llm_model_version)
            WHERE fact_id = ?
            """,
            (
                fact.title,  # type: ignore[attr-defined]
                fact.summary,  # type: ignore[attr-defined]
                fact.privacy_status,  # type: ignore[attr-defined]
                fact.confidence,  # type: ignore[attr-defined]
                fact.first_seen,  # type: ignore[attr-defined]
                fact.latest_seen,  # type: ignore[attr-defined]
                now,
                1 if text_changed else 0,
                fact.extractor_prompt_version,  # type: ignore[attr-defined]
                fact.llm_model_version,  # type: ignore[attr-defined]
                fact_id,
            ),
        )
        return str(fact_id)

    def _insert_evidence(self, fact_id: str, evidence: list[FactEvidenceInput]) -> None:
        """Insert evidence rows without duplicating fact/message/evidence_type links."""

        for item in evidence:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO fact_evidence (
                  evidence_id, fact_id, message_id, message_fingerprint,
                  sanitized_snippet, evidence_type, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evidence_{uuid.uuid4().hex}",
                    fact_id,
                    item.message_id,
                    item.message_fingerprint,
                    item.sanitized_snippet,
                    item.evidence_type,
                    item.confidence,
                    utc_now_iso(),
                ),
            )

    def _refresh_source_count(self, fact_id: str) -> None:
        """Set source_count to the distinct source-message count for a fact."""

        self.connection.execute(
            """
            UPDATE canonical_facts
            SET source_count = (
              SELECT COUNT(DISTINCT message_id)
              FROM fact_evidence
              WHERE fact_id = ?
            )
            WHERE fact_id = ?
            """,
            (fact_id, fact_id),
        )


def _json(value: object) -> str:
    """Serialize structured details in a deterministic JSON representation."""

    return json.dumps(value, sort_keys=True)

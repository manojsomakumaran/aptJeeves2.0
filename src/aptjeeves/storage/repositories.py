from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
import uuid

from aptjeeves.storage.db import utc_now_iso
from aptjeeves.storage.models import (
    FacilityInfoUpsert,
    FactEvidenceInput,
    ImportSummary,
    QuerySummary,
    ProcessInfoUpsert,
    RawMessageInsert,
    ServiceContactUpsert,
    VectorEntryUpsert,
)


_root_logger = logging.getLogger("aptjeeves")
if not _root_logger.handlers:
    _fh = logging.FileHandler("aptjeeves_debug.log")
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    _root_logger.addHandler(_fh)
    _root_logger.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


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

        logger.debug(f"Creating import_run: {import_batch_id}")
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
        extraction_failures: int = 0,
        notes: str | None = None,
    ) -> None:
        """Mark an import as finished and store final counters."""

        logger.debug(f"Completing import_run: {import_batch_id} with status {status}")
        self.connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?,
                status = ?,
                total_messages_seen = ?,
                new_messages_inserted = ?,
                duplicate_messages_skipped = ?,
                parse_failures = ?,
                extraction_failures = ?,
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
                extraction_failures,
                notes,
                import_batch_id,
            ),
        )

    def increment_extraction_failures(self, import_batch_id: str, count: int) -> None:
        """Add to the extraction_failures counter for an existing import run."""

        self.connection.execute(
            """
            UPDATE import_runs
            SET extraction_failures = extraction_failures + ?
            WHERE import_batch_id = ?
            """,
            (count, import_batch_id),
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
        logger.debug(f"Inserted raw message {message.message_id}. Was it new? {cursor.rowcount == 1}")
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

    def reset_failed(self) -> int:
        """Reset 'failed' raw messages back to 'new' so they can be re-extracted."""

        logger.debug("Resetting failed raw messages to 'new'")
        cursor = self.connection.execute(
            "UPDATE raw_messages SET processing_status = 'new' WHERE processing_status = 'failed'"
        )
        return cursor.rowcount

    def count_by_processing_status(self, status: str) -> int:
        """Return the number of raw messages waiting at a specific processing stage."""

        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM raw_messages WHERE processing_status = ?",
            (status,),
        ).fetchone()
        return int(row["count"])

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

    def list_by_import_batch(self, import_batch_id: str) -> list[sqlite3.Row]:
        """Return all raw messages for one import batch in stable order."""

        return self.connection.execute(
            """
            SELECT * FROM raw_messages
            WHERE import_batch_id = ?
            ORDER BY sent_at_utc, source_offset, message_id
            """,
            (import_batch_id,),
        ).fetchall()

    def mark_processing_status(self, message_id: str, status: str) -> None:
        """Update one raw message processing status."""

        logger.debug(f"Marking raw message {message_id} processing_status as {status}")
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

    def count_facts_for_indexing(
        self,
        *,
        embedding_model_version: str | None = None,
    ) -> int:
        """Return the number of facts waiting to be indexed."""

        if embedding_model_version is None:
            row = self.connection.execute(
                """
                SELECT COUNT(cf.fact_id) AS count
                FROM canonical_facts cf
                LEFT JOIN vector_entries ve
                  ON ve.fact_id = cf.fact_id
                 AND ve.fact_version = cf.fact_version
                 AND ve.status = 'active'
                WHERE cf.merge_status = 'active'
                  AND ve.vector_id IS NULL
                """
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT COUNT(cf.fact_id) AS count
                FROM canonical_facts cf
                LEFT JOIN vector_entries ve
                  ON ve.fact_id = cf.fact_id
                 AND ve.fact_version = cf.fact_version
                 AND ve.status = 'active'
                 AND ve.embedding_model_version = ?
                WHERE cf.merge_status = 'active'
                  AND ve.vector_id IS NULL
                """,
                (embedding_model_version,),
            ).fetchone()

        return int(row["count"])

    def list_facts_for_indexing(
        self,
        *,
        limit: int = 100,
        embedding_model_version: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return facts whose current version has no active vector entry.

        If *embedding_model_version* is provided, return facts whose current
        version has no active vector entry for that specific model.
        """

        if embedding_model_version is None:
            return self.connection.execute(
                """
                SELECT cf.*
                FROM canonical_facts cf
                LEFT JOIN vector_entries ve
                  ON ve.fact_id = cf.fact_id
                 AND ve.fact_version = cf.fact_version
                 AND ve.status = 'active'
                WHERE cf.merge_status = 'active'
                  AND ve.vector_id IS NULL
                ORDER BY cf.updated_at, cf.fact_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return self.connection.execute(
            """
            SELECT cf.*
            FROM canonical_facts cf
            LEFT JOIN vector_entries ve
              ON ve.fact_id = cf.fact_id
             AND ve.fact_version = cf.fact_version
             AND ve.status = 'active'
             AND ve.embedding_model_version = ?
            WHERE cf.merge_status = 'active'
              AND ve.vector_id IS NULL
            ORDER BY cf.updated_at, cf.fact_id
            LIMIT ?
            """,
            (embedding_model_version, limit),
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


class QueryRunRepository:
    """Persistence operations for query_runs."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        *,
        query_id: str,
        trace_id: str,
        query_text_redacted: str,
        query_text_hash: str,
        query_intent: str,
        answerer_version: str,
        guardrail_version: str,
        notes: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO query_runs (
              query_id, trace_id, status, query_text_redacted, query_text_hash,
              query_intent, answerer_version, guardrail_version, retrieval_trace_id,
              final_action, notes, created_at, completed_at
            )
            VALUES (?, ?, 'running', ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
            """,
            (
                query_id,
                trace_id,
                query_text_redacted,
                query_text_hash,
                query_intent,
                answerer_version,
                guardrail_version,
                notes,
                utc_now_iso(),
            ),
        )

    def complete(
        self,
        *,
        query_id: str,
        status: str,
        retrieval_trace_id: str | None,
        final_action: str,
        notes: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE query_runs
            SET status = ?,
                retrieval_trace_id = ?,
                final_action = ?,
                notes = COALESCE(?, notes),
                completed_at = ?
            WHERE query_id = ?
            """,
            (
                status,
                retrieval_trace_id,
                final_action,
                notes,
                utc_now_iso(),
                query_id,
            ),
        )

    def get(self, query_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM query_runs WHERE query_id = ?",
            (query_id,),
        ).fetchone()

    def get_summary(self, query_id: str) -> QuerySummary | None:
        row = self.connection.execute(
            """
            SELECT qr.query_id,
                   qr.status,
                   qr.query_text_redacted,
                   qr.query_intent,
                   qr.final_action,
                   qr.retrieval_trace_id,
                   qr.created_at,
                   qr.completed_at,
                   (
                     SELECT COUNT(*)
                     FROM guardrail_events ge
                     WHERE ge.query_id = qr.query_id
                   ) AS guardrail_events_count
            FROM query_runs qr
            WHERE qr.query_id = ?
            """,
            (query_id,),
        ).fetchone()
        if row is None:
            return None
        return QuerySummary(
            query_id=row["query_id"],
            status=row["status"],
            query_text_redacted=row["query_text_redacted"],
            query_intent=row["query_intent"],
            final_action=row["final_action"],
            retrieval_trace_id=row["retrieval_trace_id"],
            guardrail_events_count=int(row["guardrail_events_count"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


def _json(value: object) -> str:
    """Serialize structured details in a deterministic JSON representation."""

    return json.dumps(value, sort_keys=True)


class VectorEntryRepository:
    """Persistence operations for the local vector index table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Create a repository bound to a SQLite connection."""

        self.connection = connection

    def upsert_active(self, entry: VectorEntryUpsert) -> str:
        """Create or refresh the active vector entry for one fact and embedding model."""

        existing = self.get_active_by_fact_and_model(entry.fact_id, entry.embedding_model_version)
        now = utc_now_iso()
        if existing is None:
            vector_id = f"vector_{uuid.uuid4().hex}"
            self.connection.execute(
                """
                INSERT INTO vector_entries (
                  vector_id, fact_id, fact_type, fact_version, embedding_text,
                  embedding_hash, embedding_model_version, embedding_json,
                  vector_store_ref, created_at, updated_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    vector_id,
                    entry.fact_id,
                    entry.fact_type,
                    entry.fact_version,
                    entry.embedding_text,
                    entry.embedding_hash,
                    entry.embedding_model_version,
                    entry.embedding_json,
                    entry.vector_store_ref,
                    now,
                    now,
                ),
            )
            return vector_id

        vector_id = existing["vector_id"]
        self.connection.execute(
            """
            UPDATE vector_entries
            SET fact_type = ?,
                fact_version = ?,
                embedding_text = ?,
                embedding_hash = ?,
                embedding_model_version = ?,
                embedding_json = ?,
                vector_store_ref = ?,
                updated_at = ?,
                status = 'active'
            WHERE vector_id = ?
            """,
            (
                entry.fact_type,
                entry.fact_version,
                entry.embedding_text,
                entry.embedding_hash,
                entry.embedding_model_version,
                entry.embedding_json,
                entry.vector_store_ref,
                now,
                vector_id,
            ),
        )
        return str(vector_id)

    def get_active_by_fact_and_model(self, fact_id: str, embedding_model_version: str) -> sqlite3.Row | None:
        """Return the active vector entry for a fact and specific embedding model, if one exists."""

        return self.connection.execute(
            """
            SELECT *
            FROM vector_entries
            WHERE fact_id = ? AND embedding_model_version = ? AND status = 'active'
            """,
            (fact_id, embedding_model_version),
        ).fetchone()

    def count_active(self, *, embedding_model_version: str | None = None) -> int:
        """Return the number of active vector entries."""

        if embedding_model_version is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM vector_entries WHERE status = 'active'"
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM vector_entries WHERE status = 'active' AND embedding_model_version = ?",
                (embedding_model_version,),
            ).fetchone()
        return int(row["count"])

    def list_active(self, *, embedding_model_version: str | None = None) -> list[sqlite3.Row]:
        """Return active vector entries in stable order."""

        if embedding_model_version is None:
            return self.connection.execute(
                """
                SELECT *
                FROM vector_entries
                WHERE status = 'active'
                ORDER BY updated_at, vector_id
                """
            ).fetchall()

        return self.connection.execute(
            """
            SELECT *
            FROM vector_entries
            WHERE status = 'active' AND embedding_model_version = ?
            ORDER BY updated_at, vector_id
            """,
            (embedding_model_version,),
        ).fetchall()

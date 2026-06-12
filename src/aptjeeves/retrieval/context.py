from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from aptjeeves.retrieval.reranker import RankedFact


@dataclass(frozen=True)
class FactContext:
    """One canonical fact prepared for answer generation."""

    fact_id: str
    fact_type: str
    title: str
    summary: str
    source_count: int
    latest_seen: str
    confidence: float
    privacy_status: str
    approved_contact_methods: list[dict[str, Any]]
    sanitized_snippets: list[str]
    caveats: list[str]
    details: dict[str, Any]
    final_score: float


@dataclass(frozen=True)
class QueryContext:
    """Structured retrieval context ready for the answer formatter."""

    query_id: str
    intent: str
    facts: list[FactContext]


class ContextBuilder:
    """Builds structured answer context from reranked facts."""

    def __init__(self, connection: sqlite3.Connection, *, max_facts: int = 5) -> None:
        self.connection = connection
        self.max_facts = max_facts

    def build(
        self,
        *,
        query_id: str,
        intent: str,
        ranked_facts: list[RankedFact],
    ) -> QueryContext:
        """Load canonical facts and assemble a privacy-filtered context."""

        selected = ranked_facts[: self.max_facts]
        fact_contexts: list[FactContext] = []

        for ranked in selected:
            fact_row = self.connection.execute(
                "SELECT * FROM canonical_facts WHERE fact_id = ?",
                (ranked.fact_id,),
            ).fetchone()
            if fact_row is None:
                continue

            details = self._load_subtype_details(ranked.fact_id, ranked.fact_type)
            snippets = self._load_snippets(ranked.fact_id)
            contact_methods = self._approved_contact_methods(details, fact_row["privacy_status"])
            caveats = self._build_caveats(fact_row, details)

            fact_contexts.append(
                FactContext(
                    fact_id=ranked.fact_id,
                    fact_type=ranked.fact_type,
                    title=fact_row["title"],
                    summary=fact_row["summary"],
                    source_count=fact_row["source_count"],
                    latest_seen=fact_row["latest_seen"],
                    confidence=fact_row["confidence"],
                    privacy_status=fact_row["privacy_status"],
                    approved_contact_methods=contact_methods,
                    sanitized_snippets=snippets,
                    caveats=caveats,
                    details=details,
                    final_score=ranked.final_score,
                )
            )

        return QueryContext(query_id=query_id, intent=intent, facts=fact_contexts)

    def _load_subtype_details(self, fact_id: str, fact_type: str) -> dict[str, Any]:
        table = {"service_contact": "service_contacts", "process_info": "process_info", "facility_info": "facility_info"}.get(fact_type)
        if table is None:
            return {}
        row = self.connection.execute(
            f"SELECT * FROM {table} WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            return {}
        return {key: row[key] for key in row.keys()}

    def _load_snippets(self, fact_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT sanitized_snippet FROM fact_evidence
            WHERE fact_id = ? ORDER BY created_at, evidence_id LIMIT 5
            """,
            (fact_id,),
        ).fetchall()
        return [row["sanitized_snippet"] for row in rows]

    def _approved_contact_methods(
        self, details: dict[str, Any], privacy_status: str,
    ) -> list[dict[str, Any]]:
        """Return contact methods only when privacy allows sharing."""

        if privacy_status in ("restricted", "blocked"):
            return []
        raw = details.get("contact_methods_json")
        if not raw:
            return []
        methods = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(methods, list):
            return []
        approved: list[dict[str, Any]] = []
        for method in methods:
            rec = method.get("exposure_recommendation", "needs_review")
            if rec in ("safe", "public"):
                approved.append(method)
            elif privacy_status == "public_to_residents":
                approved.append(method)
        return approved

    def _build_caveats(self, fact_row: sqlite3.Row, details: dict[str, Any]) -> list[str]:
        caveats: list[str] = []
        if fact_row["privacy_status"] in ("needs_review", "restricted"):
            caveats.append("Contact method not shareable until reviewed.")
        if fact_row["fact_type"] == "process_info":
            caveats.append("Community-discussed information; not officially verified.")
            staleness = details.get("staleness_risk", "medium")
            if staleness == "high":
                caveats.append("This information may be outdated — verify with the provider.")
        detail_caveats = details.get("caveats")
        if detail_caveats and isinstance(detail_caveats, str):
            caveats.append(detail_caveats)
        return caveats

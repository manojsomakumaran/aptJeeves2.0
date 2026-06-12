from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from aptjeeves.retrieval.retriever import RetrievalCandidate


RERANKER_VERSION = "transparent_reranker_v1"

# Weights from detailed-design section 8.3.
W_SIMILARITY = 0.45
W_SOURCE_COUNT = 0.15
W_RECENCY = 0.15
W_CONFIDENCE = 0.15
W_TYPE_MATCH = 0.10


@dataclass(frozen=True)
class RankedFact:
    """A canonical fact with a transparent reranking score."""

    fact_id: str
    fact_type: str
    similarity: float
    source_count_score: float
    recency_score: float
    confidence_score: float
    type_match_score: float
    stale_penalty: float
    privacy_penalty: float
    final_score: float


class Reranker:
    """Reranks retrieval candidates using metadata from canonical_facts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def rerank(
        self,
        candidates: list[RetrievalCandidate],
        *,
        intent: str,
    ) -> list[RankedFact]:
        """Score and sort candidates using the transparent formula."""

        if not candidates:
            return []

        fact_ids = [c.fact_id for c in candidates]
        facts_by_id = self._load_facts(fact_ids)

        ranked: list[RankedFact] = []
        for candidate in candidates:
            fact = facts_by_id.get(candidate.fact_id)
            if fact is None:
                continue

            source_count_score = _source_count_score(fact["source_count"])
            recency_score = _recency_score(fact["latest_seen"])
            confidence_score = min(max(fact["confidence"], 0.0), 1.0)
            type_match_score = _type_match_score(fact["fact_type"], intent)
            stale_penalty = _stale_penalty(fact)
            privacy_penalty = _privacy_penalty(fact["privacy_status"])

            final = (
                candidate.similarity * W_SIMILARITY
                + source_count_score * W_SOURCE_COUNT
                + recency_score * W_RECENCY
                + confidence_score * W_CONFIDENCE
                + type_match_score * W_TYPE_MATCH
                - stale_penalty
                - privacy_penalty
            )

            ranked.append(
                RankedFact(
                    fact_id=candidate.fact_id,
                    fact_type=fact["fact_type"],
                    similarity=candidate.similarity,
                    source_count_score=round(source_count_score, 4),
                    recency_score=round(recency_score, 4),
                    confidence_score=round(confidence_score, 4),
                    type_match_score=round(type_match_score, 4),
                    stale_penalty=round(stale_penalty, 4),
                    privacy_penalty=round(privacy_penalty, 4),
                    final_score=round(final, 6),
                )
            )

        ranked.sort(key=lambda r: r.final_score, reverse=True)
        return ranked

    def _load_facts(self, fact_ids: list[str]) -> dict[str, sqlite3.Row]:
        if not fact_ids:
            return {}
        placeholders = ", ".join("?" for _ in fact_ids)
        rows = self.connection.execute(
            f"SELECT * FROM canonical_facts WHERE fact_id IN ({placeholders})",
            tuple(fact_ids),
        ).fetchall()
        return {row["fact_id"]: row for row in rows}


# ── Score helpers ──────────────────────────────────────────────────────────


_INTENT_TO_FACT_TYPE: dict[str, str] = {
    "find_service_contact": "service_contact",
    "ask_process_steps": "process_info",
    "ask_facility_info": "facility_info",
}

_RELATED_TYPES: dict[str, set[str]] = {
    "find_service_contact": {"process_info"},
    "ask_process_steps": {"service_contact", "facility_info"},
    "ask_facility_info": {"process_info"},
}


def _source_count_score(count: int) -> float:
    """Log-scaled mention count capped at 1."""

    if count <= 0:
        return 0.0
    return min(math.log2(count + 1) / math.log2(10), 1.0)


def _recency_score(latest_seen: str) -> float:
    """Decay based on how old the latest_seen timestamp is."""

    try:
        ts = datetime.fromisoformat(latest_seen.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_old = max((now - ts).total_seconds() / 86400, 0)
    except (ValueError, TypeError):
        return 0.3
    # Full score within 30 days, then decay.
    if days_old <= 30:
        return 1.0
    return max(1.0 - (days_old - 30) / 365, 0.1)


def _type_match_score(fact_type: str, intent: str) -> float:
    """1.0 for exact match, 0.5 for related, 0.0 for unrelated."""

    expected = _INTENT_TO_FACT_TYPE.get(intent)
    if expected and fact_type == expected:
        return 1.0
    related = _RELATED_TYPES.get(intent, set())
    if fact_type in related:
        return 0.5
    if intent in ("general_or_unknown", "ask_policy_or_rule", "ask_alert_or_issue"):
        return 0.5
    return 0.0


def _stale_penalty(fact: sqlite3.Row) -> float:
    """Higher penalty for process_info with old latest_seen."""

    if fact["fact_type"] != "process_info":
        return 0.0
    try:
        ts = datetime.fromisoformat(fact["latest_seen"].replace("Z", "+00:00"))
        days_old = max((datetime.now(timezone.utc) - ts).total_seconds() / 86400, 0)
    except (ValueError, TypeError):
        return 0.05
    if days_old > 180:
        return 0.10
    if days_old > 90:
        return 0.05
    return 0.0


def _privacy_penalty(privacy_status: str) -> float:
    """Penalize restricted or unreviewed contacts."""

    if privacy_status in ("restricted", "blocked"):
        return 0.20
    if privacy_status == "needs_review":
        return 0.05
    return 0.0

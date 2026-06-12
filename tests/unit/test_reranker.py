from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from aptjeeves.retrieval.reranker import (
    Reranker,
    _privacy_penalty,
    _recency_score,
    _source_count_score,
    _stale_penalty,
    _type_match_score,
)
from aptjeeves.retrieval.retriever import RetrievalCandidate


def test_source_count_score_zero_for_no_mentions() -> None:
    assert _source_count_score(0) == 0.0


def test_source_count_score_increases_with_mentions() -> None:
    assert _source_count_score(1) > 0
    assert _source_count_score(5) > _source_count_score(1)


def test_source_count_score_caps_at_one() -> None:
    assert _source_count_score(1000) <= 1.0


def test_recency_score_high_for_recent() -> None:
    from datetime import datetime, timezone

    recent = datetime.now(timezone.utc).isoformat()
    assert _recency_score(recent) == 1.0


def test_recency_score_low_for_old() -> None:
    assert _recency_score("2020-01-01T00:00:00Z") < 0.5


def test_type_match_exact() -> None:
    assert _type_match_score("service_contact", "find_service_contact") == 1.0


def test_type_match_related() -> None:
    assert _type_match_score("process_info", "find_service_contact") == 0.5


def test_type_match_unrelated() -> None:
    assert _type_match_score("facility_info", "find_service_contact") == 0.0


def test_type_match_general_intent_gives_partial() -> None:
    assert _type_match_score("service_contact", "general_or_unknown") == 0.5


def test_privacy_penalty_none_for_public() -> None:
    assert _privacy_penalty("public_to_residents") == 0.0


def test_privacy_penalty_for_restricted() -> None:
    assert _privacy_penalty("restricted") == 0.20


def test_privacy_penalty_for_needs_review() -> None:
    assert _privacy_penalty("needs_review") == 0.05

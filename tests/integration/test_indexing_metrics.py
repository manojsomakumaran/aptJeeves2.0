import sqlite3
import pytest

from aptjeeves.storage.db import apply_migrations
from aptjeeves.storage.repositories import CanonicalFactRepository
from aptjeeves.storage.models import ServiceContactUpsert
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel


@pytest.fixture
def db_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    yield conn
    conn.close()


def test_indexing_pagination_metrics(db_connection):
    """Verify VectorIndexingService calculates remaining items and batches correctly."""
    facts = CanonicalFactRepository(db_connection)

    # Insert 3 facts
    for i in range(3):
        contact = ServiceContactUpsert(
            fact_identity_key=f"test_plumber_{i}",
            title=f"Test Plumber {i}",
            summary="A test plumber",
            privacy_status="public_to_residents",
            confidence=0.9,
            first_seen="2026-01-01T00:00:00Z",
            latest_seen="2026-01-01T00:00:00Z",
            extractor_prompt_version="v1",
            llm_model_version="v1",
            service_type="plumber",
            display_name=f"Test {i}",
            normalized_name=f"test {i}",
            contact_methods=[],
            contact_method_hashes=[],
            contact_classification="vendor",
            is_resident_affiliated=False,
            resident_affiliation_reason=None,
            area_or_scope=None,
            price_hint=None,
            availability_hint=None,
            caveats=None,
        )
        facts.upsert_service_contact(contact, [])

    service = VectorIndexingService(db_connection, LocalTokenEmbeddingModel())

    # 1st Indexing pass
    summary_1 = service.index_pending(limit=2)
    assert summary_1.total_pending_before == 3
    assert summary_1.limit_applied == 2
    assert summary_1.remaining_pending == 1
    assert summary_1.estimated_batches_remaining == 1
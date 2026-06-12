import sqlite3
import pytest

from aptjeeves.storage.db import apply_migrations
from aptjeeves.storage.repositories import (
    CanonicalFactRepository,
    VectorEntryRepository,
    RawMessageRepository,
    ImportRunRepository,
)
from aptjeeves.storage.models import (
    ServiceContactUpsert,
    VectorEntryUpsert,
    RawMessageInsert,
)
from aptjeeves.extraction.service import ExtractionService
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.indexing.indexer import VectorIndexingService
from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel


@pytest.fixture
def db_connection():
    """Provide a fresh, migrated in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    yield conn
    conn.close()


def test_multiple_embedding_models_support(db_connection):
    """Verify canonical facts and vector entries safely isolate multiple embedding models."""
    facts = CanonicalFactRepository(db_connection)
    vectors = VectorEntryRepository(db_connection)

    # 1. Create a single canonical fact
    contact = ServiceContactUpsert(
        fact_identity_key="test_plumber_1",
        title="Test Plumber",
        summary="A test plumber",
        privacy_status="public_to_residents",
        confidence=0.9,
        first_seen="2026-01-01T00:00:00Z",
        latest_seen="2026-01-01T00:00:00Z",
        extractor_prompt_version="v1",
        llm_model_version="v1",
        service_type="plumber",
        display_name="Test",
        normalized_name="test",
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
    fact_id = facts.upsert_service_contact(contact, [])

    # 2. Both Model A and Model B should see this fact as pending indexing
    assert facts.count_facts_for_indexing(embedding_model_version="model_A") == 1
    assert facts.count_facts_for_indexing(embedding_model_version="model_B") == 1

    # 3. Index it with Model A
    vectors.upsert_active(
        VectorEntryUpsert(
            fact_id=fact_id,
            fact_type="service_contact",
            fact_version=1,
            embedding_text="test text",
            embedding_hash="hash_a",
            embedding_model_version="model_A",
            embedding_json="[0.1, 0.2]",
            vector_store_ref=None,
        )
    )

    # 4. Model A should see 0 pending, Model B should STILL see 1 pending
    assert facts.count_facts_for_indexing(embedding_model_version="model_A") == 0
    assert facts.count_facts_for_indexing(embedding_model_version="model_B") == 1

    # 5. Index it with Model B
    vectors.upsert_active(
        VectorEntryUpsert(
            fact_id=fact_id,
            fact_type="service_contact",
            fact_version=1,
            embedding_text="test text",
            embedding_hash="hash_b",
            embedding_model_version="model_B",
            embedding_json="[0.3, 0.4]",
            vector_store_ref=None,
        )
    )

    # 6. Verify total isolation in retrieval counts
    assert vectors.count_active() == 2
    assert vectors.count_active(embedding_model_version="model_A") == 1
    assert vectors.count_active(embedding_model_version="model_B") == 1


def test_extraction_pagination_metrics(db_connection):
    """Verify ExtractionService calculates remaining items and batches correctly."""
    raw_msgs = RawMessageRepository(db_connection)
    import_runs = ImportRunRepository(db_connection)

    # Setup dummy import batch
    import_runs.create(
        import_batch_id="batch_1",
        source_platform="whatsapp",
        source_file="test.txt",
        source_file_hash="hash",
        chat_name="test",
        parser_version="v1",
        normalizer_version="v1",
        redactor_version="v1",
    )

    # Insert 5 pending raw messages
    for i in range(5):
        raw_msgs.insert_if_new(
            RawMessageInsert(
                message_id=f"msg_{i}",
                message_fingerprint=f"fp_{i}",
                import_batch_id="batch_1",
                platform="whatsapp",
                source_conversation_id="conv_1",
                chat_name="test",
                source_message_id=None,
                sender_hash="sender",
                sender_display_hint="Sender",
                sent_at_utc="2026-01-01T00:00:00Z",
                source_timezone="UTC",
                normalized_text_hash=f"hash_{i}",
                sanitized_text=f"test message {i}",
                raw_text_debug_ref=None,
                source_file="test.txt",
                source_offset=i,
                source_line_start=i,
                source_line_end=i,
                processing_status="new",
                first_seen_at="2026-01-01T00:00:00Z",
                processed_at=None,
                parser_version="v1",
                normalizer_version="v1",
                redactor_version="v1",
            )
        )

    service = ExtractionService(db_connection, FakeExtractor())

    # 1st Extract (limit=2)
    summary_1 = service.extract_pending(limit=2)
    assert summary_1.total_pending_before == 5
    assert summary_1.limit_applied == 2
    assert summary_1.remaining_pending == 3
    assert summary_1.estimated_batches_remaining == 2  # ceil(3/2)

    # 2nd Extract (limit=2)
    summary_2 = service.extract_pending(limit=2)
    assert summary_2.total_pending_before == 3
    assert summary_2.limit_applied == 2
    assert summary_2.remaining_pending == 1
    assert summary_2.estimated_batches_remaining == 1  # ceil(1/2)

    # 3rd Extract (limit=2)
    summary_3 = service.extract_pending(limit=2)
    assert summary_3.total_pending_before == 1
    assert summary_3.limit_applied == 2
    assert summary_3.remaining_pending == 0
    assert summary_3.estimated_batches_remaining == 0

    # 4th Extract (Empty queue)
    summary_4 = service.extract_pending(limit=2)
    assert summary_4.total_pending_before == 0
    assert summary_4.remaining_pending == 0
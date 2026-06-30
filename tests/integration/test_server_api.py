import pytest
from fastapi.testclient import TestClient
from aptjeeves.api.server import app

@pytest.fixture
def client():
    return TestClient(app)

def test_apartment_settings_get_post(client):
    apartment = "test-apt-settings"
    
    # Test GET (defaults to env values or None overrides)
    res_get = client.get(f"/api/{apartment}/settings")
    assert res_get.status_code == 200
    data = res_get.json()
    assert "embedding_model" in data
    assert "extraction_model" in data
    
    # Test POST
    res_post = client.post(
        f"/api/{apartment}/settings",
        json={"embedding_model": "test-embedding-model-v2"}
    )
    assert res_post.status_code == 200
    assert res_post.json()["status"] == "success"
    
    # Test GET to verify update persisted
    res_get2 = client.get(f"/api/{apartment}/settings")
    assert res_get2.status_code == 200
    assert res_get2.json()["embedding_model"] == "test-embedding-model-v2"

def test_list_apartments(client):
    # Triggering settings for an arbitrary apartment forces the DB and directory creation
    apartment = "test-apt-flow"
    client.post(
        f"/api/{apartment}/settings",
        json={"embedding_model": "dummy-model"}
    )

    response = client.get("/api/apartments")
    assert response.status_code == 200
    assert "apartments" in response.json()
    assert isinstance(response.json()["apartments"], list)
    assert apartment in response.json()["apartments"]

def test_status_and_observability_schemas(client):
    apartment = "test-apt-flow"
    
    res_status = client.get(f"/api/{apartment}/status")
    assert res_status.status_code == 200
    assert "messages" in res_status.json()
    assert "facts" in res_status.json()
    assert "current_models" in res_status.json()
    
    res_obs = client.get(f"/api/{apartment}/observability")
    assert res_obs.status_code == 200
    assert "usage" in res_obs.json()
    assert "latencies" in res_obs.json()

def test_upload_chat_export_missing_primary_file(client, tmp_path):
    apartment = "test-apt-upload"
    dummy_file = tmp_path / "chat.txt"
    dummy_file.write_text("dummy chat content")
    
    with open(dummy_file, "rb") as f:
        res = client.post(
            f"/api/{apartment}/upload",
            data={"platform": "whatsapp", "primary_filename": "missing.txt"},
            files=[("files", ("chat.txt", f, "text/plain"))]
        )
        
    assert res.status_code == 400
    assert "Primary file" in res.json()["detail"]

def test_startup_cleanup_stale_tasks(tmp_path, monkeypatch):
    from pathlib import Path
    from aptjeeves.api.server import cleanup_stale_tasks
    from aptjeeves.storage.db import connect, apply_migrations
    from aptjeeves.observability.events import ObservabilityService
    
    # Mock settings data_dir to a temporary directory
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    class MockSettings:
        def __init__(self):
            self.data_dir = data_dir
            self.default_timezone = "Asia/Kolkata"
            self.log_level = "INFO"
            self.embedding_model = "text-embedding-3-small"
            self.extraction_model = "gpt-4o-mini"
            self.intent_backend = "keyword"
            self.intent_model = "gpt-4o-mini"
    
    monkeypatch.setattr("aptjeeves.api.server.load_settings", lambda: MockSettings())
    
    # Create a dummy apartment db
    apt_dir = data_dir / "apartments" / "test-cleanup-apt"
    apt_dir.mkdir(parents=True)
    db_path = apt_dir / "aptjeeves.sqlite3"
    
    conn = connect(db_path)
    apply_migrations(conn)
    
    events = ObservabilityService(conn)
    trace_id = "trace_stale_progress_task"
    
    # Emit a background_task_progress event (which should trigger cleanup on restart)
    events.emit(
        trace_id=trace_id,
        event_type="background_task_progress",
        stage="extraction",
        status="running",
        payload={"batch": 1}
    )
    conn.commit()
    conn.close()
    
    # Run the startup cleanup logic
    cleanup_stale_tasks()
    
    # Verify the event is now background_task_failed
    conn = connect(db_path)
    last_event = conn.execute(
        "SELECT event_type, sanitized_payload_json FROM pipeline_events WHERE stage = 'extraction' ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    conn.close()
    
    assert last_event is not None
    assert last_event["event_type"] == "background_task_failed"
    assert "interrupted" in last_event["sanitized_payload_json"]

def test_observability_caching_and_paging(client, monkeypatch):
    apartment = "test-apt-obs-cache"
    
    # Setup the apartment settings to make sure it's initialized
    client.post(
        f"/api/{apartment}/settings",
        json={"embedding_model": "dummy-model"}
    )
    
    # Mock Langfuse client and get_observations method
    class MockObservationsData:
        def __init__(self, data):
            self.data = data
            
    class MockObservation:
        def __init__(self, usage=None, calculated_total_cost=None, latency=None, name=None):
            self.usage = usage
            self.calculated_total_cost = calculated_total_cost
            self.latency = latency
            self.name = name

    mock_calls = 0

    class MockLangfuseClient:
        def get_observations(self, **kwargs):
            nonlocal mock_calls
            mock_calls += 1
            # Return some fake generation data
            if mock_calls == 1:
                return MockObservationsData([
                    MockObservation(
                        usage=type("Usage", (object,), {"total": 500}),
                        calculated_total_cost=0.01,
                        latency=1.5,
                        name="llm_extract_facts"
                    )
                ])
            return MockObservationsData([])

    # Mock the langfuse client provider
    monkeypatch.setattr("aptjeeves.config.get_langfuse_client", lambda: MockLangfuseClient())
    
    # Clear the global cache to start fresh
    from aptjeeves.api.server import OBSERVABILITY_CACHE
    OBSERVABILITY_CACHE.clear()
    
    # Call 1: should call get_observations and populate cache
    res1 = client.get(f"/api/{apartment}/observability")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["usage"]["total_tokens"] == 500
    assert data1["usage"]["total_cost"] == 0.01
    assert mock_calls == 1
    
    # Call 2 (immediate): should hit cache, NOT call get_observations again
    res2 = client.get(f"/api/{apartment}/observability")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["usage"]["total_tokens"] == 500
    assert mock_calls == 1  # Verify calls remained 1!
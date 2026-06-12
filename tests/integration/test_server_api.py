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
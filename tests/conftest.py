import pytest
from aptjeeves.config import load_dotenv


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live-provider",
        action="store_true",
        default=False,
        help="Run live provider smoke tests (requires .env with provider keys)",
    )


@pytest.fixture(autouse=True)
def ensure_dotenv_loaded(monkeypatch) -> None:
    """Load `.env` before tests run and override keys/backends to prevent network calls."""
    load_dotenv()
    # Disable Langfuse cloud communication
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_HOST", "")
    
    # Default to local/fake components to prevent external LLM/Embedding calls
    monkeypatch.setenv("APTJEEVES_EXTRACTION_BACKEND", "fake")
    monkeypatch.setenv("APTJEEVES_INTENT_BACKEND", "keyword")
    monkeypatch.setenv("APTJEEVES_EMBEDDING_MODEL", "local")
    monkeypatch.setenv("APTJEEVES_LLM_PROVIDER", "disabled")


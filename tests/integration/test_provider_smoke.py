import os
import pytest

from aptjeeves.extraction.schemas import MessageForExtraction
from aptjeeves.extraction.llm_extractor import LLMExtractor


def test_provider_smoke(pytestconfig):
    """Opt-in smoke test that exercises a real provider via `.env`.

    Usage: `pytest --live-provider` (the repository's `load_dotenv` runs
    automatically via `tests/conftest.py`). This test fails fast if
    `OPENAI_API_KEY` is not present in the environment or `.env`.
    """
    if not pytestconfig.getoption("live_provider"):
        pytest.skip("Live provider tests not enabled. Use --live-provider.")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.fail("OPENAI_API_KEY not set in environment or .env; provide a key for live tests")

    extractor = LLMExtractor(api_key=api_key, model="gpt-4o-mini")
    message = MessageForExtraction(
        message_id="m1",
        message_fingerprint="f1",
        sent_at_utc="2026-06-04T12:00:00Z",
        sender_hash="sender1",
        sanitized_text="Water supply problem in block A; contact PHONE_1 for plumber",
    )

    result = extractor.extract([message])
    assert isinstance(result, dict), "Provider returned non-dict response"
    assert "facts" in result and "warnings" in result
    assert isinstance(result["facts"], list)

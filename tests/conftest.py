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
def ensure_dotenv_loaded() -> None:
    """Load `.env` before tests run so tests can rely on env vars.

    This uses the repository's `load_dotenv` helper which is deterministic
    and covered by unit tests.
    """
    load_dotenv()

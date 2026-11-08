"""Repository-wide options for modernization acceptance and integration tests."""

import pytest


@pytest.fixture(autouse=True)
def isolate_developer_configuration(monkeypatch):
    """Default tests must not use ignored developer cloud/provider credentials.

    Opt-in live storage tests explicitly pass their FACTORYOS_TEST_* URI into a
    disposable subprocess/database. Individual configuration tests may override
    these values with monkeypatch after this fixture has installed the defaults.
    """
    for name in ("MONGODB_URI", "TIGERDATA_DATABASE_URL", "NVIDIA_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("SOLANA_ENABLED", "false")
    for name in ("SOLANA_ALLOWED_PUBLISHER", "SOLANA_PUBLISHER_KEYPAIR_PATH"):
        monkeypatch.setenv(name, "")


def pytest_addoption(parser):
    parser.addoption("--monitor-source", default=None, help="Source file to test inside Docker")
    parser.addoption("--monitor-image", default=None, help="Immutable monitor image ID")
    parser.addoption("--monitor-trace", default=None, help="Host-side JSONL execution evidence")
    parser.addoption("--run-docker-tests", action="store_true", help="Run Docker integration tests")
    parser.addoption("--run-mongo-tests", action="store_true", help="Run local MongoDB integration tests")

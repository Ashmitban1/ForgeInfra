"""Repository-wide options for modernization acceptance and integration tests."""


def pytest_addoption(parser):
    parser.addoption("--monitor-source", default=None, help="Source file to test inside Docker")
    parser.addoption("--monitor-image", default=None, help="Immutable monitor image ID")
    parser.addoption("--monitor-trace", default=None, help="Host-side JSONL execution evidence")
    parser.addoption("--run-docker-tests", action="store_true", help="Run Docker integration tests")

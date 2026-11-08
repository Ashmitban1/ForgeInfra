"""Select Docker execution for the same independently authored acceptance cases."""

from pathlib import Path

import pytest

from backend.modernization.docker_runner import resolve_image, run_docker_monitor
from backend.modernization.runner import run_legacy_monitor


@pytest.fixture
def monitor(request):
    source = request.config.getoption("--monitor-source")
    if source is None:
        return run_legacy_monitor
    image_id = request.config.getoption("--monitor-image")
    if not image_id:
        raise pytest.UsageError("--monitor-source requires --monitor-image")
    trace = request.config.getoption("--monitor-trace")
    return lambda event: run_docker_monitor(
        Path(source), event, image_id, Path(trace) if trace else None,
    )


@pytest.fixture(scope="session")
def docker_image(request):
    if not request.config.getoption("--run-docker-tests"):
        pytest.skip("Enable Docker integration with --run-docker-tests")
    return resolve_image()

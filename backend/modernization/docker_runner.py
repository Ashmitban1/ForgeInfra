"""Run JSON monitoring events in restricted, disposable Docker containers."""

import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from backend.modernization.patching import source_hash
from backend.modernization.runner import LegacyMonitorError
from backend.schemas.incident import TelemetryEvent

DEFAULT_IMAGE = "factoryos-monitor:local"
MONITOR_TIMEOUT_SECONDS = 15


class DockerUnavailable(LegacyMonitorError):
    """Docker or the prepared image is unavailable; no host fallback is allowed."""


def resolve_image(image: str = DEFAULT_IMAGE) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]*", image):
        raise ValueError("Invalid Docker image name")
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DockerUnavailable("Docker is unavailable; start Docker Desktop") from error
    image_id = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise DockerUnavailable(
            "Docker or the monitor image is unavailable. Start Docker Desktop and run: "
            "docker build -t factoryos-monitor:local backend/modernization/container"
        )
    return image_id


def container_command(source: Path, image_id: str, name: str) -> list[str]:
    source = source.resolve(strict=True)
    if not source.is_file() or "," in str(source):
        raise ValueError("Monitor must be a regular file with no comma in its path")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Execution requires an immutable Docker image ID")
    if not re.fullmatch(r"factoryos-monitor-[0-9a-f]{32}", name):
        raise ValueError("Invalid temporary container name")
    return [
        "docker", "run", "--rm", "--interactive", "--pull=never", "--name", name,
        "--network=none", "--read-only", "--user=65534:65534",
        "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
        "--memory=128m", "--memory-swap=128m", "--cpus=0.5", "--pids-limit=32",
        "--ulimit=nofile=64:64", "--log-driver=none",
        "--mount", f"type=bind,source={source},target=/work/monitor.py,readonly",
        image_id,
    ]


def run_docker_monitor(
    source: Path, event: TelemetryEvent, image_id: str, trace_path: Path | None = None,
) -> dict:
    source = source.resolve(strict=True)
    revision = source_hash(source)
    name = "factoryos-monitor-" + uuid.uuid4().hex
    command = container_command(source, image_id, name)
    start = time.monotonic()
    trace = {"command": command, "source_revision": revision,
             "input": event.model_dump(mode="json"), "timed_out": False}
    try:
        process = subprocess.run(
            command, input=event.model_dump_json(), capture_output=True, text=True,
            timeout=MONITOR_TIMEOUT_SECONDS, check=False,
        )
        trace.update(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        trace.update(exit_code=None, timed_out=True,
                     stdout=decoded(error.stdout), stderr=decoded(error.stderr))
        raise LegacyMonitorError("Container execution timed out") from error
    except OSError as error:
        trace.update(exit_code=None, stderr=str(error))
        raise DockerUnavailable("Could not execute Docker; no host fallback was attempted") from error
    finally:
        # Only our UUID-named container is eligible for cleanup, including on timeout.
        try:
            cleanup = subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, text=True,
                timeout=10, check=False,
            )
            trace["cleanup_exit_code"] = cleanup.returncode
            trace["cleanup_stderr"] = cleanup.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            trace["cleanup_error"] = str(error)
        trace["duration_seconds"] = round(time.monotonic() - start, 3)
        if trace_path is not None:
            with trace_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(trace) + "\n")
    if process.returncode != 0:
        raise LegacyMonitorError(f"Container exited {process.returncode}: {process.stderr.strip()}")
    try:
        output = json.loads(process.stdout)
        if not isinstance(output, dict):
            raise ValueError("Expected an object")
        if (output.get("status") not in ("NORMAL", "WARNING")
                or output.get("device_id") != event.device_id
                or output.get("sampled_at") != event.model_dump(mode="json")["observed_at"]
                or output.get("source_revision") != revision
                or source_hash(source) != revision):
            raise ValueError("Source or result metadata did not match")
    except ValueError as error:
        raise LegacyMonitorError("Invalid container monitor output") from error
    return output

"""Proposal boundaries, verification outcomes, and opt-in real Docker tests."""

import json
from pathlib import Path
import subprocess

import pytest

from backend.modernization import docker_runner, patching, testing
from backend.modernization.docker_runner import DockerUnavailable, container_command, run_docker_monitor
from backend.modernization.patching import create_demo_proposal, source_hash
from backend.modernization.runner import LEGACY_MONITOR_PATH, LegacyMonitorError
from backend.schemas.incident import TelemetryEvent


def event() -> TelemetryEvent:
    return TelemetryEvent.model_validate_json((LEGACY_MONITOR_PATH.parent / "fault.json").read_text())


def test_proposal_preserves_original_and_uses_unique_workspaces(tmp_path):
    original_bytes = LEGACY_MONITOR_PATH.read_bytes()
    proposal = create_demo_proposal(tmp_path)
    another = create_demo_proposal(tmp_path)
    assert proposal.workspace != another.workspace
    assert proposal.original.read_bytes() == original_bytes == LEGACY_MONITOR_PATH.read_bytes()
    assert proposal.original_revision != proposal.candidate_revision
    assert 'event.get("cooling_fault", False)' in proposal.candidate.read_text()
    assert '--- original/monitor.py' in proposal.diff.read_text()
    assert '+++ candidate/monitor.py' in proposal.diff.read_text()
    assert proposal.diff_revision == source_hash(proposal.diff)


def test_changed_original_rule_requires_patch_review(tmp_path, monkeypatch):
    source = tmp_path / "changed.py"
    source.write_text('status = "WARNING" if temperature > 40 else "NORMAL"\n')
    monkeypatch.setattr(patching, "LEGACY_MONITOR_PATH", source)
    with pytest.raises(ValueError, match="review the demo patch"):
        create_demo_proposal(tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("changed_file", ["candidate", "original", "diff"])
def test_tampered_proposal_never_executes_or_verifies(tmp_path, monkeypatch, changed_file):
    proposal = create_demo_proposal(tmp_path)
    source = getattr(proposal, changed_file)
    source.write_text(source.read_text() + "\n# changed after proposal\n")

    def must_not_resolve(*args):
        pytest.fail("Changed proposals must be rejected before Docker access")

    monkeypatch.setattr(testing, "resolve_image", must_not_resolve)
    report = testing.verify_proposal(proposal)
    assert report["status"] == "SOURCE_CHANGED"
    assert report["sources_unchanged"] is False
    assert report["tests"] == {}
    assert report["approval_status"] == "PENDING"
    assert report["deployed"] is False


def test_docker_unavailable_has_no_host_fallback(tmp_path, monkeypatch):
    proposal = create_demo_proposal(tmp_path)

    def unavailable(*args):
        raise DockerUnavailable("verification-only unavailable Docker")

    monkeypatch.setattr(testing, "resolve_image", unavailable)
    report = testing.verify_proposal(proposal)
    assert report["status"] == "VERIFICATION_ERROR"
    assert report["tests"] == {}
    assert report["isolation"]["unisolated_fallback"] is False
    assert json.loads((proposal.workspace / "report.json").read_text()) == report


def test_tag_cannot_be_used_as_execution_identity():
    with pytest.raises(ValueError, match="immutable"):
        container_command(LEGACY_MONITOR_PATH, "factoryos-monitor:local", "factoryos-monitor-" + "a" * 32)


def test_sibling_container_uses_host_artifact_path(tmp_path, monkeypatch):
    monkeypatch.setattr(docker_runner, "DEFAULT_OUTPUT_ROOT", tmp_path)
    monkeypatch.setenv("FACTORYOS_DOCKER_ARTIFACT_ROOT", "/host/repairs")
    source = tmp_path / "repair-123" / "candidate" / "monitor.py"
    source.parent.mkdir(parents=True)
    source.write_text("# candidate\n")
    command = container_command(source, "sha256:" + "a" * 64, "factoryos-monitor-" + "b" * 32)
    assert "type=bind,source=/host/repairs/repair-123/candidate/monitor.py,target=/work/monitor.py,readonly" in command
    assert "--network=none" in command and "--read-only" in command
    with pytest.raises(ValueError):
        container_command(LEGACY_MONITOR_PATH, "sha256:" + "a" * 64, "factoryos-monitor-" + "b" * 32)


@pytest.mark.parametrize("root", ["relative/path", "/host/path,other"])
def test_invalid_host_artifact_root_rejected(root, monkeypatch):
    monkeypatch.setenv("FACTORYOS_DOCKER_ARTIFACT_ROOT", root)
    with pytest.raises(ValueError, match="absolute path without commas"):
        container_command(LEGACY_MONITOR_PATH, "sha256:" + "a" * 64, "factoryos-monitor-" + "b" * 32)


def test_missing_or_skipped_cases_cannot_verify():
    cases = [{"name": name, "outcome": "passed", "message": ""}
             for name in sorted(testing.EXPECTED_CASES)]
    original = {"exit_code": 1, "cases": [dict(case) for case in cases]}
    failure = next(case for case in original["cases"] if case["name"] == "test_cooling_fault_requires_warning")
    failure.update(outcome="failure", message="monitor returned NORMAL")
    assert testing.classify_results(original, {"exit_code": 0, "cases": cases}) == "VERIFIED"
    assert testing.classify_results(original, {"exit_code": 0, "cases": cases[:-1]}) == "VERIFICATION_ERROR"
    cases[0]["outcome"] = "skipped"
    assert testing.classify_results(original, {"exit_code": 0, "cases": cases}) == "CANDIDATE_FAILED"
    assert testing.classify_results(original, original) == "CANDIDATE_FAILED"


def test_real_docker_before_after_verification(tmp_path, docker_image):
    revision = source_hash(LEGACY_MONITOR_PATH)
    proposal = create_demo_proposal(tmp_path)
    report = testing.verify_proposal(proposal, "TEST-REPAIR-001", docker_image)
    assert report["status"] == "VERIFIED", (proposal.workspace / "report.json").read_text()
    assert report["incident_id"] == "TEST-REPAIR-001"
    assert report["approval_status"] == "PENDING" and report["deployed"] is False
    assert report["sources_unchanged"] and source_hash(LEGACY_MONITOR_PATH) == revision
    assert report["isolation"]["image_id"] == docker_image
    for label, exit_code, passes in [("original", 1, 4), ("candidate", 0, 5)]:
        result = report["tests"][label]
        assert result["exit_code"] == exit_code
        assert sum(case["outcome"] == "passed" for case in result["cases"]) == passes
        assert "--runxfail" in result["command"]
        traces = [json.loads(line) for line in Path(result["container_trace_path"]).read_text().splitlines()]
        assert len(traces) == 5
        for trace in traces:
            assert trace["exit_code"] == 0 and not trace["timed_out"]
            assert "--network=none" in trace["command"]
            assert trace["command"][-1] == docker_image
        for path, expected_revision in result["evidence_revisions"].items():
            assert source_hash(Path(path)) == expected_revision


def test_docker_blocks_host_reads_writes_and_external_network(tmp_path, docker_image, monkeypatch):
    monkeypatch.setenv("FACTORYOS_TEST_SECRET", "not-a-real-secret")
    source = tmp_path / "probe.py"
    host_only = tmp_path / "host-only.txt"
    host_only.write_text("verification-only host data")
    source.write_text(f'''
import hashlib
import json
import os
from pathlib import Path
import socket
event = json.load(__import__("sys").stdin)
assert os.getuid() == 65534
assert "FACTORYOS_TEST_SECRET" not in os.environ
assert not Path("/var/run/docker.sock").exists()
assert not Path({str(host_only)!r}).exists()
try:
    Path("/work/unexpected.txt").write_text("must fail")
except OSError:
    pass
else:
    raise AssertionError("Container filesystem was writable")
try:
    socket.create_connection(("192.0.2.1", 80), timeout=1)
except OSError as error:
    assert error.errno in (101, 113), str(error)
else:
    raise AssertionError("External network was reachable")
print(json.dumps({{
    "device_id": event["device_id"], "status": "WARNING", "sampled_at": event["observed_at"],
    "source_revision": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}}))
''')
    assert run_docker_monitor(source, event(), docker_image)["status"] == "WARNING"
    assert not (tmp_path / "unexpected.txt").exists()


def test_docker_timeout_removes_its_container(tmp_path, docker_image, monkeypatch):
    source = tmp_path / "slow.py"
    source.write_text("import time\ntime.sleep(60)\n")
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(docker_runner, "MONITOR_TIMEOUT_SECONDS", 3)
    with pytest.raises(LegacyMonitorError, match="timed out"):
        run_docker_monitor(source, event(), docker_image, trace_path)
    trace = json.loads(trace_path.read_text())
    assert trace["timed_out"] and trace["exit_code"] is None
    command = trace["command"]
    name = command[command.index("--name") + 1]
    result = subprocess.run(["docker", "container", "inspect", name], capture_output=True, timeout=10)
    assert result.returncode != 0

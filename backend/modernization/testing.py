"""Generate a demo repair and save actual Docker-backed before/after tests."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from backend.modernization.docker_runner import DEFAULT_IMAGE, DockerUnavailable, resolve_image
from backend.modernization.patching import (
    DEFAULT_OUTPUT_ROOT, REPOSITORY_ROOT, RepairProposal, create_demo_proposal, source_hash,
)
from backend.modernization.runner import LEGACY_MONITOR_PATH

ACCEPTANCE_SUITE = REPOSITORY_ROOT / "tests/modernization/test_repair_requirements.py"
ACCEPTANCE_CONFIG = ACCEPTANCE_SUITE.with_name("conftest.py")
ACCEPTANCE_OPTIONS = REPOSITORY_ROOT / "tests/conftest.py"
EXPECTED_CASES = {
    "test_monitor_preserves_temperature_behavior[healthy]",
    "test_monitor_preserves_temperature_behavior[high-temperature]",
    "test_monitor_preserves_temperature_behavior[strict-threshold-boundary]",
    "test_monitor_preserves_temperature_behavior[high-temperature-with-fault]",
    "test_cooling_fault_requires_warning",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_matches(path: Path, revision: str) -> bool:
    try:
        return source_hash(path) == revision
    except OSError:
        return False


def run_acceptance_tests(source: Path, workspace: Path, label: str, image_id: str) -> dict:
    xml_path = workspace / f"{label}-tests.xml"
    trace_path = workspace / f"{label}-containers.jsonl"
    command = [
        sys.executable, "-m", "pytest", str(ACCEPTANCE_SUITE), "--runxfail", "-q",
        "-p", "no:cacheprovider", f"--monitor-source={source}", f"--monitor-image={image_id}",
        f"--monitor-trace={trace_path}", f"--junitxml={xml_path}",
    ]
    started_at, start = utc_now(), time.monotonic()
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    try:
        process = subprocess.run(
            command, cwd=REPOSITORY_ROOT, capture_output=True, text=True,
            timeout=150, env=environment, check=False,
        )
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or b"", error.stderr or b"", None
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    stdout_path = workspace / f"{label}-pytest.stdout.txt"
    stderr_path = workspace / f"{label}-pytest.stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    cases = []
    if xml_path.exists():
        for case in ET.parse(xml_path).getroot().iter("testcase"):
            outcome = next((tag for tag in ("failure", "error", "skipped")
                            if case.find(tag) is not None), "passed")
            detail = case.find(outcome)
            cases.append({"name": case.attrib["name"], "outcome": outcome,
                          "message": detail.attrib.get("message", "") if detail is not None else ""})
    return {
        "command": command, "started_at": started_at, "finished_at": utc_now(),
        "duration_seconds": round(time.monotonic() - start, 3),
        "exit_code": exit_code, "timed_out": exit_code is None, "cases": cases,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "junit_path": str(xml_path) if xml_path.exists() else None,
        "container_trace_path": str(trace_path) if trace_path.exists() else None,
        "evidence_revisions": {
            str(path): source_hash(path)
            for path in (stdout_path, stderr_path, xml_path, trace_path) if path.exists()
        },
    }


def classify_results(original: dict, candidate: dict) -> str:
    for result in (original, candidate):
        if (len(result["cases"]) != 5
                or {case["name"] for case in result["cases"]} != EXPECTED_CASES):
            return "VERIFICATION_ERROR"
    failures = [case for case in original["cases"] if case["outcome"] != "passed"]
    if (original["exit_code"] != 1 or len(failures) != 1
            or failures[0]["name"] != "test_cooling_fault_requires_warning"
            or failures[0]["outcome"] != "failure"
            or "monitor returned NORMAL" not in failures[0]["message"]):
        return "BASELINE_NOT_REPRODUCED"
    if candidate["exit_code"] != 0 or any(case["outcome"] != "passed" for case in candidate["cases"]):
        return "CANDIDATE_FAILED"
    return "VERIFIED"


def verify_proposal(
    proposal: RepairProposal, incident_id: str | None = None, image: str = DEFAULT_IMAGE,
) -> dict:
    expected = {
        LEGACY_MONITOR_PATH: proposal.original_revision,
        proposal.original: proposal.original_revision,
        proposal.candidate: proposal.candidate_revision,
        proposal.diff: proposal.diff_revision,
        ACCEPTANCE_SUITE: source_hash(ACCEPTANCE_SUITE),
        ACCEPTANCE_CONFIG: source_hash(ACCEPTANCE_CONFIG),
        ACCEPTANCE_OPTIONS: source_hash(ACCEPTANCE_OPTIONS),
    }
    report = {
        "schema_version": "1.0", "repair_id": proposal.workspace.name,
        "incident_id": incident_id, "created_at": utc_now(),
        "proposal_origin": proposal.proposal_origin, "status": "VERIFICATION_ERROR",
        "approval_status": "PENDING", "deployed": False,
        "isolation": {"mode": "docker", "image": image, "image_id": None,
                      "unisolated_fallback": False},
        "original": {"path": str(proposal.original), "source_revision": proposal.original_revision},
        "candidate": {"path": str(proposal.candidate), "source_revision": proposal.candidate_revision},
        "diff_path": str(proposal.diff), "diff_revision": proposal.diff_revision,
        "acceptance_suite_revision": expected[ACCEPTANCE_SUITE],
        "acceptance_config_revision": expected[ACCEPTANCE_CONFIG],
        "acceptance_options_revision": expected[ACCEPTANCE_OPTIONS], "tests": {},
    }
    try:
        if not all(file_matches(path, revision) for path, revision in expected.items()):
            raise ValueError("Source or diff changed before verification")
        image_id = resolve_image(image)
        report["isolation"]["image_id"] = image_id
        report["tests"]["original"] = run_acceptance_tests(
            proposal.original, proposal.workspace, "original", image_id,
        )
        report["tests"]["candidate"] = run_acceptance_tests(
            proposal.candidate, proposal.workspace, "candidate", image_id,
        )
        report["status"] = classify_results(report["tests"]["original"], report["tests"]["candidate"])
    except (OSError, ValueError, DockerUnavailable, ET.ParseError) as error:
        report["status"], report["error"] = "VERIFICATION_ERROR", str(error)
    finally:
        report["sources_unchanged"] = all(file_matches(path, revision) for path, revision in expected.items())
        if not report["sources_unchanged"]:
            report["status"] = "SOURCE_CHANGED"
        report["finished_at"] = utc_now()
        (proposal.workspace / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--incident-id", default=None, help="Optional correlation label; no incident is fetched")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()
    try:
        proposal = create_demo_proposal(args.output_dir)
        report = verify_proposal(proposal, args.incident_id, args.image)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": report["status"], "approval_status": report["approval_status"],
        "report_path": str(proposal.workspace / "report.json"), "diff_path": str(proposal.diff),
        "error": report.get("error"),
        "tests": {label: {"exit_code": result["exit_code"],
                          "passed": sum(case["outcome"] == "passed" for case in result["cases"]),
                          "failed": sum(case["outcome"] in ("failure", "error") for case in result["cases"])}
                  for label, result in report["tests"].items()},
    }, indent=2))
    return 0 if report["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

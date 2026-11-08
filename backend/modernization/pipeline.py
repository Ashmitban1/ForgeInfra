"""Connect the existing verifier to a frozen incident and its actual event replay."""

import json
from pathlib import Path
import sys

from backend.modernization.docker_runner import run_docker_monitor
from backend.modernization.patching import REPOSITORY_ROOT, create_demo_proposal, source_hash
from backend.modernization.repository import content_revision
from backend.modernization.testing import verify_proposal
from backend.schemas.incident import TelemetryEvent


def incident_event(snapshot: dict) -> TelemetryEvent:
    hardware = snapshot["hardware"]
    event = TelemetryEvent.model_validate({
        "schema_version": snapshot["schema_version"], "device_id": snapshot["device_id"],
        **{key: hardware[key] for key in (
            "source_kind", "observed_at", "sequence", "temperature_c", "humidity_pct",
            "cooling_fault", "fault_is_simulated",
        )},
    })
    if event.observed_at.tzinfo is None:
        raise ValueError("The incident observation must have a timezone")
    if (not event.cooling_fault or snapshot["legacy_monitor"]["status"] != "NORMAL"
            or snapshot["expected_status"] != "WARNING"
            or "legacy_missed_fault" not in snapshot["reliability"]["reasons"]):
        raise ValueError("This demo repair supports only a recorded legacy_missed_fault cooling incident")
    return event


def test_summary(result: dict, workspace: Path) -> dict:
    def redact(value: str) -> str:
        return value.replace(sys.executable, "<python>").replace(str(workspace), "<repair-workspace>").replace(
            str(REPOSITORY_ROOT), "<repo>"
        )

    logs = {}
    for channel in ("stdout", "stderr"):
        # Paths originate in our trusted verifier, never in request input.
        with Path(result[channel + "_path"]).open("rb") as stream:
            raw = stream.read(32769)
        logs[channel] = redact(raw[:32768].decode("utf-8", errors="replace"))
        logs[channel + "_truncated"] = len(raw) > 32768
    cases = [{"name": case["name"], "outcome": case["outcome"]} for case in result["cases"]]
    return {
        **logs, "command": [redact(argument) for argument in result["command"]],
        "command_paths_redacted": True,
        "exit_code": result["exit_code"], "timed_out": result["timed_out"],
        "passed": sum(case["outcome"] == "passed" for case in cases),
        "failed": sum(case["outcome"] in ("failure", "error") for case in cases),
        "skipped": sum(case["outcome"] == "skipped" for case in cases), "cases": cases,
    }


def execute_incident_repair(snapshot: dict, output_root: Path) -> dict:
    event = incident_event(snapshot)
    proposal = create_demo_proposal(output_root)
    snapshot_revision = content_revision(snapshot)
    (proposal.workspace / "incident-snapshot.json").write_text(
        json.dumps({"snapshot_revision": snapshot_revision, "incident": snapshot}, indent=2) + "\n",
        encoding="utf-8",
    )
    report = verify_proposal(proposal, snapshot["incident_id"])
    result = {
        "repair_id": report["repair_id"], "verification_status": report["status"],
        "proposal_origin": report["proposal_origin"], "approval_status": "PENDING",
        "deployed": False, "target_binding": "representative_fixture",
        "original_revision": proposal.original_revision,
        "candidate_revision": proposal.candidate_revision,
        "diff_revision": proposal.diff_revision, "diff": proposal.diff.read_text(),
        "snapshot_revision": snapshot_revision,
        "tests": {label: test_summary(value, proposal.workspace) for label, value in report["tests"].items()},
        "replay": None,
    }
    if report["status"] == "VERIFIED":
        image_id = report["isolation"]["image_id"]
        original = run_docker_monitor(proposal.original, event, image_id,
                                      proposal.workspace / "incident-replay-containers.jsonl")
        candidate = run_docker_monitor(proposal.candidate, event, image_id,
                                       proposal.workspace / "incident-replay-containers.jsonl")
        reproduced = (original["status"] == snapshot["legacy_monitor"]["status"]
                      and candidate["status"] == snapshot["expected_status"]
                      and original["source_revision"] == proposal.original_revision
                      and candidate["source_revision"] == proposal.candidate_revision)
        result["replay"] = {
            "original": original, "candidate": candidate, "expected_status": snapshot["expected_status"],
            "detection_gap_fixed": reproduced, "cooling_fault_still_present": event.cooling_fault,
            "mode": "offline_snapshot_replay",
        }
        if not reproduced:
            result["verification_status"] = "INCIDENT_NOT_REPRODUCED"
        (proposal.workspace / "incident-replay.json").write_text(
            json.dumps(result["replay"], indent=2) + "\n", encoding="utf-8",
        )
    if (source_hash(proposal.original) != proposal.original_revision
            or source_hash(proposal.candidate) != proposal.candidate_revision
            or source_hash(proposal.diff) != proposal.diff_revision):
        result["verification_status"] = "SOURCE_CHANGED"
    # A separate API-oriented artifact; step 3's raw evidence remains intact.
    (proposal.workspace / "incident-repair-result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )
    return result

"""Cases remain usable across samples without rewriting their captured evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time

from fastapi.testclient import TestClient
import pytest

from backend.agents.gemini import GeminiConfig
from backend.agents.review import ReviewService, apply_review_policy, build_review_snapshot
from backend.agents.review_router import create_review_router
from backend.agents.review_schemas import (
    ReviewConclusion, case_revision, material_incident, review_is_current, same_case,
)
from backend.modernization.patching import create_model_proposal, source_hash
from backend.modernization.repository import content_revision
from backend.modernization.runner import LEGACY_MONITOR_PATH


def next_sample(incident, observed_at=None):
    updated = deepcopy(incident)
    hardware = updated["hardware"]
    observed = observed_at or datetime.fromisoformat(hardware["observed_at"]) + timedelta(seconds=1)
    hardware.update(sequence=hardware["sequence"] + 1, observed_at=observed.isoformat(),
                    received_at=observed.isoformat(), temperature_c=30.2, humidity_pct=55.1)
    updated["updated_at"] = observed.isoformat()
    if "sampled_at" in updated["legacy_monitor"]:
        updated["legacy_monitor"]["sampled_at"] = observed.isoformat()
    updated["reliability"]["observation_age_seconds"] = 0.02
    return updated


def conclusion():
    return ReviewConclusion(
        recommendation="ESCALATE", severity="HIGH", actions=["request_human_review"],
        evidence_ids=["retrieved-evidence"], repair_assessment="NO_CANDIDATE", risks=[],
        needs_human_approval=True, explanation="Review the simulated fault evidence.",
        fault_provenance="SIMULATED",
    )


def poll(client, path):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.01)
    pytest.fail("Scripted investigation/review did not finish")


def test_case_ignores_lifecycle_metadata_but_exact_capture_does_not(agent_snapshot):
    captured = material_incident(agent_snapshot)
    current = deepcopy(agent_snapshot)
    current.update(updated_at="2030-01-01T00:00:00+00:00", approval={"status": "PENDING"})
    current["investigation"] = {"job_id": "new-metadata", "status": "COMPLETED"}
    assert content_revision(material_incident(current)) != content_revision(captured)
    assert case_revision(current) == case_revision(captured)
    assert same_case(captured, current)


def test_case_accepts_new_equivalent_sample_without_mutating_capture(agent_snapshot):
    captured = material_incident(agent_snapshot)
    captured["legacy_monitor"]["sampled_at"] = captured["hardware"]["observed_at"]
    original = deepcopy(captured)
    current = next_sample(captured)
    assert content_revision(current) != content_revision(captured)
    assert case_revision(current) == case_revision(captured)
    assert same_case(captured, current)
    assert captured == original


@pytest.mark.parametrize("before,after", [
    (-10, -1), (0, 0), (0.1, 0.9), (1, 1), (29.4, 30.1), (35, 35), (36, 40),
])
def test_temperature_jitter_only_reuses_within_candidate_equivalence_band(agent_snapshot, before, after):
    agent_snapshot["hardware"]["temperature_c"] = before
    current = next_sample(agent_snapshot)
    current["hardware"]["temperature_c"] = after
    assert case_revision(agent_snapshot) == case_revision(current)
    assert same_case(agent_snapshot, current)


def test_temperature_boundary_points_and_intervals_are_all_distinct(agent_snapshot):
    revisions = set()
    for temperature in (-10, 0, 0.5, 1, 29.4, 35, 36):
        current = next_sample(agent_snapshot)
        current["hardware"]["temperature_c"] = temperature
        revisions.add(case_revision(current))
        if temperature != 29.4:
            assert not same_case(agent_snapshot, current)
    assert len(revisions) == 7


@pytest.mark.parametrize("temperature", [0, -10])
def test_allowlisted_candidate_with_zero_boundary_cannot_reuse_warm_fault_review(
    agent_snapshot, tmp_path, temperature,
):
    # This rule fits the bounded grammar and agrees with the expected repair on
    # the warm captured sample, but suppresses faults at zero/negative readings.
    assignment = ('status = "WARNING" if temperature > 35 or '
                  'event.get("cooling_fault", False) and temperature > False else "NORMAL"')
    proposal = create_model_proposal(assignment, source_hash(LEGACY_MONITOR_PATH), tmp_path)
    assert assignment in proposal.candidate.read_text()

    def candidate_status(value, cooling_fault):
        return "WARNING" if value > 35 or cooling_fault and value > False else "NORMAL"

    captured = material_incident(agent_snapshot)
    assert candidate_status(captured["hardware"]["temperature_c"], True) == "WARNING"
    assert candidate_status(temperature, True) == "NORMAL"
    current = next_sample(agent_snapshot)
    current["hardware"]["temperature_c"] = temperature
    revision = content_revision(captured)
    current["investigation"] = {"job_id": "investigation-1", "status": "COMPLETED", "snapshot_revision": revision}
    bundle = {"basis": {"investigation_job_id": "investigation-1", "incident_revision": revision,
                        "case_revision": case_revision(captured)}, "incident": captured, "candidate": None}
    assert not same_case(captured, current)
    assert not review_is_current(current, {"snapshot": {"review_input": bundle}})
    assert "incident_case_changed" in apply_review_policy(conclusion(), bundle, current)["reasons"]


def test_generation_zero_is_compatible_with_exact_legacy_capture(agent_snapshot):
    captured = material_incident(agent_snapshot)
    revision = content_revision(captured)
    current = deepcopy(agent_snapshot)
    current["case_generation"] = 0
    assert "case_generation" not in captured
    assert material_incident(current)["case_generation"] == 0
    assert content_revision(material_incident(current)) != revision
    assert case_revision(captured) == case_revision(current)
    assert same_case(captured, current)
    assert content_revision(captured) == revision


def test_case_generation_prevents_review_revival_after_fault_recurrence(agent_snapshot):
    captured = material_incident(agent_snapshot)
    revision = content_revision(captured)
    job = {"snapshot": {"review_input": {
        "basis": {"investigation_job_id": "investigation-1", "incident_revision": revision,
                  "case_revision": case_revision(captured)}, "incident": captured,
    }}}
    recovered = next_sample(agent_snapshot)
    recovered.update(case_generation=1, expected_status="NORMAL")
    recovered["hardware"]["cooling_fault"] = False
    recovered["reliability"].update(mismatch=False, reasons=[])
    recurring = next_sample(recovered)
    recurring.update(case_generation=2, expected_status="WARNING")
    recurring["hardware"]["cooling_fault"] = True
    recurring["reliability"].update(mismatch=True, reasons=["legacy_missed_fault"])
    recurring["investigation"] = {
        "job_id": "investigation-1", "status": "COMPLETED", "snapshot_revision": revision,
    }
    # Without the generation, both fault states would describe the same case.
    without_generation = {key: value for key, value in recurring.items() if key != "case_generation"}
    assert same_case(captured, without_generation)
    assert case_revision(captured) != case_revision(recurring)
    assert not same_case(captured, recurring)
    assert not review_is_current(recurring, job)


@pytest.mark.parametrize("section,key,value", [
    (None, "incident_id", "INC-OTHER"),
    (None, "device_id", "RACK-OTHER"),
    (None, "created_at", "2020-01-01T00:00:00+00:00"),
    (None, "status", "RESOLVED"),
    (None, "severity", "CRITICAL"),
    (None, "case_generation", 1),
    ("hardware", "cooling_fault", False),
    ("hardware", "source_kind", "arduino_serial"),
    ("hardware", "fault_is_simulated", False),
    ("hardware", "temperature_c", 35.01),
    ("legacy_monitor", "status", "WARNING"),
    ("legacy_monitor", "source_revision", "sha256:actual-executed-source"),
    (None, "expected_status", "NORMAL"),
    ("reliability", "mismatch", False),
    ("reliability", "reasons", ["stale_hardware_reading", "legacy_missed_fault"]),
    ("reliability", "evidence_quality", "PARTIAL"),
])
def test_meaningful_case_changes_invalidate_old_evidence(agent_snapshot, section, key, value):
    current = next_sample(agent_snapshot)
    target = current if section is None else current[section]
    target[key] = value
    assert case_revision(current) != case_revision(agent_snapshot)
    assert not same_case(agent_snapshot, current)


@pytest.mark.parametrize("change", ["sequence_only", "in_place_measurement", "replay", "backdated"])
def test_case_matching_rejects_changed_sample_identity_and_replay(agent_snapshot, change):
    current = next_sample(agent_snapshot)
    if change == "sequence_only":
        current["hardware"] = deepcopy(agent_snapshot["hardware"])
        current["hardware"]["sequence"] += 1
    elif change == "in_place_measurement":
        current["hardware"] = deepcopy(agent_snapshot["hardware"])
        current["hardware"]["temperature_c"] += 0.1
    elif change == "replay":
        current["hardware"]["sequence"] = 0
    else:
        current["hardware"]["observed_at"] = "2020-01-01T00:00:00+00:00"
    assert case_revision(current) == case_revision(agent_snapshot)
    assert not same_case(agent_snapshot, current)


def test_freshness_uses_compatible_live_sample_and_preserves_frozen_bundle(agent_snapshot):
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    agent_snapshot["hardware"].update(observed_at=old.isoformat(), received_at=old.isoformat())
    bundle = {"incident": material_incident(agent_snapshot), "candidate": None}
    frozen = deepcopy(bundle)
    current = next_sample(agent_snapshot, datetime.now(timezone.utc))
    assert apply_review_policy(conclusion(), bundle)["requires_fresh_telemetry"]
    policy = apply_review_policy(conclusion(), bundle, current)
    assert not policy["requires_fresh_telemetry"]
    assert policy["freshness_basis"] == "compatible_current_telemetry"
    assert policy["freshness_observed_at"] == current["hardware"]["observed_at"]
    assert policy["observation_age_seconds"] < 2
    assert bundle == frozen
    current["hardware"]["cooling_fault"] = False
    rejected = apply_review_policy(conclusion(), bundle, current)
    assert rejected["requires_fresh_telemetry"]
    assert "incident_case_changed" in rejected["reasons"]
    assert rejected["freshness_basis"] == "captured_incident"


def test_review_currentness_binds_canonical_investigation_and_exact_capture(agent_snapshot):
    captured = material_incident(agent_snapshot)
    revision = content_revision(captured)
    job = {"snapshot": {"review_input": {
        "basis": {"investigation_job_id": "investigation-1", "incident_revision": revision,
                  "case_revision": case_revision(captured)}, "incident": captured,
    }}}
    current = next_sample(agent_snapshot)
    current["investigation"] = {"job_id": "investigation-1", "status": "COMPLETED", "snapshot_revision": revision}
    assert review_is_current(current, job)
    current["investigation"]["job_id"] = "investigation-2"
    assert not review_is_current(current, job)
    current["investigation"]["job_id"] = "investigation-1"
    job["snapshot"]["review_input"]["incident"]["hardware"]["humidity_pct"] += 0.1
    assert not review_is_current(current, job)


def test_investigation_reuses_same_case_and_review_keeps_original_evidence(agent_system):
    app, base, service, clients = agent_system()
    with TestClient(app) as client:
        queued = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        source = poll(client, queued.json()["links"]["job"])
        assert source["status"] == "COMPLETED", source
        captured = deepcopy(source["snapshot"])
        base.incidents["INC-AGENT-TEST"] = next_sample(base.incidents["INC-AGENT-TEST"])
        base.incidents["INC-AGENT-TEST"]["case_generation"] = 0
        repeated = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        assert repeated.status_code == 200 and repeated.json()["reused"]
        assert repeated.json()["job_id"] == source["job_id"] and len(clients) == 1
        snapshot = build_review_snapshot(base.get_incident_snapshot("INC-AGENT-TEST"), service.repository)
        assert snapshot["review_input"]["incident"] == captured
        assert snapshot["review_input"]["basis"]["incident_revision"] == content_revision(captured)
        assert snapshot["hardware"] != captured["hardware"]
        assert service.repository.get_job(source["job_id"])["snapshot"] == captured
        base.incidents["INC-AGENT-TEST"]["legacy_monitor"]["source_revision"] = "sha256:actual-source"
        new_request = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        assert new_request.json()["job_id"] != source["job_id"]
        assert poll(client, new_request.json()["links"]["job"])["status"] == "COMPLETED"


def test_review_stays_current_across_live_samples_then_stales_on_source_change(agent_system, tmp_path):
    app, base, investigation, _ = agent_system()
    seen = []

    class ScriptedReviewer:
        def review(self, bundle, prompt, schema):
            seen.append(deepcopy(bundle))
            result = conclusion().model_dump()
            result["evidence_ids"] = [item["evidence_id"] for item in bundle["evidence"]]
            return json.dumps(result), {"response_id": "scripted-review"}

        def close(self):
            pass

    review = ReviewService(base.for_reviews(), base.for_investigations(), tmp_path / "reviews",
                           lambda config: ScriptedReviewer(), lambda: GeminiConfig(api_key="test-review-key"))
    app.include_router(create_review_router(review))
    with TestClient(app) as client:
        response = client.post("/api/incidents/INC-AGENT-TEST/investigate")
        source = poll(client, response.json()["links"]["job"])
        base.incidents["INC-AGENT-TEST"] = next_sample(base.incidents["INC-AGENT-TEST"])
        response = client.post("/api/incidents/INC-AGENT-TEST/review")
        assert response.status_code == 202, response.text
        completed = poll(client, response.json()["links"]["job"])
        assert completed["status"] == "COMPLETED" and completed["current"]
        assert seen[0]["incident"] == source["snapshot"]
        base.incidents["INC-AGENT-TEST"] = next_sample(base.incidents["INC-AGENT-TEST"])
        current = client.get(completed["links"]["job"]).json()
        assert current["current"] and current["status"] == "COMPLETED"
        assert current["result"]["policy"]["freshness_basis"] == "compatible_current_telemetry"
        retry = client.post("/api/incidents/INC-AGENT-TEST/review")
        assert retry.status_code == 200 and retry.json()["job_id"] == completed["job_id"]
        assert len(seen) == 1
        base.incidents["INC-AGENT-TEST"]["legacy_monitor"]["source_revision"] = "sha256:actual-source"
        stale = client.get(completed["links"]["job"]).json()
        assert stale["status"] == "STALE" and not stale["current"]
        assert client.post("/api/incidents/INC-AGENT-TEST/review").status_code == 409

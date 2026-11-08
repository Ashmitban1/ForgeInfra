"""Reuse the actual approval gate with explicitly scripted model/Docker evidence."""
import importlib.util
from pathlib import Path

import pytest
import mongomock

from backend.repairproof.repository import ProofRepository
from backend.repairproof.router import create_repairproof_router
from backend.repairproof.service import RepairProofService

spec = importlib.util.spec_from_file_location("proof_approval_fixtures", Path(__file__).parents[1] / "modernization/test_approval_api.py")
approval_fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approval_fixtures)
approval_system = approval_fixtures.approval_system


@pytest.fixture
def proof_system(approval_system, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.modernization.approval_auth import Reviewer
    app, base, gate, snapshot = approval_system()
    db = mongomock.MongoClient().factoryos_proof_tests
    repository = ProofRepository(db)
    service = RepairProofService(gate, repository, enabled_factory=lambda: True)
    app.include_router(create_repairproof_router(service))
    with TestClient(app) as client:
        view, source, review = approval_fixtures.prepare(client)
        result = client.post(approval_fixtures.PATH, headers=approval_fixtures.ALICE,
                             json=approval_fixtures.decision(view))
        assert result.status_code == 201, result.text
        # The fake DB ack is explicit; no live MongoDB or provider is contacted.
        raw_get = base.get_incident_snapshot
        def persisted(incident_id):
            incident = raw_get(incident_id)
            incident["approval_persistence"] = {"status": "PERSISTED", "version": incident["approval"]["version"]}
            return incident
        monkeypatch.setattr(base, "get_incident_snapshot", persisted)
        incident = persisted("INC-AGENT-TEST")
        db.incidents.insert_one(incident)
        from backend.repairproof.router import PublishRequest
        request = PublishRequest(decision_id=result.json()["recorded_decision"]["decision_id"],
                                 package_revision=view["package_revision"], candidate_revision=view["candidate_revision"])
        yield service, client, request, Reviewer("alice"), db, base, source, review

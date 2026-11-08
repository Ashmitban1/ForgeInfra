"""Approval state/auth tests use explicitly scripted verifier and model responses."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from threading import Barrier
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.agents.gemini import GeminiConfig
from backend.agents.review import ReviewService
from backend.agents.review_router import create_review_router
from backend.agents.router import create_investigation_router
from backend.agents import tools as tools_module
from backend.modernization import approval as approval_module
from backend.modernization.approval import ApprovalConflict, ApprovalService
from backend.modernization.approval_auth import token_digest
from backend.modernization.approval_router import create_approval_router
from backend.modernization.repository import content_revision
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService
from backend.modernization.testing import EXPECTED_CASES

ALICE_TOKEN = 'unit-test-only-alice-credential-000000000000'
BOB_TOKEN = 'unit-test-only-bob-credential-00000000000000'
ALICE = {'Authorization': 'Bearer ' + ALICE_TOKEN}
BOB = {'Authorization': 'Bearer ' + BOB_TOKEN}
PATH = '/api/incidents/INC-AGENT-TEST/approval'


def scripted_verifier(snapshot, output_root, proposal):
    """Unit fixture only: actual verifier is exercised separately with Docker."""
    cases = [{'name': name, 'outcome': 'passed'} for name in sorted(EXPECTED_CASES)]
    original = deepcopy(cases)
    next(case for case in original if case['name'] == 'test_cooling_fault_requires_warning')['outcome'] = 'failure'
    return {
        'repair_id': proposal.workspace.name, 'proposal_origin': 'nemotron_generated_patch',
        'verification_status': 'VERIFIED', 'original_revision': proposal.original_revision,
        'candidate_revision': proposal.candidate_revision, 'diff_revision': proposal.diff_revision,
        'diff': proposal.diff.read_text(), 'snapshot_revision': content_revision(snapshot),
        'approval_status': 'PENDING', 'deployed': False,
        'tests': {
            'original': {'exit_code': 1, 'passed': 4, 'failed': 1, 'skipped': 0, 'cases': original,
                         'stdout': 'SCRIPTED UNIT VERIFIER: monitor returned NORMAL'},
            'candidate': {'exit_code': 0, 'passed': 5, 'failed': 0, 'skipped': 0, 'cases': cases, 'stdout': 'SCRIPTED UNIT VERIFIER'},
        },
        'replay': {'original': {'status': 'NORMAL', 'source_revision': proposal.original_revision},
                   'candidate': {'status': 'WARNING', 'source_revision': proposal.candidate_revision},
                   'detection_gap_fixed': True, 'cooling_fault_still_present': True},
    }


class ScriptedReviewer:
    def __init__(self, config):
        self.config = config

    def review(self, bundle, prompt, schema):
        return json.dumps({
            'recommendation': 'REQUEST_REPAIR_REVIEW', 'severity': 'HIGH',
            'actions': ['request_human_review'], 'evidence_ids': [e['evidence_id'] for e in bundle['evidence']],
            'repair_assessment': 'SUITABLE_FOR_HUMAN_REVIEW', 'risks': ['Simulated signal; physical health unverified.'],
            'needs_human_approval': True, 'explanation': 'Scripted independent review for approval gate tests.',
            'fault_provenance': 'SIMULATED',
        }), {'status': 'SUCCESS', 'response_id': 'scripted-approval-review', 'model': self.config.model}

    def close(self):
        pass


def poll(client, path):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        job = response.json()
        if job['status'] not in ('QUEUED', 'RUNNING'):
            assert job['status'] == 'COMPLETED', job
            return job
        time.sleep(0.01)
    pytest.fail('Scripted investigation/review timed out')


@pytest.fixture
def approval_system(tmp_path, monkeypatch):
    # Reuse the test-only provider definitions, never ignored live artifacts.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('approval_test_agents', Path(__file__).parents[1] / 'agents/conftest.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    agent_snapshot = fixtures.agent_snapshot.__wrapped__()
    make_agent = fixtures.agent_system.__wrapped__(tmp_path, agent_snapshot)
    monkeypatch.setenv('FACTORYOS_APPROVERS_JSON', json.dumps({
        'alice': token_digest(ALICE_TOKEN), 'bob': token_digest(BOB_TOKEN),
    }))

    def make(repository=None, real_verifier=False):
        if not real_verifier:
            monkeypatch.setattr(tools_module, 'execute_incident_repair', scripted_verifier)
        unused, base, investigation, clients = make_agent('patch', repository=repository)
        review = ReviewService(base.for_reviews(), base.for_investigations(), tmp_path / 'approval-reviews',
                               ScriptedReviewer, lambda: GeminiConfig(api_key='unit-test-google-key'))
        gate = ApprovalService(base, base.for_investigations(), review)
        repair = RepairService(base, tmp_path / 'approval-repairs')
        app = FastAPI()
        app.include_router(create_modernization_router(repair, investigation, review, gate))
        app.include_router(create_investigation_router(investigation, review, gate))
        app.include_router(create_review_router(review))
        app.include_router(create_approval_router(gate))
        return app, base, gate, agent_snapshot
    return make


def prepare(client, review=True):
    queued = client.post('/api/incidents/INC-AGENT-TEST/investigate')
    assert queued.status_code == 202, queued.text
    source = poll(client, queued.json()['links']['job'])
    reviewed = None
    if review:
        queued = client.post('/api/incidents/INC-AGENT-TEST/review')
        assert queued.status_code == 202, queued.text
        reviewed = poll(client, queued.json()['links']['job'])
    response = client.get(PATH, headers=ALICE)
    assert response.status_code == 200, response.text
    return response.json(), source, reviewed


def decision(view, action='APPROVE', comment='Reviewed the exact diff and test evidence.'):
    return {'decision': action, 'package_revision': view['package_revision'],
            'candidate_revision': view['candidate_revision'], 'comment': comment}


def test_approval_identity_audit_binding_and_execution_guard(approval_system):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        assert view['can_approve'] and view['can_reject'] and view['status'] == 'PENDING', view
        with pytest.raises(ApprovalConflict):
            gate.require_approved('INC-AGENT-TEST', view['package_revision'], view['candidate_revision'])
        response = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'decision-1'}, json=decision(view))
        assert response.status_code == 201, response.text
        result = response.json()
        assert result['status'] == 'APPROVED' and not result['reused'] and not result['deployed']
        record = result['recorded_decision']
        assert record['reviewer_id'] == 'alice' and record['decided_at']
        history = client.get(PATH + '/history', headers=BOB).json()
        assert history['version'] == 1 and len(history['packages']) == len(history['decisions']) == 1
        package = history['packages'][0]
        assert content_revision(package['data']) == view['package_revision']
        assert package['data']['binding']['investigation_job_id'] == source['job_id']
        assert package['data']['binding']['review_job_id'] == reviewed['job_id']
        authorized = gate.require_approved('INC-AGENT-TEST', view['package_revision'], view['candidate_revision'])
        assert authorized['decision']['decision_id'] == record['decision_id']
        summary = client.get('/api/incidents/INC-AGENT-TEST/analysis').json()['approval']
        assert summary['status'] == 'APPROVED'
        incident = base.get_incident_snapshot('INC-AGENT-TEST')
        assert incident['status'] == 'OPEN' and incident['decision_review']['approval_status'] == 'PENDING'
        assert ALICE_TOKEN not in str(history) and BOB_TOKEN not in str(history)
        assert 'approval' not in RepairService(base).prepare_snapshot(incident)


def test_idempotency_is_actor_scoped_and_final_decisions_cannot_be_overwritten(approval_system):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        body = decision(view)
        first = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'same'}, json=body).json()
        repeated = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'same'}, json=body)
        assert repeated.status_code == 200 and repeated.json()['reused']
        assert repeated.json()['recorded_decision']['decision_id'] == first['recorded_decision']['decision_id']
        changed = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'same'}, json=decision(view, 'REJECT'))
        assert changed.status_code == 409
        assert client.post(PATH, headers={**BOB, 'Idempotency-Key': 'same'}, json=body).status_code == 409
        assert len(client.get(PATH + '/history', headers=ALICE).json()['decisions']) == 1


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Basic ignored'}])
def test_unauthorized_access_cannot_read_or_create_decisions(approval_system, headers):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        assert client.get(PATH, headers=headers).status_code == 401
        assert client.get(PATH + '/history', headers=headers).status_code == 401
        body = {'decision': 'APPROVE', 'package_revision': 'sha256:' + '0' * 64, 'candidate_revision': 'sha256:' + '0' * 64}
        response = client.post(PATH, headers=headers, json=body)
        assert response.status_code == 401 and response.headers['www-authenticate'] == 'Bearer'
        assert 'approval' not in base.get_incident_snapshot('INC-AGENT-TEST')


def test_authentication_is_not_configured_by_model_keys_or_client_actor_ids(approval_system, monkeypatch):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        assert client.post(PATH, headers=ALICE, json={**decision(view), 'reviewer_id': 'forged'}).status_code == 422
        monkeypatch.delenv('FACTORYOS_APPROVERS_JSON')
        assert not client.get('/api/agents/capabilities').json()['approval_configured']
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 503
        assert 'approval' not in base.get_incident_snapshot('INC-AGENT-TEST')


@pytest.mark.parametrize('change', ['candidate', 'diff', 'review', 'tests'])
def test_changed_package_cannot_use_old_expected_revision(approval_system, change):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        raw = base.for_investigations().jobs[source['job_id']]['result']['generated_repair']
        if change == 'candidate':
            raw['candidate_revision'] = 'sha256:' + '1' * 64
        elif change == 'diff':
            raw['diff'] += '\n# changed'
        elif change == 'tests':
            raw['tests']['candidate']['exit_code'] = 1
        else:
            base.for_reviews().jobs[reviewed['job_id']]['result']['explanation'] += ' changed'
        response = client.post(PATH, headers=ALICE, json=decision(view))
        assert response.status_code == 409 and 'approval' not in base.get_incident_snapshot('INC-AGENT-TEST')


@pytest.mark.parametrize('blocked', ['missing_review', 'failed_tests', 'stale_input', 'legacy_review'])
def test_rejection_available_when_approval_is_blocked(approval_system, blocked):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        unused, source, reviewed = prepare(client, review=blocked != 'missing_review')
        if blocked == 'failed_tests':
            base.for_investigations().jobs[source['job_id']]['result']['generated_repair']['verification_status'] = 'CANDIDATE_FAILED'
        elif blocked == 'stale_input':
            base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        elif blocked == 'legacy_review':
            base.for_reviews().jobs[reviewed['job_id']]['result'].pop('fault_provenance')
        view = client.get(PATH, headers=ALICE).json()
        assert not view['can_approve'] and view['can_reject']
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 409
        rejected = client.post(PATH, headers=ALICE, json=decision(view, 'REJECT', 'Evidence insufficient.'))
        assert rejected.status_code == 201 and rejected.json()['status'] == 'REJECTED', rejected.text
        with pytest.raises(ApprovalConflict):
            gate.require_approved('INC-AGENT-TEST', view['package_revision'], view['candidate_revision'])


def test_recorded_approval_becomes_stale_and_retry_retains_audit(approval_system):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        body = decision(view)
        assert client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'retry-after-change'}, json=body).status_code == 201
        base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        assert client.get(PATH, headers=ALICE).json()['status'] == 'STALE'
        assert client.get('/api/incidents/INC-AGENT-TEST/analysis').json()['approval']['status'] == 'STALE'
        repeated = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'retry-after-change'}, json=body)
        assert repeated.status_code == 200 and repeated.json()['status'] == 'STALE' and repeated.json()['reused']
        with pytest.raises(ApprovalConflict):
            gate.require_approved('INC-AGENT-TEST', view['package_revision'], view['candidate_revision'])
        assert len(client.get(PATH + '/history', headers=ALICE).json()['decisions']) == 1


def test_aged_evidence_blocks_approval_even_if_package_hash_is_unchanged(approval_system, monkeypatch):
    from backend.agents import review as review_module
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return later
        monkeypatch.setattr(review_module, 'datetime', Later)
        fresh_view = client.get(PATH, headers=ALICE).json()
        assert fresh_view['package_revision'] == view['package_revision']
        assert 'fresh_telemetry_required' in fresh_view['blocking_reasons']
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 409


def test_execution_guard_blocks_a_revoked_reviewer(approval_system, monkeypatch):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 201
        monkeypatch.setenv('FACTORYOS_APPROVERS_JSON', json.dumps({'bob': token_digest(BOB_TOKEN)}))
        current = client.get(PATH, headers=BOB).json()
        assert current['status'] == 'STALE' and 'approving_reviewer_no_longer_authorized' in current['blocking_reasons']
        with pytest.raises(ApprovalConflict):
            gate.require_approved('INC-AGENT-TEST', view['package_revision'], view['candidate_revision'])


def test_conflicting_concurrent_decisions_do_not_overwrite_each_other(approval_system, monkeypatch):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        barrier = Barrier(2)
        original_save = base.save_approval
        def racing_save(*args):
            barrier.wait(timeout=5)
            return original_save(*args)
        monkeypatch.setattr(base, 'save_approval', racing_save)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.post, PATH, headers=headers, json=decision(view, action))
                       for headers, action in [(ALICE, 'APPROVE'), (BOB, 'REJECT')]]
            responses = [future.result() for future in futures]
        assert sorted(r.status_code for r in responses) == [201, 409]
        history = client.get(PATH + '/history', headers=ALICE).json()
        assert history['version'] == 1 and len(history['decisions']) == len(history['packages']) == 1


def test_telemetry_change_during_commit_is_rejected_atomically(approval_system, monkeypatch):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        original_save = base.save_approval
        def changed_save(*args):
            base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
            return original_save(*args)
        monkeypatch.setattr(base, 'save_approval', changed_save)
        response = client.post(PATH, headers=ALICE, json=decision(view))
        assert response.status_code == 409
        assert 'approval' not in base.get_incident_snapshot('INC-AGENT-TEST')


def test_target_revision_change_blocks_gate(approval_system, monkeypatch, tmp_path):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        changed = tmp_path / 'new-target.py'
        changed.write_text('# a new baseline')
        monkeypatch.setattr(approval_module, 'LEGACY_MONITOR_PATH', changed)
        response = client.post(PATH, headers=ALICE, json=decision(view))
        assert response.status_code == 409 and 'target_source_revision_changed' in response.json()['detail']['reasons']


def test_storage_errors_are_safe_on_approval_and_analysis(approval_system, monkeypatch):
    from pymongo.errors import PyMongoError
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        prepare(client)
        def unavailable(*args):
            raise PyMongoError('private-database-url')
        monkeypatch.setattr(gate.investigations, 'get_job', unavailable)
        for path, headers in [(PATH, ALICE), ('/api/incidents/INC-AGENT-TEST/analysis', {})]:
            response = client.get(path, headers=headers)
            assert response.status_code == 503 and 'private-database-url' not in response.text


def test_review_must_bind_the_exact_investigation_result(approval_system):
    app, base, gate, snapshot = approval_system()
    with TestClient(app) as client:
        unused, source, reviewed = prepare(client)
        base.for_investigations().jobs[source['job_id']]['result']['summary'] += ' changed after review'
        view = client.get(PATH, headers=ALICE).json()
        assert 'reviewed_evidence_changed' in view['blocking_reasons']
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 409


@pytest.mark.parametrize('configuration', ['', '{}', '{"alice":"plaintext-secret"}'])
def test_invalid_reviewer_configuration_fails_closed(approval_system, monkeypatch, configuration):
    app, base, gate, snapshot = approval_system()
    monkeypatch.setenv('FACTORYOS_APPROVERS_JSON', configuration)
    with TestClient(app) as client:
        response = client.get(PATH, headers=ALICE)
        assert response.status_code == 503 and 'plaintext-secret' not in response.text


@pytest.fixture
def approval_mongo_database(request):
    if not request.config.getoption('--run-mongo-tests'):
        pytest.skip('Enable disposable local MongoDB checks with --run-mongo-tests')
    from pymongo import MongoClient
    import uuid
    uri = os.environ.get('FACTORYOS_TEST_MONGO_URI', '')
    if not uri.startswith(('mongodb://127.0.0.1:', 'mongodb://localhost:')):
        pytest.fail('Use a disposable local FACTORYOS_TEST_MONGO_URI')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    client.admin.command('ping')
    name = 'factoryos_approval_test_' + uuid.uuid4().hex
    try:
        yield client[name]
    finally:
        client.drop_database(name)
        client.close()


def test_mongo_decision_and_frozen_package_persist_atomically(approval_system, approval_mongo_database):
    from backend.modernization.mongo_repository import MongoIncidentRepository
    database = approval_mongo_database
    # Obtain a fresh synthetic incident from the same test provider fixture.
    unused, memory, unused_gate, snapshot = approval_system()
    database.incidents.insert_one(deepcopy(snapshot))
    repository = MongoIncidentRepository(database.incidents, database.repair_jobs)
    app, base, gate, snapshot = approval_system(repository=repository)
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        response = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'mongo-persist'}, json=decision(view))
        assert response.status_code == 201, response.text
        stored = database.incidents.find_one({})
        assert stored['approval']['version'] == 1
        assert len(stored['approval']['packages']) == len(stored['approval']['decisions']) == 1
        assert stored['approval']['decisions'][0]['reviewer_id'] == 'alice'
        assert stored['status'] == 'OPEN'
        assert stored['investigation']['job_id'] == source['job_id']
        assert stored['decision_review']['job_id'] == reviewed['job_id']
    recreated = MongoIncidentRepository(database.incidents, database.repair_jobs)
    second, base, gate, snapshot = approval_system(repository=recreated)
    with TestClient(second) as client:
        assert client.get(PATH, headers=ALICE).json()['status'] == 'APPROVED'
        repeated = client.post(PATH, headers={**ALICE, 'Idempotency-Key': 'mongo-persist'}, json=decision(view))
        assert repeated.status_code == 200 and repeated.json()['reused']
        assert len(client.get(PATH + '/history', headers=ALICE).json()['decisions']) == 1


def test_mongo_compare_and_swap_rejects_concurrent_telemetry(approval_system, approval_mongo_database, monkeypatch):
    from backend.modernization.mongo_repository import MongoIncidentRepository
    database = approval_mongo_database
    unused, memory, unused_gate, snapshot = approval_system()
    database.incidents.insert_one(deepcopy(snapshot))
    repository = MongoIncidentRepository(database.incidents, database.repair_jobs)
    app, base, gate, snapshot = approval_system(repository=repository)
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        original_update = database.incidents.update_one
        changed = False
        def update_with_race(query, update, **kwargs):
            nonlocal changed
            if 'approval' in update.get('$set', {}) and not changed:
                changed = True
                original_update({'incident_id': 'INC-AGENT-TEST'}, {'$inc': {'hardware.sequence': 1}})
            return original_update(query, update, **kwargs)
        monkeypatch.setattr(repository.incidents, 'update_one', update_with_race)
        response = client.post(PATH, headers=ALICE, json=decision(view))
        assert response.status_code == 409
        assert 'approval' not in database.incidents.find_one({})


def test_real_docker_proof_can_pass_the_human_gate(approval_system, request):
    if not request.config.getoption('--run-docker-tests'):
        pytest.skip('Enable actual Docker verifier with --run-docker-tests')
    app, base, gate, snapshot = approval_system(real_verifier=True)
    with TestClient(app) as client:
        view, source, reviewed = prepare(client)
        assert view['can_approve'], view
        assert client.post(PATH, headers=ALICE, json=decision(view)).status_code == 201

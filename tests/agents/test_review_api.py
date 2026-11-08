from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from threading import Event
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.agents.gemini import GeminiClient, GeminiConfig, GeminiError, MODEL
from backend.agents.review import ReviewService, apply_review_policy
from backend.agents.review_router import create_review_router
from backend.agents.review_schemas import ReviewConclusion
from backend.agents.router import create_investigation_router
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService
from backend.modernization.mongo_repository import MongoIncidentRepository


def poll(client, path, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        job = response.json()
        if job['status'] not in ('QUEUED', 'RUNNING'):
            return job
        time.sleep(0.01)
    pytest.fail('Review/investigation did not finish')


@pytest.fixture
def review_system(agent_system, tmp_path):
    def make(mode='normal', investigation_mode='normal', repository=None, config_factory=None, block=None):
        original, base, investigation, clients = agent_system(investigation_mode, repository=repository)
        seen = []
        def transport(request):
            payload = json.loads(request.content)
            bundle = json.loads(payload['contents'][0]['parts'][0]['text'])
            seen.append(bundle)
            if block:
                block[0].set()
                assert block[1].wait(5), 'Test must release the blocked provider'
            if mode == 'auth':
                return httpx.Response(403, json={'error': {'message': 'test-gemini-secret'}})
            candidate = bundle['candidate']
            conclusion = {
                'recommendation': 'REQUEST_REPAIR_REVIEW' if candidate else 'ESCALATE', 'severity': 'HIGH',
                'actions': ['inspect_equipment', 'request_human_review'],
                'evidence_ids': [item['evidence_id'] for item in bundle['evidence']],
                'repair_assessment': 'SUITABLE_FOR_HUMAN_REVIEW' if candidate else 'NO_CANDIDATE',
                'risks': ['The fault input is simulated; software verification does not repair equipment.'],
                'needs_human_approval': True, 'explanation': 'Review the captured mismatch and independently verified candidate if present.',
            }
            if mode == 'unknown_evidence':
                conclusion['evidence_ids'] = ['invented-evidence']
            if mode == 'unsafe_action':
                conclusion['actions'] = ['deploy_production']
            if mode == 'no_approval':
                conclusion['needs_human_approval'] = False
            if mode == 'leak':
                conclusion['explanation'] += ' test-gemini-secret'
            if mode == 'disagree':
                conclusion.update(recommendation='NO_ACTION', repair_assessment='SUITABLE_FOR_HUMAN_REVIEW')
            text = 'invalid JSON' if mode == 'bad_json' else json.dumps(conclusion)
            return httpx.Response(200, json={
                'responseId': 'scripted-review-response', 'modelVersion': MODEL,
                'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}],
                'usageMetadata': {'totalTokenCount': 100},
            })
        config_factory = config_factory or (lambda: GeminiConfig(api_key='test-gemini-secret'))
        review = ReviewService(base.for_reviews(), base.for_investigations(), tmp_path / 'reviews',
                               lambda config: GeminiClient(config, httpx.MockTransport(transport)), config_factory)
        app = FastAPI()
        app.include_router(create_modernization_router(RepairService(base, tmp_path / 'repairs'), investigation, review))
        app.include_router(create_investigation_router(investigation, review))
        app.include_router(create_review_router(review))
        return app, base, review, seen
    return make


def investigate(client):
    response = client.post('/api/incidents/INC-AGENT-TEST/investigate')
    assert response.status_code == 202, response.text
    job = poll(client, response.json()['links']['job'])
    assert job['status'] == 'COMPLETED', job
    return job


def submit_review(client):
    response = client.post('/api/incidents/INC-AGENT-TEST/review', headers={'Idempotency-Key': 'review-once'})
    assert response.status_code == 202, response.text
    return poll(client, response.json()['links']['job'])


def test_review_evidence_is_real_shared_and_idempotent(review_system):
    app, base, review, seen = review_system()
    with TestClient(app) as client:
        source = investigate(client)
        job = submit_review(client)
        assert job['status'] == 'COMPLETED', job
        assert job['current'] and job['result']['recommendation'] == 'ESCALATE'
        assert job['result']['policy']['actions_executed'] == []
        assert job['provider_calls'][0]['response_id'] == 'scripted-review-response'
        assert seen[0]['basis']['investigation_job_id'] == source['job_id']
        assert seen[0]['incident'] == source['snapshot']
        assert 'decision_review' not in seen[0]['incident']
        assert 'status = "WARNING"' in str(seen[0]['evidence'])
        assert len(base.jobs) == 0 and len(base.for_investigations().jobs) == 1
        summary = client.get(job['links']['analysis']).json()['decision_review']
        assert summary['status'] == 'COMPLETED' and summary['recommendation'] == 'ESCALATE'
        assert summary['approval_status'] == 'PENDING' and not summary['deployed']
        assert base.get_incident_snapshot('INC-AGENT-TEST')['decision_review']['job_id'] == job['job_id']
        repeated = client.post('/api/incidents/INC-AGENT-TEST/review', headers={'Idempotency-Key': 'review-once'})
        assert repeated.status_code == 200 and repeated.json()['job_id'] == job['job_id'] and repeated.json()['reused']
        assert len(seen) == 1
        capabilities = client.get('/api/agents/capabilities').json()
        assert capabilities['gemini'] and capabilities['gemini_configured']
        assert client.get('/api/reviews/INC-AGENT-TEST').status_code == 404


def test_review_requires_completed_current_investigation(review_system):
    app, base, review, seen = review_system()
    with TestClient(app) as client:
        assert client.post('/api/incidents/missing/review').status_code == 404
        assert client.post('/api/incidents/INC-AGENT-TEST/review').status_code == 409
        investigate(client)
        base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        response = client.post('/api/incidents/INC-AGENT-TEST/review')
        assert response.status_code == 409 and 'fresh investigation' in response.json()['detail']
        assert review.repository.jobs == {} and seen == []


def test_changed_tool_evidence_cannot_be_reviewed(review_system):
    app, base, review, seen = review_system()
    with TestClient(app) as client:
        source = investigate(client)
        raw = base.for_investigations().jobs[source['job_id']]
        raw['tool_calls'][0]['result']['incident']['expected_status'] = 'NORMAL'
        response = client.post('/api/incidents/INC-AGENT-TEST/review')
        assert response.status_code == 409 and seen == []


def test_missing_gemini_credentials_fail_before_queueing(review_system):
    def missing():
        raise GeminiError('NOT_CONFIGURED', 'Configure GEMINI_API_KEY')
    app, base, review, seen = review_system(config_factory=missing)
    with TestClient(app) as client:
        investigate(client)
        assert not client.get('/api/agents/capabilities').json()['gemini_configured']
        assert client.post('/api/incidents/INC-AGENT-TEST/review').status_code == 503
        assert review.repository.jobs == {} and seen == []


@pytest.mark.parametrize('mode', ['bad_json', 'unknown_evidence', 'unsafe_action', 'no_approval', 'auth'])
def test_invalid_recommendations_never_become_completed_reviews(review_system, mode):
    app, base, review, seen = review_system(mode)
    with TestClient(app) as client:
        investigate(client)
        job = submit_review(client)
        assert job['status'] == 'FAILED' and job['result'] is None
        assert job['error']['code'] in {'INVALID_REVIEW', 'PROVIDER_ACCESS'}
        summary = client.get(job['links']['analysis']).json()['decision_review']
        assert summary['status'] == 'FAILED' and summary['recommendation'] is None
        assert 'test-gemini-secret' not in str(job) + str(summary)


def test_secret_redaction_in_valid_model_output(review_system):
    app, base, review, seen = review_system('leak')
    with TestClient(app) as client:
        investigate(client)
        job = submit_review(client)
        assert job['status'] == 'COMPLETED'
        assert 'test-gemini-secret' not in str(job)
        assert '[REDACTED]' in job['result']['explanation']


def test_changed_evidence_while_provider_runs_marks_review_stale(review_system):
    started, release = Event(), Event()
    app, base, review, seen = review_system(block=(started, release))
    with TestClient(app) as client:
        investigate(client)
        response = client.post('/api/incidents/INC-AGENT-TEST/review')
        assert started.wait(3)
        base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        release.set()
        # GET reports stale immediately; wait for the actual worker to finish too.
        deadline = time.monotonic() + 5
        while review.repository.get_job(response.json()['job_id'])['active'] and time.monotonic() < deadline:
            time.sleep(0.01)
        job = client.get(response.json()['links']['job']).json()
        assert job['status'] == 'STALE' and not job['current']
        assert job['result']['policy']['effective_recommendation'] is None
        summary = client.get(job['links']['analysis']).json()['decision_review']
        assert summary['status'] == 'STALE' and summary['recommendation'] is None


def test_completed_review_becomes_stale_when_live_input_changes(review_system):
    app, base, review, seen = review_system()
    with TestClient(app) as client:
        investigate(client)
        job = submit_review(client)
        base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        assert client.get(job['links']['job']).json()['status'] == 'STALE'
        assert client.get(job['links']['analysis']).json()['decision_review']['recommendation'] is None


def test_review_read_rechecks_telemetry_age(review_system, monkeypatch):
    from backend.agents import review as review_module
    app, base, review, seen = review_system()
    with TestClient(app) as client:
        investigate(client)
        job = submit_review(client)
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return later
        monkeypatch.setattr(review_module, 'datetime', Later)
        response = client.get(job['links']['job']).json()
        assert response['status'] == 'COMPLETED' and response['current']
        assert response['result']['policy']['requires_fresh_telemetry']
        summary = client.get(job['links']['analysis']).json()['decision_review']
        assert summary['recommendation'] == 'COLLECT_MORE_EVIDENCE'


def test_policy_blocks_unverified_repair_and_alert_downgrade(review_system):
    app, base, review, seen = review_system('disagree')
    with TestClient(app) as client:
        investigate(client)
        job = submit_review(client)
        policy = job['result']['policy']
        assert not policy['repair_review_eligible']
        assert policy['effective_recommendation'] == 'INVESTIGATE_SOFTWARE'
        assert policy['needs_human_approval'] and policy['actions_executed'] == []
        bundle = deepcopy(seen[0])
        conclusion = ReviewConclusion.model_validate(
            {key: value for key, value in job['result'].items() if key != 'policy'})
        conclusion.repair_assessment = 'NO_CANDIDATE'
        assert apply_review_policy(conclusion, bundle)['effective_recommendation'] == 'ESCALATE'
        bundle['incident']['hardware']['observed_at'] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert apply_review_policy(conclusion, bundle)['effective_recommendation'] == 'COLLECT_MORE_EVIDENCE'


def test_real_docker_candidate_can_be_independently_reviewed(review_system, agent_docker_image):
    app, base, review, seen = review_system(investigation_mode='patch')
    with TestClient(app) as client:
        source = investigate(client)
        assert source['result']['generated_repair']['verification_status'] == 'VERIFIED'
        job = submit_review(client)
        assert job['status'] == 'COMPLETED', job
        assert job['result']['policy']['repair_review_eligible']
        assert job['result']['recommendation'] == 'REQUEST_REPAIR_REVIEW'
        assert not job['result']['policy']['deployed']
        assert job['result']['policy']['approval_status'] == 'PENDING'


def test_review_persists_in_separate_mongo_namespace(review_system, agent_snapshot, agent_mongo_database):
    database = agent_mongo_database
    database.incidents.insert_one(deepcopy(agent_snapshot))
    repository = MongoIncidentRepository(database.incidents, database.repair_jobs)
    app, base, review, seen = review_system(repository=repository)
    with TestClient(app) as client:
        source = investigate(client)
        job = submit_review(client)
        assert job['status'] == 'COMPLETED'
        assert database.review_jobs.count_documents({}) == 1
        assert database.investigation_jobs.count_documents({}) == 1
        assert database.repair_jobs.count_documents({}) == 0
        incident = database.incidents.find_one({})
        assert incident['decision_review']['recommendation'] == 'ESCALATE'
        assert incident['investigation']['job_id'] == source['job_id'] and incident['status'] == 'OPEN'
    recreated = MongoIncidentRepository(database.incidents, database.repair_jobs)
    second, base, review, second_seen = review_system(repository=recreated)
    with TestClient(second) as client:
        assert client.get(job['links']['job']).json()['result']['recommendation'] == 'ESCALATE'
        repeated = client.post('/api/incidents/INC-AGENT-TEST/review', headers={'Idempotency-Key': 'review-once'})
        assert repeated.status_code == 200 and repeated.json()['reused']
        assert second_seen == []


def test_review_recovery_never_interrupts_other_workers(agent_mongo_database):
    database = agent_mongo_database
    base = MongoIncidentRepository(database.incidents, database.repair_jobs)
    base.for_investigations()
    reviews = base.for_reviews()
    for collection, prefix in [(database.repair_jobs, 'repair'), (database.investigation_jobs, 'investigation'),
                               (database.review_jobs, 'review')]:
        collection.insert_one({'job_id': prefix + '-only', 'incident_identity': 'identity',
                               'request_key': prefix, 'status': 'RUNNING', 'active': True})
    assert len(reviews.interrupt_incomplete()) == 1
    assert database.review_jobs.find_one({})['status'] == 'INTERRUPTED'
    assert database.repair_jobs.find_one({})['status'] == 'RUNNING'
    assert database.investigation_jobs.find_one({})['status'] == 'RUNNING'

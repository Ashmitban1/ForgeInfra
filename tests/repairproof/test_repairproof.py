"""No wallets or external providers. Transaction signatures below are mock bytes."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymongo.errors import PyMongoError
from solders.hash import Hash
from solders.signature import Signature

from backend.modernization.approval import ApprovalConflict
from backend.modernization.repository import content_revision
from backend.repairproof.commitment import canonical_bytes, build_bundle, digest, DOMAIN
from backend.repairproof.memo import MemoAdapter, MemoConfig, DEVNET_GENESIS, MEMO_PROGRAM, InvalidTransaction
from backend.repairproof.repository import ProofRepository, ProofConflict
from backend.repairproof.service import RepairProofService, ProofUnavailable

HEADERS = {"Authorization": "Bearer unit-test-only-alice-credential-000000000000", "Idempotency-Key": "proof-test"}
PATH = "/api/incidents/INC-AGENT-TEST/repair-proofs"


class ScriptedRPC:
    def __init__(self):
        self.calls = []
        self.network = DEVNET_GENESIS
        self.status = {"confirmationStatus": "finalized", "err": None}
        self.receipt = None
        self.ambiguous = False

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "getGenesisHash":
            return self.network
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 123}}
        if method == "getFeeForMessage":
            return {"value": 5000}
        if method == "getBalance":
            return {"value": 1_000_000}
        if method == "getBlockHeight":
            return 100
        if method == "sendTransaction":
            if self.ambiguous:
                raise TimeoutError("private provider diagnostic")
            return str(Signature.from_bytes(bytes([2]) * 64))
        if method == "getSignatureStatuses":
            return {"value": [self.status]}
        if method == "getTransaction":
            return self.receipt
        raise AssertionError(method)


def install_adapter(service, monkeypatch):
    # No Keypair, wallet creation, or live RPC. Positive signatures are mocked;
    # strict real SDK rejection of invalid signatures is tested separately.
    rpc = ScriptedRPC()
    signer = SimpleNamespace(sign_message=lambda message: Signature.from_bytes(bytes([2]) * 64))
    adapter = MemoAdapter(MemoConfig("11111111111111111111111111111111"), rpc, signer)
    monkeypatch.setattr("backend.repairproof.memo.verify_signatures", lambda tx: None)
    service.adapter = adapter
    return rpc


def finalize_receipt(rpc, proof):
    rpc.receipt = {"transaction": [proof["signed_transaction_b64"], "base64"], "meta": {"err": None, "fee": 5000}, "slot": 42}


def test_golden_serialization_and_commitment():
    fixture = json.loads((Path(__file__).parent / "golden_v1.json").read_text())
    bundle = build_bundle(fixture["package"], fixture["decision"], **fixture["context"])
    assert bundle == fixture["expected"]
    assert canonical_bytes({"z": 1.0, "a": "é", "v": False}) == b'{"a":"\\u00e9","v":false,"z":1.0}'
    with pytest.raises(ValueError):
        canonical_bytes({"invalid": float("nan")})
    changed = deepcopy(fixture)
    changed["decision"]["comment"] += " edited"
    assert build_bundle(changed["package"], changed["decision"], **changed["context"])["commitment"] != bundle["commitment"]
    changed = deepcopy(fixture)
    changed["package"]["data"]["binding"]["candidate_revision"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        build_bundle(changed["package"], changed["decision"], **changed["context"])


def test_publication_persists_signed_bytes_before_send_and_recovers(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    call = rpc.call
    def observe(method, params):
        if method == "sendTransaction":
            stored = db.repair_proofs.find_one({})
            assert stored["status"] == "SUBMITTING"
            assert stored["signed_transaction_b64"] == params[0] and stored["signature"]
            assert params[1]["maxRetries"] == 0 and not params[1]["skipPreflight"]
        return call(method, params)
    rpc.call = observe
    first = client.post(PATH, headers=HEADERS, json=request.model_dump())
    assert first.status_code == 202, first.text
    proof = service.repository.get(first.json()["proof_id"])
    assert proof["status"] == "UNKNOWN"
    # A new service/repository simulates process restart over persisted records.
    recovered = RepairProofService(service.approval, ProofRepository(db), service.adapter, enabled_factory=lambda: True)
    finalize_receipt(rpc, proof)
    rpc.status = {"confirmationStatus": "finalized", "err": None}
    result, created = recovered.publish("INC-AGENT-TEST", request, reviewer, "new-key")
    assert not created and result["status"] == "FINALIZED"
    assert result["verification"]["slot"] == 42
    assert len([c for c in rpc.calls if c[0] == "sendTransaction"]) == 1
    before = deepcopy(db.repair_proofs.find_one({}))
    response = client.get(f"/api/repair-proofs/{proof['proof_id']}/verify", headers=HEADERS)
    assert response.json()["status"] == "FINALIZED", response.text
    assert db.repair_proofs.find_one({}) == before  # GET is read only.
    assert "signed_transaction_b64" not in first.text
    assert client.get(f"/api/repair-proofs/{proof['proof_id']}/bundle", headers=HEADERS).status_code == 200


def test_ambiguous_timeout_never_resubmits_and_idempotency_is_strict(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.ambiguous, rpc.status = True, None
    proof, created = service.publish("INC-AGENT-TEST", request, reviewer, "first")
    assert proof["status"] == "UNKNOWN"
    for key in ["first", "second", "second"]:
        repeated, created = service.publish("INC-AGENT-TEST", request, reviewer, key)
        assert not created and repeated["signature"] == proof["signature"]
    assert len([c for c in rpc.calls if c[0] == "sendTransaction"]) == 1
    changed = request.model_copy(update={"decision_id": "different"})
    with pytest.raises((ProofConflict, ApprovalConflict)):
        service.publish("INC-AGENT-TEST", changed, reviewer, "second")
    assert db.repair_proofs.count_documents({}) == 1


@pytest.mark.parametrize("blocked", ["disabled", "memory", "volatile", "pending", "readback", "candidate", "review", "revoked"])
def test_fail_closed_approval_gates(proof_system, monkeypatch, blocked):
    service, client, request, reviewer, db, base, source, review = proof_system
    rpc = install_adapter(service, monkeypatch)
    if blocked == "disabled":
        service.enabled_factory = lambda: False
    elif blocked == "memory":
        service.repository = ProofRepository(None)
    elif blocked in {"volatile", "pending"}:
        get = base.get_incident_snapshot
        def changed(iid):
            incident = get(iid)
            incident["approval_persistence"]["status"] = blocked.upper()
            return incident
        monkeypatch.setattr(base, "get_incident_snapshot", changed)
    elif blocked == "readback":
        db.incidents.update_one({}, {"$set": {"approval.version": 99}})
    elif blocked == "candidate":
        base.for_investigations().jobs[source["job_id"]]["result"]["generated_repair"]["verification_status"] = "FAILED"
    elif blocked == "review":
        base.incidents["INC-AGENT-TEST"]["hardware"]["sequence"] += 1
    else:
        monkeypatch.setenv("FACTORYOS_APPROVERS_JSON", '{}')
    response = client.post(PATH, headers=HEADERS, json=request.model_dump())
    assert response.status_code in {409, 503}, response.text
    assert not [c for c in rpc.calls if c[0] == "sendTransaction"]


def test_auth_and_reserved_update_fields(proof_system, monkeypatch):
    from backend.storage.lifecycle import IncidentUpdate
    from pydantic import ValidationError
    service, client, request, reviewer, *_ = proof_system
    install_adapter(service, monkeypatch)
    assert client.post(PATH, json=request.model_dump(), headers={"Idempotency-Key": "x"}).status_code == 401
    assert client.get(PATH).status_code == 401
    assert client.get('/api/repair-proofs/missing').status_code == 401
    assert client.get('/api/repair-proofs/missing', headers=HEADERS).status_code == 404
    assert client.post(PATH, headers=HEADERS, json={**request.model_dump(), "signer": "forged"}).status_code == 422
    for name in ["solana_tx_signature", "SOLANA_verified", "repairproof_status", "repair_proof"]:
        with pytest.raises(ValidationError):
            IncidentUpdate(event_id="forged", integrations={name: "VERIFIED"})
    with pytest.raises(ValidationError):
        IncidentUpdate(event_id="forged", repairproof={"status": "FINALIZED"})
    IncidentUpdate(event_id="allowed", integrations={"jira_key": "KAN-TEST"})


@pytest.mark.parametrize("invalid", ["network", "signer", "program", "memo", "signature", "bytes", "failed", "pending", "missing"])
def test_strict_provider_verification(proof_system, monkeypatch, invalid):
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.transaction import Transaction
    service, client, request, reviewer, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    proof, _ = service.publish("INC-AGENT-TEST", request, reviewer, "provider")
    finalize_receipt(rpc, proof)
    rpc.status = {"confirmationStatus": "finalized", "err": None}
    if invalid == "network":
        rpc.network = "wrong-network"
    elif invalid in {"signer", "program", "memo"}:
        publisher = Pubkey.from_string(service.adapter.config.publisher)
        instruction = Instruction(Pubkey.from_string(MEMO_PROGRAM) if invalid != "program" else Pubkey.default(),
                                  service.adapter.memo(proof) if invalid != "memo" else b"forged memo",
                                  [AccountMeta(publisher, True, False)])
        payer = publisher if invalid != "signer" else Pubkey.from_bytes(bytes([3]) * 32)
        message = Message.new_with_blockhash([instruction], payer, Hash.default())
        signatures = [Signature.default()] * message.header.num_required_signatures
        raw = base64.b64encode(bytes(Transaction.populate(message, signatures))).decode()
        with pytest.raises(InvalidTransaction):
            service.adapter.inspect(raw, proof)
        return
    elif invalid == "signature":
        # Restore real Ed25519 validation: scripted positive signature is invalid.
        monkeypatch.setattr("backend.repairproof.memo.verify_signatures", lambda tx: tx.verify())
    elif invalid == "bytes":
        rpc.receipt["transaction"][0] = base64.b64encode(b"forged").decode()
    elif invalid == "failed":
        rpc.status["err"] = {"InstructionError": [0, "error"]}
    elif invalid == "pending":
        rpc.status["confirmationStatus"] = "confirmed"
    else:
        rpc.receipt = None
    result = service.verify(proof)
    assert result["status"] == {"failed": "CHAIN_FAILED", "pending": "PENDING", "missing": "UNKNOWN"}.get(invalid, "MISMATCH")


def test_unique_concurrent_reservations_and_failed_writes(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    proof, _ = service.publish("INC-AGENT-TEST", request, reviewer, "concurrent")
    def reserve(index):
        candidate = deepcopy(proof)
        candidate["proof_id"] = "alternate-" + str(index)
        candidate["request_key"] += str(index)
        return ProofRepository(db).reserve(candidate)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(reserve, range(8)))
    assert all(not created and p["proof_id"] == proof["proof_id"] for p, created in results)
    assert db.repair_proofs.count_documents({}) == 1


def test_storage_failure_before_send_blocks_broadcast(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    transition = service.repository.transition
    def broken(proof_id, previous, changes):
        if changes["status"] == "SIGNED":
            raise PyMongoError("private connection information")
        return transition(proof_id, previous, changes)
    monkeypatch.setattr(service.repository, "transition", broken)
    response = client.post(PATH, headers=HEADERS, json=request.model_dump())
    assert response.status_code == 503 and "private connection" not in response.text
    assert not [c for c in rpc.calls if c[0] == "sendTransaction"]


def test_saved_bundle_tampering_is_detected(proof_system, monkeypatch):
    service, client, request, reviewer, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    proof, _ = service.publish("INC-AGENT-TEST", request, reviewer, "tamper")
    proof["bundle"]["approval_bytes_b64"] = base64.b64encode(b'{}').decode()
    assert service.verify(proof)["status"] == "MISMATCH"


def test_approval_changed_during_preparation_blocks_send(proof_system, monkeypatch):
    service, client, request, reviewer, db, base, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    prepare = service.adapter.prepare
    def changed(proof):
        signed = prepare(proof)
        base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
        return signed
    service.adapter.prepare = changed
    response = client.post(PATH, headers=HEADERS, json=request.model_dump())
    assert response.status_code == 409
    assert db.repair_proofs.find_one({})['status'] == 'SIGNED'
    assert not [c for c in rpc.calls if c[0] == 'sendTransaction']


def test_lost_database_ack_after_send_recovers_without_resending(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    transition = service.repository.transition
    def broken(proof_id, previous, changes):
        if changes['status'] == 'SUBMITTED':
            raise PyMongoError('private Mongo diagnostic')
        return transition(proof_id, previous, changes)
    monkeypatch.setattr(service.repository, 'transition', broken)
    response = client.post(PATH, headers=HEADERS, json=request.model_dump())
    assert response.status_code == 503 and 'private Mongo' not in response.text
    saved = db.repair_proofs.find_one({})
    assert saved['status'] == 'SUBMITTING' and saved['signature']
    finalize_receipt(rpc, saved)
    rpc.status = {'confirmationStatus': 'finalized', 'err': None}
    monkeypatch.setattr(service.repository, 'transition', transition)
    proof, created = service.publish('INC-AGENT-TEST', request, reviewer, 'proof-test')
    assert not created and proof['status'] == 'FINALIZED'
    assert len([c for c in rpc.calls if c[0] == 'sendTransaction']) == 1


def test_current_approval_can_become_stale_without_invalidating_historical_proof(proof_system, monkeypatch):
    service, client, request, reviewer, db, base, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    rpc.status = None
    proof, _ = service.publish('INC-AGENT-TEST', request, reviewer, 'history')
    finalize_receipt(rpc, proof)
    rpc.status = {'confirmationStatus': 'finalized', 'err': None}
    base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
    # No new signing is allowed; an old, already submitted commitment is readable.
    result, created = service.publish('INC-AGENT-TEST', request, reviewer, 'history')
    assert not created and result['status'] == 'FINALIZED'
    readiness = service.readiness('INC-AGENT-TEST', reviewer)
    assert not readiness['ready'] and readiness['proof']['status'] == 'FINALIZED'
    assert len([c for c in rpc.calls if c[0] == 'sendTransaction']) == 1


def test_only_approving_reviewer_can_publish_and_disabled_startup_is_read_only(proof_system, monkeypatch):
    service, client, request, reviewer, db, *_ = proof_system
    rpc = install_adapter(service, monkeypatch)
    headers = {**HEADERS, 'Authorization': 'Bearer unit-test-only-bob-credential-00000000000000'}
    assert client.post(PATH, headers=headers, json=request.model_dump()).status_code == 409
    response = client.get(PATH, headers=headers)
    assert not response.json()['ready']
    assert 'approving_reviewer_required' in response.json()['blocking_reasons']
    assert client.post(PATH, headers={'Authorization': HEADERS['Authorization']}, json=request.model_dump()).status_code == 422
    assert not [c for c in rpc.calls if c[0] == 'sendTransaction']
    import mongomock
    clean = mongomock.MongoClient().empty
    ProofRepository(clean)
    assert clean.list_collection_names() == []  # no startup/index writes


def test_default_feature_cannot_be_enabled_into_a_live_provider(proof_system, monkeypatch):
    from backend.repairproof.service import enabled
    service, client, request, reviewer, *_ = proof_system
    service.enabled_factory = enabled
    assert not service.capabilities()['enabled']
    monkeypatch.setenv('SOLANA_ENABLED', 'true')
    assert not service.capabilities()['publish_ready']
    assert 'solana_publisher_configuration_required' in service.capabilities()['blocking_reasons']
    assert client.post(PATH, headers=HEADERS, json=request.model_dump()).status_code == 503


def test_integrated_app_registers_disabled_routes_and_rejects_forgery(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import app
    monkeypatch.setenv('FACTORYOS_APPROVERS_JSON', '{}')
    with TestClient(app) as client:
        response = client.get('/api/repair-proofs/capabilities')
        assert response.status_code == 200
        assert response.json()['enabled'] is False
        assert not response.json()['publish_ready']
        assert 'mongodb_required' in response.json()['blocking_reasons']
        assert client.get('/api/repair-proofs/missing/verify').status_code == 503
        response = client.post('/api/incidents/missing/updates', json={
            'event_id': 'forgery-route-test', 'integrations': {'solana_tx_signature': 'forged'}})
        assert response.status_code == 422

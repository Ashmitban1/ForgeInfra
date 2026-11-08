"""Real SDK signatures with public RFC 8032 TEST 1 data, fully mocked HTTP RPC.

No random keys, application wallets, real RPC, funds, or on-chain transactions.
The published, insecure test vector is reconstructed only inside test fixtures.
"""
import base64
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from solders.hash import Hash, ParseHashError
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

from backend.repairproof.live import (
    JsonRpcClient, LiveConfig, LiveConfigurationError, LocalFileSigner, adapter_from_environment,
)
from backend.repairproof.memo import DEVNET_GENESIS, MEMO_PROGRAM, MemoAdapter, MemoConfig, InvalidTransaction, ProviderError
from backend.repairproof.repository import ProofRepository, ProofConflict
from backend.repairproof.service import RepairProofService, ProofUnavailable

RFC8032_TEST1 = bytes.fromhex(
    '9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60'
    'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
HEADERS = {'Authorization': 'Bearer unit-test-only-alice-credential-000000000000'}


def test_devnet_pin_is_full_sdk_hash_not_the_truncated_chain_reference():
    # Solana's canonical Devnet genesis, independently of the mocked RPC constant.
    expected = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG'
    assert DEVNET_GENESIS == expected
    assert str(Hash.from_string(DEVNET_GENESIS)) == expected
    with pytest.raises(ParseHashError):
        Hash.from_string('EtWTRABZaYq6iMfeYKouRu166VU2xqa1')


class HttpChain:
    def __init__(self):
        self.calls = []
        self.sends = 0
        self.raw = None
        self.genesis = DEVNET_GENESIS
        self.fee = 5000
        self.balance = 1_000_000
        self.height = 100
        self.finalized = False
        self.ambiguous = False
        self.observe_send = lambda raw: None

    def handle(self, request):
        body = json.loads(request.content)
        method, params = body['method'], body['params']
        self.calls.append((method, params))
        if method == 'getGenesisHash': result = self.genesis
        elif method == 'getLatestBlockhash': result = {'value': {'blockhash': str(Hash.from_bytes(bytes([7]) * 32)), 'lastValidBlockHeight': 200}}
        elif method == 'getFeeForMessage': result = {'value': self.fee}
        elif method == 'getBalance': result = {'value': self.balance}
        elif method == 'getBlockHeight': result = self.height
        elif method == 'sendTransaction':
            self.sends += 1
            self.raw = params[0]
            self.observe_send(self.raw)
            tx = Transaction.from_bytes(base64.b64decode(self.raw))
            tx.verify()  # Actual SDK Ed25519 verification, no monkeypatch.
            assert params[1]['skipPreflight'] is False and params[1]['maxRetries'] == 0
            if self.ambiguous:
                raise httpx.ReadTimeout('untrusted private RPC diagnostic')
            result = str(tx.signatures[0])
        elif method == 'getSignatureStatuses':
            assert params[1]['searchTransactionHistory'] is True
            result = {'value': [{'confirmationStatus': 'finalized' if self.finalized else 'confirmed', 'err': None, 'slot': 42}]}
        elif method == 'getTransaction':
            assert params[1]['commitment'] == 'finalized'
            result = {'transaction': [self.raw, 'base64'], 'meta': {'err': None, 'fee': self.fee}, 'slot': 42} if self.finalized else None
        else: raise AssertionError(method)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})


@pytest.fixture
def sdk_adapter(tmp_path):
    # Reconstruct an already-public test vector, never generate a new key.
    key = Keypair.from_bytes(RFC8032_TEST1)
    path = tmp_path / 'public-rfc-test-vector.json'
    path.write_text(json.dumps(list(RFC8032_TEST1)))
    path.chmod(0o600)
    signer = LocalFileSigner(str(path), str(key.pubkey()))
    chain = HttpChain()
    rpc = JsonRpcClient('https://rpc.invalid', transport=httpx.MockTransport(chain.handle))
    verify_rpc = JsonRpcClient('https://verify.invalid', transport=httpx.MockTransport(chain.handle))
    adapter = MemoAdapter(MemoConfig(str(key.pubkey())), rpc, signer, verification_rpc=verify_rpc)
    yield adapter, chain, key, path
    adapter.close()


def test_actual_sdk_signing_persist_before_send_finality_and_idempotent_reconcile(proof_system, sdk_adapter):
    service, client, request, reviewer, db, *_ = proof_system
    adapter, chain, key, _ = sdk_adapter
    service.adapter = adapter
    frozen_before = deepcopy(db.incidents.find_one({})['approval'])
    def stored_before_send(raw):
        stored = db.repair_proofs.find_one({})
        assert stored['status'] == 'SUBMITTING' and stored['signed_transaction_b64'] == raw
        assert stored['estimated_fee_lamports'] == 5000 and stored['max_fee_lamports'] == 10000
        assert stored['signature'] == str(Transaction.from_bytes(base64.b64decode(raw)).signatures[0])
    chain.observe_send = stored_before_send
    proof, created = service.publish('INC-AGENT-TEST', request, reviewer, 'real-sdk-offline')
    assert created and proof['status'] == 'UNKNOWN' and chain.sends == 1
    assert service.verify(proof)['status'] == 'PENDING'
    chain.finalized = True
    response = client.post('/api/repair-proofs/' + proof['proof_id'] + '/reconcile', headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'FINALIZED'
    assert response.json()['verification']['fee_lamports'] == 5000
    assert response.json()['explorer_url'].endswith('?cluster=devnet')
    for identity in ['real-sdk-offline', 'new-retry-key']:
        repeated, created = service.publish('INC-AGENT-TEST', request, reviewer, identity)
        assert not created and repeated['signature'] == proof['signature']
    assert chain.sends == 1 and db.repair_proofs.count_documents({}) == 1
    assert db.incidents.find_one({})['approval'] == frozen_before
    assert not client.get('/api/repair-proofs/' + proof['proof_id'], headers=HEADERS).json().get('signed_transaction_b64')


def test_http_timeout_after_send_recovers_across_service_recreation_without_sign_or_send(proof_system, sdk_adapter):
    service, _, request, reviewer, db, *_ = proof_system
    adapter, chain, _, _ = sdk_adapter
    service.adapter = adapter
    chain.ambiguous = True
    proof, _ = service.publish('INC-AGENT-TEST', request, reviewer, 'ambiguous')
    assert proof['status'] == 'UNKNOWN' and chain.sends == 1
    def no_sign(message): raise AssertionError('Recovery must never sign')
    adapter.signer.sign_message = no_sign
    recreated = RepairProofService(service.approval, ProofRepository(db), adapter, enabled_factory=lambda: True)
    chain.finalized = True
    result, created = recreated.publish('INC-AGENT-TEST', request, reviewer, 'retry')
    assert not created and result['status'] == 'FINALIZED' and chain.sends == 1


@pytest.mark.parametrize('failure', ['wrong_network', 'fee_high', 'fee_null', 'balance_low', 'expired'])
def test_real_adapter_fails_closed_without_broadcast(proof_system, sdk_adapter, failure):
    service, _, request, reviewer, db, *_ = proof_system
    adapter, chain, _, _ = sdk_adapter
    service.adapter = adapter
    if failure == 'wrong_network': chain.genesis = 'wrong-cluster'
    elif failure == 'fee_high': chain.fee = 10001
    elif failure == 'fee_null': chain.fee = None
    elif failure == 'balance_low': chain.balance = 1
    else: chain.height = 201
    if failure == 'expired':
        proof, _ = service.publish('INC-AGENT-TEST', request, reviewer, failure)
        assert proof['status'] == 'UNKNOWN'
    else:
        with pytest.raises(ProofUnavailable): service.publish('INC-AGENT-TEST', request, reviewer, failure)
        assert db.repair_proofs.find_one({})['status'] == 'PREPARATION_FAILED'
    assert chain.sends == 0


def test_sdk_rejects_bad_signature_other_signer_extra_instruction_and_proof_replay(proof_system, sdk_adapter):
    service, _, request, reviewer, _, *_ = proof_system
    adapter, chain, key, _ = sdk_adapter
    service.adapter = adapter
    proof, _ = service.publish('INC-AGENT-TEST', request, reviewer, 'strict-sdk')
    tx = Transaction.from_bytes(base64.b64decode(proof['signed_transaction_b64']))
    invalid = Transaction.populate(tx.message, [Signature.default()])
    with pytest.raises(InvalidTransaction): adapter.inspect(base64.b64encode(bytes(invalid)).decode(), proof)
    altered = deepcopy(proof)
    altered['proof_id'] = 'different-proof'
    with pytest.raises(InvalidTransaction): adapter.inspect(proof['signed_transaction_b64'], altered)
    altered = deepcopy(proof)
    altered['bundle']['commitment'] = 'sha256:' + 'f' * 64
    with pytest.raises(InvalidTransaction): adapter.inspect(proof['signed_transaction_b64'], altered)
    instruction = Instruction(Pubkey.from_string(MEMO_PROGRAM), adapter.memo(proof), [AccountMeta(key.pubkey(), True, False)])
    message = Message.new_with_blockhash([instruction, instruction], key.pubkey(), Hash.default())
    extra = Transaction.populate(message, [key.sign_message(bytes(message))])
    with pytest.raises(InvalidTransaction): adapter.inspect(base64.b64encode(bytes(extra)).decode(), proof)
    other = MemoAdapter(MemoConfig(str(Pubkey.default())), adapter.rpc, key)
    with pytest.raises(InvalidTransaction): other.inspect(proof['signed_transaction_b64'], proof)
    assert chain.sends == 1


def test_verification_uses_separate_rpc_and_checks_actual_fee_and_finality(proof_system, sdk_adapter):
    service, _, request, reviewer, _, *_ = proof_system
    adapter, chain, _, _ = sdk_adapter
    service.adapter = adapter
    proof, _ = service.publish('INC-AGENT-TEST', request, reviewer, 'verify-rpc')
    chain.finalized = True
    assert service.verify(proof)['status'] == 'FINALIZED'
    chain.fee = 10001
    assert service.verify(proof)['status'] == 'MISMATCH'
    chain.fee = 5000
    def wrong(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': 'wrong-cluster'})
    independent = JsonRpcClient('https://independent.invalid', transport=httpx.MockTransport(wrong))
    adapter.verification_rpc = independent
    assert service.verify(proof)['status'] == 'MISMATCH'
    independent.close()
    assert chain.sends == 1


def test_local_signer_rejects_permissions_symlinks_invalid_file_and_allowlist(sdk_adapter, tmp_path):
    adapter, _, key, path = sdk_adapter
    assert adapter.signer.sign_message(b'test').verify(key.pubkey(), b'test')
    path.chmod(0o644)
    assert not adapter.signer.configured()
    with pytest.raises(ProviderError): adapter.signer.sign_message(b'test')
    path.chmod(0o600)
    link = tmp_path / 'symlink'
    link.symlink_to(path)
    assert not LocalFileSigner(str(link), str(key.pubkey())).configured()
    with pytest.raises(ProviderError): LocalFileSigner(str(link), str(key.pubkey())).sign_message(b'test')
    with pytest.raises(ProviderError): LocalFileSigner(str(path), str(Pubkey.default())).sign_message(b'test')
    path.write_text('[]')
    with pytest.raises(ProviderError): adapter.signer.sign_message(b'test')


@pytest.mark.parametrize('failure', ['timeout', 'http', 'redirect', 'error', 'wrong_id', 'oversized', 'invalid_json'])
def test_rpc_errors_are_bounded_sanitized_and_never_retried(failure):
    calls = []
    secret = 'private-rpc-diagnostic-never-returned'
    def handler(request):
        calls.append(request)
        assert request.extensions['timeout']['read'] == 2
        body = json.loads(request.content)
        if failure == 'timeout': raise httpx.ReadTimeout(secret)
        if failure == 'http': return httpx.Response(500, text=secret)
        if failure == 'redirect': return httpx.Response(307, headers={'Location': 'https://elsewhere.invalid'})
        if failure == 'error': return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'error': {'message': secret}})
        if failure == 'wrong_id': return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 'other', 'result': True})
        if failure == 'oversized': return httpx.Response(200, content=b'X' * 256001)
        return httpx.Response(200, text=secret)
    rpc = JsonRpcClient('https://rpc.invalid', 2, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as error: rpc.call('getGenesisHash', [])
        assert secret not in str(error.value) and len(calls) == 1
        with pytest.raises(ProviderError): rpc.call('requestAirdrop', [])
        assert len(calls) == 1
    finally: rpc.close()


def test_configuration_and_factory_never_load_key_or_contact_rpc(monkeypatch, sdk_adapter):
    adapter, _, key, path = sdk_adapter
    monkeypatch.setenv('SOLANA_ALLOWED_PUBLISHER', str(key.pubkey()))
    monkeypatch.setenv('SOLANA_PUBLISHER_KEYPAIR_PATH', str(path))
    config = LiveConfig.from_environment()
    assert config.max_fee_lamports == 10000
    def forbidden(*args, **kwargs): raise AssertionError('No startup/capability RPC or signing')
    monkeypatch.setattr(JsonRpcClient, 'call', forbidden)
    monkeypatch.setattr(LocalFileSigner, 'sign_message', forbidden)
    result = adapter_from_environment()
    assert result.configured()
    result.close()
    for name, value in [('SOLANA_EXPECTED_GENESIS_HASH','wrong-network'), ('SOLANA_MAX_FEE_LAMPORTS','100001'),
                        ('SOLANA_RPC_TIMEOUT_SECONDS','nan'), ('SOLANA_RPC_URL','http://localhost'),
                        ('SOLANA_ALLOWED_PUBLISHER',str(Pubkey.default()))]:
        with monkeypatch.context() as patch:
            patch.setenv(name, value)
            with pytest.raises(LiveConfigurationError): LiveConfig.from_environment()


@pytest.mark.parametrize('blocked', ['disabled', 'memory', 'stale', 'wrong_reviewer', 'wrong_candidate'])
def test_real_sdk_path_requires_current_authorized_durable_approval_before_any_rpc(proof_system, sdk_adapter, blocked):
    from backend.modernization.approval import ApprovalConflict
    from backend.modernization.approval_auth import Reviewer
    service, _, request, reviewer, _, base, *_ = proof_system
    adapter, chain, _, _ = sdk_adapter
    service.adapter = adapter
    if blocked == 'disabled': service.enabled_factory = lambda: False
    elif blocked == 'memory': service.repository = ProofRepository(None)
    elif blocked == 'stale': base.incidents['INC-AGENT-TEST']['hardware']['sequence'] += 1
    elif blocked == 'wrong_reviewer': reviewer = Reviewer('bob')
    else: request = request.model_copy(update={'candidate_revision': 'sha256:' + 'f' * 64})
    with pytest.raises((ProofUnavailable, ProofConflict, ApprovalConflict)):
        service.publish('INC-AGENT-TEST', request, reviewer, 'must-not-sign')
    assert chain.calls == [] and chain.sends == 0

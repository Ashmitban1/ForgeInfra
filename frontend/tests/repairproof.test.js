import { afterEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { verifyRepairProofBundle } from '../src/lib/repairproof.js';
import { getRepairProofReadiness, publishRepairProof, verifyRepairProof, getRepairProofBundle, reconcileRepairProof } from '../src/api.js';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; delete globalThis.window; });
test('browser independently hashes the shared Python golden fixture and rejects edits', async () => {
  const fixture = JSON.parse(await readFile(new URL('../../tests/repairproof/golden_v1.json', import.meta.url), 'utf8'));
  assert.equal(await verifyRepairProofBundle(fixture.expected, fixture.expected.commitment), true);
  assert.equal(await verifyRepairProofBundle(fixture.expected, 'sha256:' + '0'.repeat(64)), false);
  const changed = structuredClone(fixture.expected);
  changed.approval_bytes_b64 = btoa('{}');
  assert.equal(await verifyRepairProofBundle(changed, fixture.expected.commitment), false);
});
test('RepairProof publication is authenticated and verification/readiness never POST', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response('{}'); };
  const body = { decision_id: 'approval-1', package_revision: 'sha256:package', candidate_revision: 'sha256:candidate' };
  await publishRepairProof('INC /1', body, { token: 'unit-reviewer', idempotencyKey: 'proof-1' });
  await getRepairProofReadiness('INC /1', { token: 'unit-reviewer' });
  await verifyRepairProof('proof-1', { token: 'unit-reviewer' });
  await getRepairProofBundle('proof-1', { token: 'unit-reviewer' });
  assert.ok(calls[0].url.endsWith('/api/incidents/INC%20%2F1/repair-proofs'));
  assert.equal(calls[0].options.headers.Authorization, 'Bearer unit-reviewer');
  assert.equal(calls[0].options.headers['Idempotency-Key'], 'proof-1');
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
  assert.deepEqual(calls.map(call => call.options.method), ['POST', 'GET', 'GET', 'GET']);
});
test('demo RepairProof mutation never reaches a provider', async () => {
  globalThis.window = { localStorage: { getItem: () => '1' } };
  globalThis.fetch = async () => { throw new Error('must not call'); };
  await assert.rejects(publishRepairProof('DEMO', {}), error => error.kind === 'demo');
});
test('reconciliation targets the saved proof and never calls the publication endpoint', async () => {
  let call;
  globalThis.fetch = async (url, options) => { call = { url, options }; return new Response('{"status":"FINALIZED"}'); };
  const result = await reconcileRepairProof('proof /1', { token: 'unit-reviewer' });
  assert.equal(result.status, 'FINALIZED');
  assert.ok(call.url.endsWith('/api/repair-proofs/proof%20%2F1/reconcile'));
  assert.equal(call.options.method, 'POST');
  assert.equal(call.options.headers.Authorization, 'Bearer unit-reviewer');
  assert.equal(call.options.body, undefined);
});

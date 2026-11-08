// Hash the server's exact canonical bytes; never reserialize Python JSON in JS.
const decode = value => Uint8Array.from(atob(value), char => char.charCodeAt(0));
const parse = bytes => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
async function digest(bytes) {
  const hash = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
  return 'sha256:' + Array.from(hash, byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function verifyRepairProofBundle(bundle, expectedCommitment) {
  try {
    const envelopeBytes = decode(bundle.envelope_bytes_b64);
    const envelope = parse(envelopeBytes);
    const packageBytes = decode(bundle.package_bytes_b64);
    const approvalBytes = decode(bundle.approval_bytes_b64);
    const evidence = parse(packageBytes);
    const approval = parse(approvalBytes);
    const domain = new TextEncoder().encode('FactoryOS/RepairProof/v1\n');
    const bytes = new Uint8Array(domain.length + envelopeBytes.length);
    bytes.set(domain); bytes.set(envelopeBytes, domain.length);
    return envelope.schema === 'factoryos.repairproof.v1'
      && await digest(bytes) === expectedCommitment
      && bundle.commitment === expectedCommitment
      && await digest(packageBytes) === envelope.package_revision
      && await digest(approvalBytes) === envelope.approval_revision
      && evidence.incident_identity === envelope.incident_identity
      && evidence.binding.candidate_revision === envelope.candidate_revision
      && approval.candidate_revision === envelope.candidate_revision
      && approval.package_revision === envelope.package_revision
      && approval.decision_id === envelope.approval_decision_id
      && approval.decision === 'APPROVE';
  } catch { return false; }
}

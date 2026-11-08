import { useEffect, useRef, useState } from 'react';
import { getRepairProofReadiness, getRepairProofBundle, publishRepairProof, verifyRepairProof, reconcileRepairProof } from '../../api.js';
import { verifyRepairProofBundle } from '../../lib/repairproof.js';
import { isDemoMode } from '../../demo/fixtures.js';
import { actionKey } from '../../hooks/useIncidentWorkflow.js';
import { safeHttpUrl } from '../../lib/format.js';

export default function RepairProof({ incidentId, token, approvalVersion }) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [verification, setVerification] = useState(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const session = useRef(0);
  const inFlight = useRef(false);
  const requestKey = useRef(null);
  useEffect(() => {
    const current = ++session.current;
    setView(null); setError(null); setVerification(null); setUncertain(false);
    requestKey.current = null;
    if (!token || isDemoMode()) return undefined;
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const result = await getRepairProofReadiness(incidentId, { token, signal: controller.signal });
        if (session.current === current && !controller.signal.aborted) { setView(result); setError(null); }
      } catch (failure) {
        if (session.current === current && !controller.signal.aborted) setError(failure.message);
      }
      if (!controller.signal.aborted) timer = setTimeout(load, 8000);
    }
    load();
    return () => { ++session.current; controller.abort(); clearTimeout(timer); };
  }, [incidentId, token, approvalVersion]);
  async function act(publish) {
    if (inFlight.current || !token) return;
    inFlight.current = true; setBusy(true); setError(null);
    const current = session.current;
    try {
      if (publish === true) {
        requestKey.current ||= actionKey();
        const result = await publishRepairProof(incidentId, { decision_id: view.decision_id,
          package_revision: view.package_revision, candidate_revision: view.candidate_revision },
        { token, idempotencyKey: requestKey.current });
        if (current === session.current) setView(previous => ({ ...previous, proof: result }));
      } else if (publish === 'reconcile') {
        const result = await reconcileRepairProof(view.proof.proof_id, { token });
        if (current === session.current) {
          setView(previous => ({ ...previous, proof: result }));
          setVerification(result.verification || null);
        }
      } else {
        const [result, bundle] = await Promise.all([
          verifyRepairProof(view.proof.proof_id, { token }), getRepairProofBundle(view.proof.proof_id, { token }),
        ]);
        const matches = await verifyRepairProofBundle(bundle, view.proof.commitment);
        if (current === session.current) setVerification(matches ? result : { status: 'MISMATCH', reason: 'browser_evidence_hash_mismatch' });
      }
    } catch (failure) {
      if (current === session.current) {
        setError(failure.message);
        if (publish === true) setUncertain(true);
      }
    } finally { inFlight.current = false; setBusy(false); }
  }
  const proof = view?.proof;
  const explorer = safeHttpUrl(proof?.explorer_url);
  return <div className="repairproof-panel">
    <p className="note">Devnet evidence commitment · {view?.enabled ? 'Publishing enabled; approval required.' : 'Live publishing disabled.'}</p>
    {isDemoMode() ? <p>Unavailable for demo fixtures.</p> : !token ? <p>Inspect the Human Approval package above to use the reviewer session.</p> : <>
      <p role="status">{busy ? 'Checking RepairProof…' : proof?.status || (view?.ready ? 'Ready for authorized publishing' : 'Publishing blocked')}</p>
      {view?.blocking_reasons?.length > 0 && <ul className="reasons">{view.blocking_reasons.map(reason => <li key={reason}><code>{reason}</code></li>)}</ul>}
      <dl className="facts revision-list">
        <div className="fact"><dt>Evidence fingerprint</dt><dd><code>{proof?.commitment || view?.package_revision || 'Not available'}</code></dd></div>
        {proof?.signature && <div className="fact"><dt>Transaction</dt><dd><code>{proof.signature}</code></dd></div>}
      </dl>
      <div className="actions">
        <button className="btn" disabled={busy || !view?.ready || !!proof || uncertain || !!error} onClick={() => act(true)}>Publish RepairProof</button>
        <button className="btn" disabled={busy || !proof?.signature} onClick={() => act(false)}>Verify proof (read only)</button>
        <button className="btn" disabled={busy || !proof?.signature} onClick={() => act('reconcile')}>Reconcile status (no resubmit)</button>
        {explorer && <a className="btn" href={explorer} target="_blank" rel="noreferrer noopener">View on Solana Explorer</a>}
      </div>
      {uncertain && <p className="note">Publication outcome is uncertain. Inspect the saved proof; this view will not automatically submit again.</p>}
      {verification && <p role="status">Verification: {verification.status} · {verification.reason}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </>}
    <p className="note">A proof records approved evidence. It does not deploy software or establish equipment recovery.</p>
  </div>;
}

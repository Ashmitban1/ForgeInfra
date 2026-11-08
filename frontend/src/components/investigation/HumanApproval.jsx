import { useEffect, useRef, useState } from 'react';
import { decideApproval, getApproval, getApprovalHistory } from '../../api.js';
import { isDemoMode } from '../../demo/fixtures.js';
import { actionKey } from '../../hooks/useIncidentWorkflow.js';
import { Badge } from '../ui.jsx';

export default function HumanApproval({ incidentId, summary, configured, onChanged, candidateRevision, investigationJobId, onSessionChange }) {
  const [credential, setCredential] = useState('');
  const [token, setToken] = useState('');
  const [state, setState] = useState({ view: null, history: null, error: null });
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const [revision, setRevision] = useState(0);
  const inFlight = useRef(false);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;
  useEffect(() => {
    setState({ view: null, history: null, error: null });
    if (!token || isDemoMode()) return undefined;
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const [view, history] = await Promise.all([getApproval(incidentId, { token, signal: controller.signal }), getApprovalHistory(incidentId, { token, signal: controller.signal })]);
        if (!controller.signal.aborted) setState({ view, history, error: null });
      } catch (error) { if (!controller.signal.aborted) setState(previous => ({ ...previous, error })); }
      if (!controller.signal.aborted) timer = setTimeout(load, 5000);
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [incidentId, token, revision]);
  const view = state.view || summary;
  async function decide(decision, retry = null) {
    if (inFlight.current || !state.view || (!retry && state.error) || !token) return;
    inFlight.current = true; setBusy(true);
    const request = retry || { body: { decision, package_revision: state.view.package_revision,
      candidate_revision: state.view.candidate_revision, comment }, key: actionKey() };
    try {
      const result = await decideApproval(incidentId, request.body, { token, idempotencyKey: request.key });
      setState(previous => ({ ...previous, view: result, error: null })); setPending(null);
    } catch (error) {
      setState(previous => ({ ...previous, error }));
      setPending(error.status === 503 || error.kind === 'network' ? request : null);
    } finally {
      setBusy(false); inFlight.current = false; setRevision(value => value + 1); onChangedRef.current?.();
    }
  }
  return <div className="approval-panel">
    <p>Human decision: <Badge tone={view?.status === 'APPROVED' ? 'ok' : 'review'}>{view?.status || 'PENDING'}</Badge></p>
    {isDemoMode() ? <p className="note">Human decisions are disabled for demo fixtures.</p> : <>
      {!configured && <p className="note">Reviewer authentication is not configured. Configure named reviewers on the backend using the human approval guide.</p>}
      <form className="reviewer-session" onSubmit={event => { event.preventDefault(); setToken(credential.trim()); onSessionChange?.(credential.trim()); setPending(null); }}>
        <label>Reviewer credential <input type="password" autoComplete="off" value={credential} onChange={event => setCredential(event.target.value)} placeholder="Named reviewer bearer token" /></label>
        <button className="btn" disabled={!configured || !credential.trim() || busy}>Inspect approval package</button>
        {token && <button className="btn" type="button" onClick={() => { setToken(''); onSessionChange?.(''); setCredential(''); setPending(null); }}>Clear credential</button>}
      </form>
      <p className="note">The credential is held in this view's memory. AI provider keys are not reviewer credentials.</p>
    </>}
    {view?.package_revision && <dl className="facts revision-list">
      <div className="fact"><dt>Inspected package</dt><dd><code>{view.package_revision}</code></dd></div>
      <div className="fact"><dt>Candidate</dt><dd><code>{view.candidate_revision}</code></dd></div>
      <div className="fact"><dt>Decision persistence</dt><dd>{view.persistence?.status || '—'}</dd></div>
    </dl>}
    {view?.blocking_reasons?.length > 0 && <ul className="reasons">{view.blocking_reasons.map(reason => <li key={reason}><code>{reason}</code></li>)}</ul>}
    {state.view?.package && <details className="raw"><summary>Inspect frozen evidence package</summary><pre>{JSON.stringify(state.view.package, null, 2)}</pre></details>}
    <label>Decision comment <textarea value={comment} maxLength={2000} onChange={event => setComment(event.target.value)} /></label>
    <div className="actions">
      <button className="btn btn-primary" disabled={busy || !!pending || !!state.error || !state.view?.can_approve
        || state.view?.candidate_revision !== candidateRevision
        || state.view?.package?.data?.binding?.investigation_job_id !== investigationJobId} onClick={() => decide('APPROVE')}>Approve inspected candidate</button>
      <button className="btn" disabled={busy || !!pending || !!state.error || !state.view?.can_reject} onClick={() => decide('REJECT')}>Reject inspected candidate</button>
      {pending && <button className="btn" disabled={busy || !token || !state.view} onClick={() => { setState(previous => ({ ...previous, error: null })); decide(pending.body.decision, pending); }}>Retry decision confirmation</button>}
    </div>
    {busy && <p role="status">Recording the human decision…</p>}
    {pending && <p className="note">Decision confirmation is pending. Retry uses the same decision and idempotency key.</p>}
    {state.error && <p className="inline-error" role="alert">{state.error.message}{state.error.reasons?.length ? ' · ' + state.error.reasons.join(', ') : ''}</p>}
    {view?.decision && <p>Recorded {view.decision.decision} by {view.decision.reviewer_id} at {view.decision.decided_at}.</p>}
    {state.history && <details className="raw"><summary>Decision audit history ({state.history.decisions.length})</summary><pre>{JSON.stringify(state.history, null, 2)}</pre></details>}
    <p className="note">Approval records a decision for these exact hashes. Activation, deployment, and equipment recovery remain separate.</p>
  </div>;
}

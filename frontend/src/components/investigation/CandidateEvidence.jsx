import { useEffect, useState } from 'react';
import { getInvestigationPatch } from '../../api.js';
import { isDemoMode } from '../../demo/fixtures.js';
import { Badge } from '../ui.jsx';

export function CandidateDiff({ candidate, jobId }) {
  const [state, setState] = useState({ text: '', error: null });
  useEffect(() => {
    setState({ text: '', error: null });
    if (!candidate || !jobId || isDemoMode()) return undefined;
    const controller = new AbortController();
    getInvestigationPatch(jobId, controller.signal).then(text => {
      if (!controller.signal.aborted) setState({ text, error: null });
    }).catch(error => { if (!controller.signal.aborted) setState({ text: '', error }); });
    return () => controller.abort();
  }, [jobId, candidate?.diff_revision]);
  if (!candidate) return <p className="muted">No generated candidate is available for this investigation.</p>;
  return <>
    <p><Badge tone="info">{candidate.proposal_origin}</Badge></p>
    <dl className="facts revision-list">
      {['original_revision', 'candidate_revision', 'diff_revision', 'snapshot_revision'].map(key => <div className="fact" key={key}><dt>{key}</dt><dd><code>{candidate[key] || '—'}</code></dd></div>)}
    </dl>
    {state.error ? <p className="inline-error" role="alert">{state.error.message}</p> : <pre className="actual-diff">{state.text || 'Loading actual diff…'}</pre>}
  </>;
}

export function CandidateTests({ candidate }) {
  if (!candidate) return <p className="muted">No acceptance-test evidence is available for this investigation.</p>;
  return <>
    <p>Verification: <Badge tone={candidate.verification_status === 'VERIFIED' ? 'ok' : 'review'}>{candidate.verification_status}</Badge></p>
    <div className="evidence-table-wrap"><table className="evidence-table"><thead><tr><th>Source</th><th>Passed</th><th>Failed</th><th>Skipped</th><th>Exit</th></tr></thead>
      <tbody>{['original', 'candidate'].map(label => {
        const result = candidate.tests?.[label];
        return <tr key={label}><th>{label}</th>{['passed', 'failed', 'skipped', 'exit_code'].map(key => <td key={key}>{result?.[key] ?? 'Not run'}</td>)}</tr>;
      })}</tbody></table></div>
    {['original', 'candidate'].map(label => {
      const tests = candidate.tests?.[label];
      return tests && <details className="raw" key={label}><summary>{label} case outcomes and output</summary>
        <ul>{tests.cases?.map(test => <li key={test.name}><code>{test.name}</code>: {test.outcome}</li>)}</ul>
        <pre>{tests.stdout || tests.stderr || 'No output recorded.'}</pre>
      </details>;
    })}
    {candidate.replay ? <dl className="facts">
      <div className="fact"><dt>Offline decision</dt><dd>{candidate.replay.original?.status} → {candidate.replay.candidate?.status}</dd></div>
      <div className="fact"><dt>Detection gap fixed</dt><dd>{String(candidate.replay.detection_gap_fixed)}</dd></div>
      <div className="fact"><dt>Fault still asserted in replay</dt><dd>{String(candidate.replay.cooling_fault_still_present)}</dd></div>
    </dl> : <p className="note">No verified offline replay is available.</p>}
    <p className="note">Software verification and physical equipment recovery are separate. This candidate remains offline.</p>
  </>;
}

import { isDemoMode } from '../demo/fixtures.js';
import { workspaceHref } from '../router.js';

export default function WorkspaceContext({ route, incidents }) {
  if (route.name === 'mission' || route.name === 'investigate') return null;
  const engineering = route.name === 'engineering';
  const records = incidents.data ?? [];
  const jira = records.filter(i => i.integrations?.jira_key).length;
  const slack = records.filter(i => i.integrations?.slack_status === 'DELIVERED').length;
  return <section className="workspace-context" aria-label={engineering ? 'Engineering workspace' : 'Operational oversight'}>
    <div><span className="eyebrow">{engineering ? 'ENGINEERING & MODERNIZATION' : 'OPERATIONAL OVERSIGHT'}{isDemoMode() ? ' · DEMO FIXTURES' : ''}</span><h2>{engineering ? 'The incident is the starting point.' : 'A shared view of the response.'}</h2><p>{engineering ? 'Run an investigation, inspect generated code and actual test evidence, request independent review, and inspect human approval below.' : 'Persisted incidents, notification outcomes, telemetry analytics, and backend-host health from the shared API.'}</p></div>
    {engineering ? <div className="context-links">{route.incidentId && <><button className="btn" onClick={() => document.getElementById('inc-evidence-h')?.scrollIntoView({ block: 'center', behavior: 'instant' })}>Mismatch evidence ↓</button><button className="btn" onClick={() => document.getElementById('verify-h')?.scrollIntoView({ block: 'center', behavior: 'instant' })}>Verification ↓</button></>}<a className="btn" href={workspaceHref('investigate', route.incidentId)}>Incident response ↗</a></div> : <dl className="context-stats"><div><dt>Current incidents</dt><dd>{incidents.data ? records.length : '—'}</dd></div><div><dt>Jira references</dt><dd>{incidents.data ? jira : '—'}</dd></div><div><dt>Slack confirmed</dt><dd>{incidents.data ? slack : '—'}</dd></div></dl>}
    <small>Workspace selection changes navigation, not permissions.</small>
  </section>;
}

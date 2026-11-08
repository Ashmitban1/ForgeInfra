import { useRef, useState } from 'react';
import { createJiraIssue } from '../../api.js';
import { isDemoMode } from '../../demo/fixtures.js';
import { safeHttpUrl } from '../../lib/format.js';

export default function JiraAction({ incident, onCreated }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inFlight = useRef(false);
  const demo = isDemoMode();
  const issue = result ?? incident.integrations;
  const url = safeHttpUrl(issue?.jira_url);

  async function create() {
    if (inFlight.current || demo) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      setResult(await createJiraIssue(incident.incident_id));
      onCreated();
    } catch (e) {
      setError(e.message);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  if (demo) return <p className="note">Demo incident — Jira creation is disabled. No demo data is sent to Jira.</p>;
  return (
    <div className="actions">
      {issue?.jira_key && url ? (
        <a className="btn btn-primary" href={url} target="_blank" rel="noreferrer noopener">View Jira Issue · {issue.jira_key}</a>
      ) : (
        <button type="button" className="btn btn-primary" disabled={pending || !!issue?.jira_key} onClick={create}>
          {pending ? 'Creating Jira Issue…' : 'Create Jira Issue'}
        </button>
      )}
      {pending && <p role="status">Waiting for Jira confirmation…</p>}
      {result && <p role="status">Jira confirmed {result.jira_key}.</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </div>
  );
}

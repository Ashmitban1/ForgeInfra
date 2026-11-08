import { usePolling } from '../../hooks/usePolling.js';
import { useRef, useState } from 'react';
import { notifyIncident, getJiraCapability, getSlackCapability } from '../../api.js';
import { isDemoMode } from '../../demo/fixtures.js';
import { safeHttpUrl } from '../../lib/format.js';

export default function JiraAction({ incident, onCreated }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inFlight = useRef(false);
  const demo = isDemoMode();
  const capability = usePolling(getJiraCapability, { intervalMs: 10000 });
  const slackCapability = usePolling(getSlackCapability, { intervalMs: 10000 });
  const issue = result ?? incident.integrations;
  const slackStatus = issue?.slack_status;
  const blocked = ['PENDING', 'UNCONFIRMED'].includes(slackStatus);
  const canNotify = !issue?.jira_key || (slackCapability.data === true && slackStatus !== 'DELIVERED');
  const url = safeHttpUrl(issue?.jira_url);

  async function create() {
    if (inFlight.current || demo || blocked || capability.data !== true) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      setResult(await notifyIncident(incident.incident_id));
      onCreated();
    } catch (e) {
      setError(e.message);
      onCreated();
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  if (demo) return <p className="note">Demo incident — Jira and Slack notifications are disabled. No demo data is sent.</p>;
  return (
    <div className="actions">
      {issue?.jira_key && url ? (
        <a className="btn btn-primary" href={url} target="_blank" rel="noreferrer noopener">View Jira Issue · {issue.jira_key}</a>
      ) : null}
      {canNotify && (
        <button type="button" className="btn btn-primary" disabled={pending || blocked || capability.data !== true} onClick={create}>
          {pending ? 'Notifying…' : issue?.jira_key ? 'Notify Slack / Retry' : slackCapability.data === true ? 'Create Jira Issue & Notify Slack' : 'Create Jira Issue'}
        </button>
      )}
      {!issue?.jira_key && capability.loading && <p role="status">Checking Jira route availability…</p>}
      {!issue?.jira_key && capability.data === false && <p className="note">Jira route unavailable. Start the backend with backend.integrations.app:app.</p>}
      {capability.error && <p className="inline-error" role="alert">{capability.error.message}</p>}
      {pending && <p role="status">Waiting for provider confirmation…</p>}
      {result && <p role="status">Jira confirmed {result.jira_key}.</p>}
      {slackStatus && <p role="status">Slack: {slackStatus}{issue?.slack_message_ts ? ` · ${issue.slack_message_ts}` : ''}</p>}
      {issue?.slack_error && <p className="inline-error" role="alert">Jira retained. {issue.slack_error}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </div>
  );
}

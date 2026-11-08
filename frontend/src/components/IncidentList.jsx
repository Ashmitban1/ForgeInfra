import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useChangedKeys } from '../hooks/useLiveEvents.js';
import { classifyStatus } from '../lib/health.js';
import { formatTime } from '../lib/format.js';
import { workspaceHref } from '../router.js';
import { Badge, SkeletonRows, StateMessage } from './ui.jsx';

const SEVERITY_TONE = { HIGH: 'fault', REVIEW: 'review' };
const STAGE_TONE = { pending: 'muted', done: 'ok', failed: 'fault', active: 'info', unknown: 'review' };

export function sortIncidents(incidents) {
  return [...incidents].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

const keyOf = i => i.incident_id;
const signatureOf = i => [i.status, i.investigation?.status, i.decision_review?.status,
  i.investigation?.tool_calls?.length ?? 0, i.integrations?.jira_key, i.integrations?.slack_message_id].join('|');

export default function IncidentList({ state, selectedId, linkLabel = 'Investigate', workspace = 'investigate' }) {
  const { data, error, loading, refresh } = state;
  const reduce = useReducedMotion();
  // Highlights an incident only when the API reports a real change in its status, tool calls or integrations.
  const changed = useChangedKeys(data, keyOf, signatureOf);
  if (loading) return <SkeletonRows rows={3} />;
  if (error && !data) {
    return (
      <StateMessage
        kind="error"
        title="Could not load incidents"
        action={<button type="button" className="btn" onClick={refresh}>Retry</button>}
      >
        {error.message}
      </StateMessage>
    );
  }
  if (!data?.length) {
    return (
      <StateMessage title="No incidents yet">
        Incidents appear when telemetry has a reliability reason. Run <code>python hardware/simulator.py --mode fault</code>.
      </StateMessage>
    );
  }
  return (
    <>
      {error && <p className="inline-error" role="alert">Refresh failed ({error.message}). Showing last data.</p>}
      <ul className="incident-list">
        <AnimatePresence initial={false}>
          {sortIncidents(data).map(incident => {
            const nemotron = incident.investigation?.status;
            const gemini = incident.decision_review?.status;
            const selected = incident.incident_id === selectedId;
            return (
              <motion.li
                key={incident.incident_id}
                layout
                initial={{ opacity: 0, x: -14 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
              >
                <a
                  className={`incident ${selected ? 'is-selected' : ''}`}
                  href={workspaceHref(workspace, incident.incident_id)}
                  aria-current={selected ? 'true' : undefined}
                >
                  {changed[incident.incident_id] && !reduce && (
                    <motion.span
                      key={changed[incident.incident_id]}
                      className="incident-flash"
                      aria-hidden="true"
                      initial={{ opacity: 0.8 }}
                      animate={{ opacity: 0 }}
                      transition={{ duration: 1.6, ease: 'easeOut' }}
                    />
                  )}
                  <div className="incident-top">
                    <strong className="mono">{incident.incident_id}</strong>
                    <Badge tone={SEVERITY_TONE[incident.severity] ?? 'muted'} icon="▲">{incident.severity ?? '—'}</Badge>
                  </div>
                  <p className="muted">
                    {incident.device_id} · {incident.status} · opened {formatTime(incident.created_at)}
                  </p>
                  <div className="chips">
                    <Badge tone={STAGE_TONE[classifyStatus(nemotron)]}>Nemotron: {nemotron ?? '—'}</Badge>
                    <Badge tone={STAGE_TONE[classifyStatus(gemini)]}>Gemini: {gemini ?? '—'}</Badge>
                    <Badge tone={incident.integrations?.jira_key ? 'ok' : 'muted'}>
                      Jira: {incident.integrations?.jira_key ?? 'not connected'}
                    </Badge>
                  </div>
                  {!selected && <span className="incident-cta">{linkLabel} →</span>}
                </a>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </>
  );
}

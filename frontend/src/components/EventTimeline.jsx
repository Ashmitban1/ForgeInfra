import { formatNumber, formatTime } from '../lib/format.js';
import { investigateHref } from '../router.js';
import { StateMessage } from './ui.jsx';

const MAX_EVENTS = 25;

export function buildEvents(incidents, history) {
  const events = [];
  for (const incident of incidents ?? []) {
    events.push({
      id: `inc-${incident.incident_id}`,
      at: incident.created_at,
      tone: incident.severity === 'HIGH' ? 'fault' : 'review',
      title: `Incident ${incident.incident_id} opened`,
      detail: `${incident.device_id} · severity ${incident.severity ?? '—'}`,
      href: investigateHref(incident.incident_id),
    });
  }
  for (const readings of Object.values(history)) {
    for (const r of readings) {
      const faulted = r.cooling_fault || r.expected_status === 'WARNING';
      events.push({
        id: `read-${r.device_id}-${r.key}`,
        at: r.at,
        tone: r.mismatch ? 'fault' : faulted ? 'review' : 'ok',
        title: `${r.device_id} reading: ${formatNumber(r.temperature_c)} °C, cooling fault ${r.cooling_fault ? 'reported' : 'not reported'}`,
        detail: `legacy ${r.legacy_status ?? '—'} · independent ${r.expected_status ?? '—'}${r.mismatch ? ' · MISMATCH' : ''} · ${r.source_kind}`,
      });
    }
  }
  return events
    .filter(e => Number.isFinite(Date.parse(e.at)))
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, MAX_EVENTS);
}

const ICON = { fault: '▲', review: '◆', ok: '●' };

export default function EventTimeline({ events }) {
  if (events.length === 0) {
    return <StateMessage title="No events yet">Events appear after the API receives telemetry or opens an incident.</StateMessage>;
  }
  return (
    <>
      <ol className="timeline">
        {events.map(event => (
            <li key={event.id} className={`event event-${event.tone}`}>
              <time className="mono" dateTime={event.at}>{formatTime(event.at)}</time>
              <span className="event-icon" aria-hidden="true">{ICON[event.tone]}</span>
              <div>
                <strong>{event.href ? <a href={event.href}>{event.title}</a> : event.title}</strong>
                <p className="muted">{event.detail}</p>
              </div>
            </li>
          ))}
      </ol>
      <p className="note">
        Timeline combines API incident timestamps with readings this tab observed while polling. Nemotron, Gemini,
        and Jira/Slack steps have no timestamps in API v1, so they are not shown here.
      </p>
    </>
  );
}

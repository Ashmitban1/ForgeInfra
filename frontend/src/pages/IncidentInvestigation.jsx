import { useEffect, useMemo } from 'react';
import { getIncident } from '../api.js';
import IncidentList, { sortIncidents } from '../components/IncidentList.jsx';
import MismatchEvidence from '../components/MismatchEvidence.jsx';
import ProgressPath from '../components/ProgressPath.jsx';
import { GeminiRecommendation, NemotronActivity } from '../components/investigation/Agents.jsx';
import {
  ApprovalActions, IntegrationResults, SampleDiff, SampleTests,
} from '../components/investigation/Scaffolds.jsx';
import { Badge, Fact, Panel, SkeletonRows, StateMessage } from '../components/ui.jsx';
import { usePolling } from '../hooks/usePolling.js';
import { formatDateTime } from '../lib/format.js';
import RepairVerification from '../components/investigation/RepairVerification.jsx';
import { deviceHealth, pathSteps, repairVerification } from '../lib/health.js';
import { missionHref, replaceHash, investigateHref } from '../router.js';

function IncidentDetail({ incidentId, telemetry, history, now }) {
  const detail = usePolling(signal => getIncident(incidentId, signal));
  const { data: incident, error, loading, refresh } = detail;
  const steps = useMemo(() => (incident ? pathSteps(incident) : []), [incident]);
  const liveDevice = incident ? (telemetry.data ?? []).find(d => d.device_id === incident.device_id) : null;
  const verification = incident
    ? repairVerification(incident, liveDevice ? deviceHealth(liveDevice, now, history[incident.device_id]) : null)
    : null;

  if (loading) {
    return (
      <div role="status" aria-label={`Loading ${incidentId}`}>
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (error && !incident) {
    const notFound = error.kind === 'not_found';
    return (
      <StateMessage
        kind="error"
        title={notFound ? `Incident ${incidentId} not found` : `Could not load ${incidentId}`}
        action={<button type="button" className="btn" onClick={refresh}>Retry</button>}
      >
        {notFound ? 'Backend storage is in-memory and resets whenever FastAPI restarts, so older IDs disappear.' : error.message}
      </StateMessage>
    );
  }

  return (
    <div className="detail">
      {error && <p className="inline-error" role="alert">Refresh failed ({error.message}). Showing last data.</p>}
      <Panel title={incident.incident_id} eyebrow="Selected incident" headingId="detail-h"
        actions={<a className="btn" href={missionHref}>← Mission Control</a>}>
        <div className="chips">
          <Badge tone={incident.severity === 'HIGH' ? 'fault' : 'review'} icon="▲">Severity {incident.severity ?? '—'}</Badge>
          <Badge tone="info">{incident.status ?? '—'}</Badge>
        </div>
        <dl className="facts">
          <Fact label="Device" mono>{incident.device_id}</Fact>
          <Fact label="Opened">{formatDateTime(incident.created_at)}</Fact>
          <Fact label="Last updated">{formatDateTime(incident.updated_at)}</Fact>
          <Fact label="Schema" mono>{incident.schema_version}</Fact>
        </dl>
        <ProgressPath steps={steps} />
      </Panel>

      <div className="split">
        <div className="col">
          <Panel title="Nemotron tool activity" eyebrow="Investigation" headingId="nemo-h">
            <NemotronActivity investigation={incident.investigation} />
          </Panel>
          <Panel title="Gemini recommendation" eyebrow="Decision review" headingId="gem-h">
            <GeminiRecommendation review={incident.decision_review} />
          </Panel>
          <Panel title="Source mismatch evidence" eyebrow="From this incident" headingId="inc-evidence-h">
            <MismatchEvidence source={incident} />
          </Panel>
        </div>
        <div className="col">
          <Panel title="Repair verification" eyebrow="Outcome" headingId="verify-h">
            <RepairVerification verification={verification} deviceId={incident.device_id} />
          </Panel>
          <Panel title="Approval" eyebrow="Human decision" sample="Scaffold — route not implemented" headingId="appr-h">
            <ApprovalActions />
          </Panel>
          <Panel title="Jira / Slack results" eyebrow="Integrations" headingId="integ-h">
            <IntegrationResults integrations={incident.integrations} />
          </Panel>
          <Panel title="Code diff" eyebrow="Proposed repair" sample headingId="diff-h">
            <SampleDiff />
          </Panel>
          <Panel title="Regression tests" eyebrow="Verification" sample headingId="tests-h">
            <SampleTests />
          </Panel>
        </div>
      </div>
    </div>
  );
}

export default function IncidentInvestigation({ incidentId, incidents, telemetry, history, now }) {
  const firstId = incidents.data?.length ? sortIncidents(incidents.data)[0].incident_id : null;

  useEffect(() => {
    if (!incidentId && firstId) replaceHash(investigateHref(firstId));
  }, [incidentId, firstId]);

  return (
    <div className="page">
      <div className="page-title">
        <span className="eyebrow">Incident Investigation</span>
        <h1>Investigate an incident</h1>
        <p className="muted">
          Details come from <code>GET /api/incidents/{'{id}'}</code>. Agent and repair stages stay pending until the backend reports them.
        </p>
      </div>
      <div className="grid-investigate">
        <aside aria-label="Incident selector" className="selector">
          <Panel title="Incidents" eyebrow="Select one" headingId="sel-h">
            <IncidentList state={incidents} selectedId={incidentId} linkLabel="Open" />
          </Panel>
        </aside>
        <div>
          {incidentId ? (
            <IncidentDetail key={incidentId} incidentId={incidentId} telemetry={telemetry} history={history} now={now} />
          ) : incidents.loading ? (
            <SkeletonRows rows={4} />
          ) : (
            <StateMessage title="No incident selected">
              {incidents.error && !incidents.data
                ? 'Incidents could not be loaded, so none can be selected.'
                : 'There are no incidents to investigate yet.'}
            </StateMessage>
          )}
        </div>
      </div>
    </div>
  );
}

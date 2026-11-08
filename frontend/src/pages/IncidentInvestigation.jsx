import { useEffect, useMemo, useState } from 'react';
import { getIncident, getIncidentHistory } from '../api.js';
import EventTimeline, { buildEvents } from '../components/EventTimeline.jsx';
import IncidentList, { sortIncidents } from '../components/IncidentList.jsx';
import MismatchEvidence from '../components/MismatchEvidence.jsx';
import ProgressPath from '../components/ProgressPath.jsx';
import { GeminiRecommendation, NemotronActivity } from '../components/investigation/Agents.jsx';
import { IntegrationResults } from '../components/investigation/Scaffolds.jsx';
import JiraAction from '../components/investigation/JiraAction.jsx';
import WorkflowControls from '../components/investigation/WorkflowControls.jsx';
import HumanApproval from '../components/investigation/HumanApproval.jsx';
import RepairProof from '../components/investigation/RepairProof.jsx';
import { CandidateDiff, CandidateTests } from '../components/investigation/CandidateEvidence.jsx';
import { Badge, Fact, Panel, SkeletonRows, StateMessage } from '../components/ui.jsx';
import { usePolling } from '../hooks/usePolling.js';
import { useIncidentWorkflow } from '../hooks/useIncidentWorkflow.js';
import { formatDateTime } from '../lib/format.js';
import RepairVerification from '../components/investigation/RepairVerification.jsx';
import { deviceHealth, pathSteps, repairVerification } from '../lib/health.js';
import { missionHref, replaceHash, workspaceHref } from '../router.js';

function IncidentContent({ incident, refresh, telemetry, history, now, backend, lifecycle }) {
  const [reviewerToken, setReviewerToken] = useState('');
  const workflow = useIncidentWorkflow(incident, refresh);
  const analysis = workflow.analysis.data;
  const steps = useMemo(() => pathSteps(incident, analysis), [incident, analysis]);
  const liveDevice = (telemetry.data || []).find(device => device.device_id === incident.device_id);
  const verification = repairVerification(incident, liveDevice ? deviceHealth(liveDevice, now, history[incident.device_id]) : null, workflow.candidate);
  const source = workflow.investigation.data;
  const investigation = { ...(analysis?.investigation || incident.investigation), ...(source ? {
    status: source.status, tool_calls: source.tool_calls, evidence_ids: source.evidence?.map(item => item.evidence_id),
    findings: source.result?.findings || [], summary: source.result?.summary, error: source.error,
  } : {}) };
  return <div className="detail">
    <Panel title={incident.incident_id} eyebrow="Selected incident" headingId="detail-h" actions={<a className="btn" href={missionHref}>← Mission Control</a>}>
      <div className="chips"><Badge tone={incident.severity === 'HIGH' ? 'fault' : 'review'}>{incident.severity}</Badge><Badge tone="info">{incident.status}</Badge></div>
      <dl className="facts"><Fact label="Device" mono>{incident.device_id}</Fact><Fact label="Opened">{formatDateTime(incident.created_at)}</Fact><Fact label="Last updated">{formatDateTime(incident.updated_at)}</Fact></dl>
      <ProgressPath steps={steps} />
      <WorkflowControls workflow={workflow} capabilities={backend?.agents} />
      <p className="note">Jira/Slack notification can run independently of investigation and approval. It does not resolve the incident.</p>
    </Panel>
    <Panel title="Incident lifecycle" eyebrow="Persisted event history" headingId="lifecycle-h">
      {lifecycle.error && <p className="inline-error" role="alert">{lifecycle.error.message}</p>}
      <EventTimeline events={buildEvents([], {}, lifecycle.data || [])} />
    </Panel>
    <div className="split"><div className="col">
      <Panel title="Nemotron tool activity" eyebrow="Investigation" headingId="nemo-h"><NemotronActivity investigation={investigation} /></Panel>
      <Panel title="Gemini recommendation" eyebrow="Independent review" headingId="gem-h"><GeminiRecommendation review={workflow.reviewSummary} /></Panel>
      <Panel title="Source mismatch evidence" eyebrow="Captured incident" headingId="inc-evidence-h"><MismatchEvidence source={incident} /></Panel>
      <Panel title="Code diff" eyebrow="Generated candidate" headingId="diff-h"><CandidateDiff candidate={workflow.candidate} jobId={workflow.sourceId} /></Panel>
    </div><div className="col">
      <Panel title="Repair verification" eyebrow="Software evidence" headingId="verify-h"><RepairVerification verification={verification} deviceId={incident.device_id} /></Panel>
      <Panel title="Regression tests" eyebrow="Actual acceptance results" headingId="tests-h"><CandidateTests candidate={workflow.candidate} /></Panel>
      <Panel title="Approval" eyebrow="Human decision" headingId="appr-h"><HumanApproval incidentId={incident.incident_id} summary={analysis?.approval} configured={backend?.agents?.approval_configured} onChanged={workflow.refresh} candidateRevision={workflow.candidate?.candidate_revision} investigationJobId={workflow.sourceId} onSessionChange={setReviewerToken} /></Panel>
      <Panel title="Solana RepairProof" eyebrow="Approved evidence · Devnet" headingId="proof-h"><RepairProof incidentId={incident.incident_id} token={reviewerToken} approvalVersion={analysis?.approval?.version} /></Panel>
      <Panel title="Jira / Slack results" eyebrow="Notifications" headingId="integ-h"><JiraAction incident={incident} onCreated={refresh} capabilities={backend?.integrations} /><IntegrationResults integrations={incident.integrations} /></Panel>
    </div></div>
  </div>;
}
function IncidentDetail({ incidentId, ...props }) {
  const detail = usePolling(signal => getIncident(incidentId, signal));
  const lifecycle = usePolling(signal => getIncidentHistory(incidentId, { signal }), { intervalMs: 15000 });
  if (detail.loading) return <SkeletonRows rows={6} />;
  if (!detail.data) return <StateMessage kind="error" title={'Could not load ' + incidentId} action={<button className="btn" onClick={detail.refresh}>Retry</button>}>{detail.error?.message}</StateMessage>;
  return <>{detail.error && <p className="inline-error" role="alert">{detail.error.message}. Showing the last saved incident.</p>}<IncidentContent incident={detail.data} refresh={detail.refresh} lifecycle={lifecycle} {...props} /></>;
}
export default function IncidentInvestigation({ incidentId, incidents, workspace = 'investigate', ...props }) {
  const firstId = incidents.data?.length ? sortIncidents(incidents.data)[0].incident_id : null;
  useEffect(() => { if (!incidentId && firstId) replaceHash(workspaceHref(workspace, firstId)); }, [incidentId, firstId, workspace]);
  return <div className="page"><div className="page-title"><span className="eyebrow">{workspace === 'engineering' ? 'Engineering evidence' : 'Incident Investigation'}</span><h1>{workspace === 'engineering' ? 'Evidence before a change.' : 'Understand the incident.'}</h1><p className="muted">Investigate, verify a candidate, request independent review, and inspect a human decision from the shared backend.</p></div>
    <div className="grid-investigate"><aside className="selector" aria-label="Incident selector"><Panel title="Incidents" eyebrow="Select one" headingId="sel-h"><IncidentList state={incidents} workspace={workspace} selectedId={incidentId} linkLabel="Open" /></Panel></aside>
      <div>{incidentId ? <IncidentDetail key={incidentId} incidentId={incidentId} {...props} /> : incidents.loading ? <SkeletonRows rows={4} /> : <StateMessage title="No incident selected">Submit telemetry or select an existing incident.</StateMessage>}</div>
    </div></div>;
}

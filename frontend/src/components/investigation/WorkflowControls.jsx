import { isDemoMode } from '../../demo/fixtures.js';
import { activeJob } from '../../hooks/useIncidentWorkflow.js';

export default function WorkflowControls({ workflow, capabilities }) {
  const source = workflow.source;
  const sourceActive = activeJob(source);
  const reviewActive = activeJob(workflow.reviewJob || workflow.reviewSummary);
  const demo = isDemoMode();
  const error = workflow.error || workflow.investigation.error || workflow.review.error;
  const jobError = workflow.investigation.data?.error || source?.error;
  return <div className="workflow-controls">
    <div className="actions">
      <button className="btn btn-primary" disabled={demo || !capabilities?.configured || !!workflow.pending || sourceActive || reviewActive}
        onClick={() => workflow.run('investigate')}>
        {workflow.pending === 'investigate' ? 'Submitting investigation…' : sourceActive ? 'Investigation running…' : source?.job_id ? 'Run new investigation / Retry' : 'Run investigation'}
      </button>
      <button className="btn" disabled={demo || !capabilities?.gemini_configured || !!workflow.pending || source?.status !== 'COMPLETED' || reviewActive}
        onClick={() => workflow.run('review')}>
        {workflow.pending === 'review' ? 'Submitting review…' : reviewActive ? 'Gemini review running…' : 'Request Gemini review'}
      </button>
    </div>
    {demo ? <p className="note">Demo fixtures cannot submit AI jobs.</p> : <>
      {capabilities?.unavailable ? <p className="inline-error" role="alert">Agent capabilities unavailable: {capabilities.error}</p> : <>
        {!capabilities?.configured && <p className="note">Investigation requires backend NVIDIA configuration.</p>}
        {!capabilities?.gemini_configured && <p className="note">Independent review requires backend Gemini configuration.</p>}
      </>}
      <p className="note">Each action starts a background job. Evidence changes can require a new investigation; the backend checks currentness.</p>
    </>}
    {error && <p className="inline-error" role="alert">{error.message}{error.reasons?.length ? ' · ' + error.reasons.join(', ') : ''}</p>}
    {jobError && <p className="inline-error" role="alert">{jobError.code}: {jobError.message || String(jobError)}</p>}
    {workflow.review.data?.error && <p className="inline-error" role="alert">{workflow.review.data.error.code}: {workflow.review.data.error.message}</p>}
    {workflow.analysis.error && <p className="inline-error" role="alert">Current eligibility could not be refreshed: {workflow.analysis.error.message}</p>}
  </div>;
}

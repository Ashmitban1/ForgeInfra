import { useCallback, useEffect, useRef, useState } from 'react';
import { getIncidentAnalysis, getInvestigation, getReview, submitInvestigation, submitReview } from '../api.js';
import { isDemoMode } from '../demo/fixtures.js';
import { usePolling } from './usePolling.js';

export const activeJob = job => Boolean(job?.job_id) && ['QUEUED', 'PENDING', 'RUNNING'].includes(job.status);
export const actionKey = () => globalThis.crypto?.randomUUID?.() || Date.now() + '-' + Math.random().toString(36).slice(2);

function useJob(id, fetcher) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    if (!id || isDemoMode()) { setState({ data: null, error: null }); return undefined; }
    const controller = new AbortController();
    let timer;
    setState({ data: null, error: null });
    async function poll() {
      try {
        const data = await fetcher(id, controller.signal);
        if (controller.signal.aborted) return;
        setState({ data, error: null });
        if (activeJob(data)) timer = setTimeout(poll, 2000);
      } catch (error) {
        if (controller.signal.aborted) return;
        setState(previous => ({ ...previous, error }));
        timer = setTimeout(poll, 5000);
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, fetcher]);
  return { ...state, data: state.data?.job_id === id ? state.data : null };
}

export function useIncidentWorkflow(incident, onRefresh) {
  const analysis = usePolling(signal => isDemoMode() ? Promise.resolve(null) : getIncidentAnalysis(incident.incident_id, signal));
  const [sourceId, setSourceId] = useState(incident.investigation?.job_id);
  const [reviewId, setReviewId] = useState(incident.decision_review?.job_id);
  const [accepted, setAccepted] = useState({});
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const keys = useRef({});
  const inFlight = useRef(false);
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  const sourceRef = analysis.data?.investigation?.job_id || incident.investigation?.job_id;
  const reviewRef = analysis.data?.decision_review?.job_id || incident.decision_review?.job_id;
  useEffect(() => { if (sourceRef) setSourceId(sourceRef); }, [sourceRef]);
  useEffect(() => { if (reviewRef) setReviewId(reviewRef); }, [reviewRef]);
  const investigation = useJob(sourceId, getInvestigation);
  const review = useJob(reviewId, getReview);
  const refresh = useCallback(() => { analysis.refresh(); onRefresh?.(); }, [analysis.refresh, onRefresh]);
  async function run(kind) {
    if (inFlight.current || isDemoMode()) return;
    inFlight.current = true;
    controller.current = new AbortController();
    setPending(kind); setError(null);
    keys.current[kind] ||= actionKey();
    try {
      const submit = kind === 'investigate' ? submitInvestigation : submitReview;
      const job = await submit(incident.incident_id, { idempotencyKey: keys.current[kind], signal: controller.current.signal });
      setAccepted(previous => ({ ...previous, [kind]: job }));
      if (kind === 'investigate') setSourceId(job.job_id); else setReviewId(job.job_id);
      keys.current[kind] = null;
      refresh();
    } catch (failure) {
      if (failure.name !== 'AbortError') {
        setError(failure);
        if (failure.status && failure.status < 500) keys.current[kind] = null;
      }
    } finally {
      if (!controller.current.signal.aborted) setPending(null);
      inFlight.current = false;
    }
  }
  const source = investigation.data || (accepted.investigate?.job_id === sourceId ? accepted.investigate : null)
    || analysis.data?.investigation || incident.investigation;
  const candidate = investigation.data?.status === 'COMPLETED' ? investigation.data.result?.generated_repair : null;
  return { analysis, investigation, review, source, sourceId, candidate, pending, error, refresh, run,
    reviewJob: review.data || (accepted.review?.job_id === reviewId ? accepted.review : null),
    reviewSummary: analysis.data?.decision_review || incident.decision_review };
}

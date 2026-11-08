import { demoGetIncident, demoGetIncidents, demoGetTelemetry, isDemoMode } from './demo/fixtures.js';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');

export class ApiError extends Error {
  constructor(message, { kind, status = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

async function getJson(path, signal, method = 'GET') {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal, method, headers: { Accept: 'application/json' } });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new ApiError(`Cannot reach the FactoryOS API at ${API_BASE}. Is the backend running?`, { kind: 'network' });
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch { /* non-JSON error body */ }
    const kind = response.status === 404 ? 'not_found' : 'http';
    throw new ApiError(detail || `API returned HTTP ${response.status}`, { kind, status: response.status });
  }
  try {
    return await response.json();
  } catch {
    throw new ApiError('API returned a response that is not valid JSON.', { kind: 'shape' });
  }
}

function requireArray(body, key) {
  if (!body || !Array.isArray(body[key])) {
    throw new ApiError(`API response is missing the "${key}" list required by the v1 contract.`, { kind: 'shape' });
  }
  return body[key];
}

export async function getLatestTelemetry(signal) {
  if (isDemoMode()) return demoGetTelemetry();
  return requireArray(await getJson('/api/telemetry/latest', signal), 'devices');
}

export async function getIncidents(signal) {
  if (isDemoMode()) return demoGetIncidents();
  return requireArray(await getJson('/api/incidents', signal), 'incidents');
}

export async function getIncident(incidentId, signal) {
  if (isDemoMode()) return demoGetIncident(incidentId);
  const body = await getJson(`/api/incidents/${encodeURIComponent(incidentId)}`, signal);
  if (!body || typeof body !== 'object' || body.incident_id !== incidentId) {
    throw new ApiError('API returned an incident that does not match the requested ID.', { kind: 'shape' });
  }
  return body;
}

export async function notifyIncident(incidentId) {
  if (isDemoMode()) throw new ApiError('Demo incidents cannot be sent to Jira.', { kind: 'demo' });
  const body = await getJson(`/api/incidents/${encodeURIComponent(incidentId)}/notify`, undefined, 'POST');
  if (!body?.jira_key || !body?.jira_url || body.incident_id !== incidentId) {
    throw new ApiError('Backend did not confirm a Jira issue. Refresh before retrying.', { kind: 'shape' });
  }
  return body;
}

export async function getJiraCapability(signal) {
  if (isDemoMode()) return false;
  try {
    const body = await getJson('/api/integrations/capabilities', signal);
    return body?.jira?.notify === true;
  } catch (error) {
    if (error.status === 404) return false;
    throw error;
  }
}

// Compatibility for callers using the original Jira action name.
export const createJiraIssue = notifyIncident;

export async function getSlackCapability(signal) {
  if (isDemoMode()) return false;
  try {
    const body = await getJson('/api/integrations/capabilities', signal);
    return body?.slack?.notify === true;
  } catch (error) {
    if (error.status === 404) return false;
    throw error;
  }
}

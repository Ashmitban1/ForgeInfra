import { demoGetIncident, demoGetIncidents, demoGetTelemetry, isDemoMode } from './demo/fixtures.js';

export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
export class ApiError extends Error {
  constructor(message, { kind = 'http', status = null, code = null, reasons = [], detail = null } = {}) {
    super(message);
    Object.assign(this, { name: 'ApiError', kind, status, code, reasons, detail });
  }
}

export async function request(path, { method = 'GET', body, signal, headers = {}, token, idempotencyKey, text = false } = {}) {
  if (!path.startsWith('/') || path.startsWith('//')) throw new ApiError('Invalid API path.', { kind: 'shape' });
  if (method !== 'GET' && isDemoMode()) throw new ApiError('Actions are disabled for demo data.', { kind: 'demo' });
  const requestHeaders = { Accept: text ? 'text/plain' : 'application/json', ...headers };
  if (body !== undefined) requestHeaders['Content-Type'] = 'application/json';
  if (token) requestHeaders.Authorization = 'Bearer ' + token;
  if (idempotencyKey) requestHeaders['Idempotency-Key'] = idempotencyKey;
  let response;
  try {
    response = await fetch(API_BASE + path, { method, signal, headers: requestHeaders,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new ApiError('Cannot reach the ForgeInfra API at ' + API_BASE + '.', { kind: 'network' });
  }
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { detail = null; }
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => (item.loc || []).join('.') + ': ' + item.msg).join('; ')
      : detail?.message || 'API returned HTTP ' + response.status;
    throw new ApiError(message, { kind: response.status === 404 ? 'not_found' : 'http', status: response.status,
      code: detail?.code, reasons: detail?.reasons || [], detail });
  }
  if (text) return response.text();
  try { return await response.json(); } catch { throw new ApiError('API returned invalid JSON.', { kind: 'shape' }); }
}
function list(body, key) {
  if (!Array.isArray(body?.[key])) throw new ApiError('API is missing the ' + key + ' list.', { kind: 'shape' });
  return body[key];
}
const incidentPath = id => '/api/incidents/' + encodeURIComponent(id);
const jobPath = (kind, id) => '/api/' + kind + '/' + encodeURIComponent(id);
function query(options) {
  return new URLSearchParams(Object.entries(options).filter(([, value]) => value != null)).toString();
}
export async function getLatestTelemetry(signal) {
  return isDemoMode() ? demoGetTelemetry() : list(await request('/api/telemetry/latest', { signal }), 'devices');
}
export async function getIncidents(signal) {
  return isDemoMode() ? demoGetIncidents() : list(await request('/api/incidents', { signal }), 'incidents');
}
export async function getIncident(id, signal) {
  if (isDemoMode()) return demoGetIncident(id);
  const result = await request(incidentPath(id), { signal });
  if (result?.incident_id !== id) throw new ApiError('API returned a different incident.', { kind: 'shape' });
  return result;
}
export const getIncidentAnalysis = (id, signal) => request(incidentPath(id) + '/analysis', { signal });
export async function getIncidentHistory(id, { limit = 100, signal } = {}) {
  if (isDemoMode()) return [];
  return list(await request(incidentPath(id) + '/history?' + query({ limit }), { signal }), 'events');
}
export const submitInvestigation = (id, options = {}) => request(incidentPath(id) + '/investigate', { ...options, method: 'POST' });
export const getInvestigation = (id, signal) => request(jobPath('investigations', id), { signal });
export const getInvestigationPatch = (id, signal) => request(jobPath('investigations', id) + '/patch', { signal, text: true });
export const submitReview = (id, options = {}) => request(incidentPath(id) + '/review', { ...options, method: 'POST' });
export const getReview = (id, signal) => request(jobPath('reviews', id), { signal });
export const submitRepair = (id, options = {}) => request(incidentPath(id) + '/repair', { ...options, method: 'POST' });
export const getRepair = (id, signal) => request(jobPath('repairs', id), { signal });
export const getRepairReport = (id, signal) => request(jobPath('repairs', id) + '/report', { signal });
export const getRepairDiff = (id, signal) => request(jobPath('repairs', id) + '/diff', { signal, text: true });
export const getApproval = (id, options = {}) => request(incidentPath(id) + '/approval', options);
export const getApprovalHistory = (id, options = {}) => request(incidentPath(id) + '/approval/history', options);
export const decideApproval = (id, body, options = {}) => request(incidentPath(id) + '/approval', { ...options, method: 'POST', body });
export const getRepairProofReadiness = (id, options = {}) => request(incidentPath(id) + '/repair-proofs', options);
export const publishRepairProof = (id, body, options = {}) => request(incidentPath(id) + '/repair-proofs', { ...options, method: 'POST', body });
export const verifyRepairProof = (id, options = {}) => request(jobPath('repair-proofs', id) + '/verify', options);
export const getRepairProofBundle = (id, options = {}) => request(jobPath('repair-proofs', id) + '/bundle', options);
export const reconcileRepairProof = (id, options = {}) => request(jobPath('repair-proofs', id) + '/reconcile', { ...options, method: 'POST' });
export const updateIncident = (id, body, options = {}) => request(incidentPath(id) + '/updates', { ...options, method: 'POST', body });
export async function notifyIncident(id) {
  const result = await request(incidentPath(id) + '/notify', { method: 'POST' });
  if (!result?.jira_key || !result?.jira_url || result.incident_id !== id) throw new ApiError('Provider confirmation is incomplete; refresh before retrying.', { kind: 'shape' });
  return result;
}
export const createJiraIssue = notifyIncident;
export const getIntegrationCapabilities = signal => request('/api/integrations/capabilities', { signal });
export const getAgentCapabilities = signal => request('/api/agents/capabilities', { signal });
export const getModernizationCapabilities = signal => request('/api/modernization/capabilities', { signal });
export const getStorageHealth = signal => request('/api/storage/health', { signal });
export const getTelemetryStorageHealth = signal => request('/api/telemetry/storage/health', { signal });
export const getSystemMetrics = signal => request('/api/system/metrics', { signal });
export async function getJiraCapability(signal) {
  if (isDemoMode()) return false;
  try { return (await getIntegrationCapabilities(signal))?.jira?.notify === true; }
  catch (error) { if (error.status === 404) return false; throw error; }
}
export async function getSlackCapability(signal) {
  if (isDemoMode()) return false;
  try { return (await getIntegrationCapabilities(signal))?.slack?.notify === true; }
  catch (error) { if (error.status === 404) return false; throw error; }
}
export async function getBackendStatus(signal) {
  if (isDemoMode()) return { demo: true };
  const routes = { health: '/health', storage: '/api/storage/health', telemetryStorage: '/api/telemetry/storage/health',
    agents: '/api/agents/capabilities', modernization: '/api/modernization/capabilities', integrations: '/api/integrations/capabilities' };
  return Object.fromEntries(await Promise.all(Object.entries(routes).map(async ([key, path]) => {
    try { return [key, await request(path, { signal })]; }
    catch (error) { if (error.name === 'AbortError') throw error; return [key, { unavailable: true, error: error.message, httpStatus: error.status }]; }
  })));
}
export async function getTelemetrySources(signal) {
  if (isDemoMode()) return [];
  return list(await request('/api/telemetry/sources', { signal }), 'sources');
}
export async function getTelemetryHistory({ sourceKind, sourceId, start, end, limit = 300, signal }) {
  if (isDemoMode()) return [];
  return list(await request('/api/telemetry/history?' + query({ source_kind: sourceKind, source_id: sourceId, start, end, limit }), { signal }), 'samples');
}
export async function getTelemetrySummary({ sourceKind, sourceId, start, end, bucketSeconds = 300, signal }) {
  if (isDemoMode()) return [];
  return list(await request('/api/telemetry/summary?' + query({ source_kind: sourceKind, source_id: sourceId, start, end, bucket_seconds: bucketSeconds }), { signal }), 'buckets');
}

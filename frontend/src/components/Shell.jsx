import { API_BASE } from '../api.js';
import { isDemoMode, setDemoMode } from '../demo/fixtures.js';
import { formatTime } from '../lib/format.js';
import { landingHref, workspaceHref, missionHref } from '../router.js';
import FactoryOSLogo from './brand/FactoryOSLogo.jsx';

function connectionState({ loading, error, updatedAt }, demo) {
  if (demo) return { tone: 'demo', label: 'Demo data' };
  if (loading) return { tone: 'muted', label: 'Connecting…' };
  if (error && !updatedAt) return { tone: 'fault', label: 'Backend unreachable' };
  if (error) return { tone: 'review', label: 'Connection lost — showing last data' };
  return { tone: 'ok', label: 'API connected' };
}

export default function Shell({ route, polling, children, backend }) {
  const demo = isDemoMode();
  const conn = connectionState(polling, demo);
  const nav = [
    { id: 'mission', label: 'Mission Control', href: missionHref },
    { id: 'investigate', label: 'Incident Investigation', href: workspaceHref('investigate', route.incidentId) },
    { id: 'engineering', label: 'Engineering', href: workspaceHref('engineering', route.incidentId) },
    { id: 'operations', label: 'Oversight', href: workspaceHref('operations') },
  ];
  return (
    <div className="shell" data-workspace={route.name}>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="topbar">
        <a className="brand app-brand" href={landingHref} aria-label="FactoryOS product overview"><FactoryOSLogo /><span className="eyebrow">OPERATIONS WORKSPACE</span></a>
        <nav aria-label="Primary">
          {nav.map(item => (
            <a key={item.id} href={item.href} aria-current={route.name === item.id ? 'page' : undefined}>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="connection">
          <span className={`conn-pill conn-${conn.tone}`} role="status" aria-live="polite">
            <span className="conn-dot" aria-hidden="true" />
            {conn.label}
          </span>
          <span className="conn-meta">
            {polling.updatedAt ? `API checked ${formatTime(new Date(polling.updatedAt).toISOString())}` : 'No data yet'}
          </span>
          <button type="button" className="btn" onClick={() => setDemoMode(!demo)} aria-pressed={demo}>
            Demo data: {demo ? 'on' : 'off'}
          </button>
          <button type="button" className="btn" onClick={polling.refresh} disabled={polling.refreshing}>
            {polling.refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>
      {demo && (
        <p className="demo-banner" role="note">
          <strong>Demo mode.</strong> Everything on screen is hardcoded sample data, not from the FactoryOS backend.
          Turn “Demo data” off to see live API state.
        </p>
      )}
      <main id="main" tabIndex={-1}>{children}</main>
      <footer className="footer">
        API: <span className="mono">{demo ? 'not used (demo mode)' : API_BASE}</span>
        {!demo && <> · Incidents: {backend?.storage?.backend || 'checking'} / {backend?.storage?.unavailable ? 'UNAVAILABLE' : backend?.storage?.status || 'checking'}
          {' · '}Telemetry: Tiger Data / {backend?.telemetryStorage?.unavailable ? 'UNAVAILABLE' : backend?.telemetryStorage?.status || 'checking'}
          {' · '}Pending writes: {(backend?.storage?.pending_incidents || 0) + (backend?.storage?.pending_evidence || 0) + (backend?.storage?.pending_events || 0) + (backend?.telemetryStorage?.pending_samples || 0)}</>}
        {' · '}Local prototype. Observation freshness is shown separately from API availability.
      </footer>
    </div>
  );
}

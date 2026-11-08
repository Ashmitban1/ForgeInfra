import { MotionConfig } from 'motion/react';
import { lazy, Suspense, useEffect, useMemo, useRef } from 'react';
import { getBackendStatus, getIncidents, getLatestTelemetry, getTelemetrySources } from './api.js';
import Shell from './components/Shell.jsx';
import { useNow, usePolling } from './hooks/usePolling.js';
import { useIncidentHistory, useTelemetryHistory } from './hooks/useTelemetryHistory.js';
import { rackSources } from './lib/history.js';
import IncidentInvestigation from './pages/IncidentInvestigation.jsx';
import MissionControl from './pages/MissionControl.jsx';
import { useRoute } from './router.js';
import WorkspaceContext from './components/WorkspaceContext.jsx';

const LandingPage = lazy(() => import('./pages/LandingPage.jsx'));

function OperationalApp({ route }) {
  const contextRoute = route;
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); }, [route.name]);
  const now = useNow(1000);
  const telemetry = usePolling(getLatestTelemetry);
  const incidents = usePolling(getIncidents);
  const backend = usePolling(getBackendStatus, { intervalMs: 15000 });
  const sources = usePolling(getTelemetrySources, { intervalMs: 15000 });
  const knownDevices = useMemo(() => rackSources(telemetry.data || [], incidents.data || [], sources.data || []),
    [telemetry.data, incidents.data, sources.data]);
  const displayedTelemetry = { ...telemetry, data: telemetry.data || knownDevices.length ? knownDevices : null };
  const historyState = useTelemetryHistory(telemetry.data, { incidents: incidents.data || [], sources: sources.data || [],
    enabled: backend.data?.telemetryStorage?.status !== 'DISABLED' });
  const history = historyState.history;
  const lifecycle = useIncidentHistory(incidents.data || []);

  const updates = [telemetry.updatedAt, incidents.updatedAt].filter(Boolean);
  const polling = {
    loading: telemetry.loading || incidents.loading,
    refreshing: telemetry.refreshing || incidents.refreshing,
    error: telemetry.error || incidents.error,
    updatedAt: updates.length ? Math.min(...updates) : null,
    refresh: () => { telemetry.refresh(); incidents.refresh(); },
  };

  return (
    <Shell route={contextRoute} polling={polling} backend={backend.data}>
        {(historyState.error || lifecycle.error || sources.error) && <p className="inline-error" role="alert">Some persisted history could not be loaded: {(historyState.error || lifecycle.error || sources.error).message}</p>}
        <WorkspaceContext route={contextRoute} incidents={incidents} backend={backend.data} />
        {['investigate', 'engineering'].includes(route.name) ? (
          <IncidentInvestigation key={contextRoute.incidentId ?? 'none'} workspace={route.name} incidentId={contextRoute.incidentId} incidents={incidents} telemetry={displayedTelemetry} history={history} now={now} backend={backend.data} />
        ) : (
          <MissionControl telemetry={displayedTelemetry} incidents={incidents} history={history} now={now} backend={backend.data} persistedEvents={lifecycle.events} oversight={route.name === 'operations'} />
        )}
      </Shell>
  );
}

export default function App() {
  const route = useRoute();
  const selectedIncident = useRef(null);
  if (route.incidentId) selectedIncident.current = route.incidentId;
  const contextRoute = { ...route, incidentId: route.incidentId ?? selectedIncident.current };
  useEffect(() => {
    document.title = route.name === 'landing' ? 'FactoryOS — Reliability, engineered.' : 'FactoryOS — ' + ({ mission: 'Mission Control', investigate: 'Incident Investigation', engineering: 'Engineering Evidence', operations: 'Operational Oversight' }[route.name] ?? 'Operations');
  }, [route.name]);
  return (
    <MotionConfig reducedMotion="user">
      {route.name === 'landing'
        ? <Suspense fallback={<div className="landing-loading" role="status">Loading FactoryOS overview…</div>}><LandingPage section={route.section} /></Suspense>
        : <OperationalApp route={contextRoute} />}
    </MotionConfig>
  );
}

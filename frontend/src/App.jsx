import { MotionConfig } from 'motion/react';
import { lazy, Suspense, useEffect, useRef } from 'react';
import { getIncidents, getLatestTelemetry } from './api.js';
import Shell from './components/Shell.jsx';
import { useNow, usePolling } from './hooks/usePolling.js';
import { useTelemetryHistory } from './hooks/useTelemetryHistory.js';
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
  const history = useTelemetryHistory(telemetry.data);

  const updates = [telemetry.updatedAt, incidents.updatedAt].filter(Boolean);
  const polling = {
    loading: telemetry.loading || incidents.loading,
    refreshing: telemetry.refreshing || incidents.refreshing,
    error: telemetry.error || incidents.error,
    updatedAt: updates.length ? Math.min(...updates) : null,
    refresh: () => { telemetry.refresh(); incidents.refresh(); },
  };

  return (
    <Shell route={contextRoute} polling={polling}>
        <WorkspaceContext route={contextRoute} incidents={incidents} />
        {['investigate', 'engineering'].includes(route.name) ? (
          <IncidentInvestigation key={contextRoute.incidentId ?? 'none'} workspace={route.name} incidentId={contextRoute.incidentId} incidents={incidents} telemetry={telemetry} history={history} now={now} />
        ) : (
          <MissionControl telemetry={telemetry} incidents={incidents} history={history} now={now} />
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

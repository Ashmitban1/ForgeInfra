import { MotionConfig } from 'motion/react';
import { getIncidents, getLatestTelemetry } from './api.js';
import Shell from './components/Shell.jsx';
import { useNow, usePolling } from './hooks/usePolling.js';
import { useTelemetryHistory } from './hooks/useTelemetryHistory.js';
import IncidentInvestigation from './pages/IncidentInvestigation.jsx';
import MissionControl from './pages/MissionControl.jsx';
import { useRoute } from './router.js';

export default function App() {
  const route = useRoute();
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
    <MotionConfig reducedMotion="user">
      <Shell route={route} polling={polling}>
        {route.name === 'investigate' ? (
          <IncidentInvestigation key={route.incidentId ?? 'none'} incidentId={route.incidentId} incidents={incidents} telemetry={telemetry} history={history} now={now} />
        ) : (
          <MissionControl telemetry={telemetry} incidents={incidents} history={history} now={now} />
        )}
      </Shell>
    </MotionConfig>
  );
}

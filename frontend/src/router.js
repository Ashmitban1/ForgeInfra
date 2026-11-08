import { useEffect, useState } from 'react';

function parseHash() {
  const path = window.location.hash.replace(/^#/, '') || '/';
  const parts = path.split('/').filter(Boolean);
  if (parts[0] === 'investigate') {
    let incidentId = null;
    if (parts[1]) {
      try { incidentId = decodeURIComponent(parts[1]); } catch { incidentId = parts[1]; }
    }
    return { name: 'investigate', incidentId };
  }
  return { name: 'mission' };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export const missionHref = '#/';
export const investigateHref = incidentId =>
  incidentId ? `#/investigate/${encodeURIComponent(incidentId)}` : '#/investigate';

export function replaceHash(href) {
  window.history.replaceState(null, '', href);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

import { useEffect, useState } from 'react';

export function parseRoute(hash = window.location.hash) {
  // Keep the original #/ Mission Control route; a bare URL opens the new overview.
  if (!hash || !hash.startsWith('#/')) {
    const section = hash.replace(/^#/, '');
    return { name: 'landing', section: ['overview', 'architecture', 'people', 'mission', 'workspaces'].includes(section) ? section : null };
  }
  const parts = hash.slice(2).split('/').filter(Boolean);
  if (['investigate', 'engineering'].includes(parts[0])) {
    let incidentId = null;
    if (parts[1]) {
      try { incidentId = decodeURIComponent(parts[1]); } catch { incidentId = parts[1]; }
    }
    return { name: parts[0], incidentId };
  }
  if (parts[0] === 'operations') return { name: 'operations' };
  return { name: 'mission' };
}

export function useRoute() {
  const [route, setRoute] = useState(parseRoute);
  useEffect(() => {
    const onChange = () => setRoute(parseRoute());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export const landingHref = '#overview';
export const missionHref = '#/';
export const investigateHref = incidentId =>
  incidentId ? `#/investigate/${encodeURIComponent(incidentId)}` : '#/investigate';
export const workspaceHref = (name, incidentId) => name === 'mission' ? missionHref
  : name === 'operations' ? '#/operations'
    : `#/${name === 'engineering' ? 'engineering' : 'investigate'}${incidentId ? '/' + encodeURIComponent(incidentId) : ''}`;

export function replaceHash(href) {
  window.history.replaceState(null, '', href);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

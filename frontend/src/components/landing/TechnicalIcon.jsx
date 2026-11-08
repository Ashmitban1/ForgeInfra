export default function TechnicalIcon({ kind, size = 24 }) {
  const paths = {
    signal: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8 11h8M8 15h3m3 0h2M8 18h8" /></>,
    compare: <><path d="M4 4v6h6M20 20v-6h-6M4 10a8 8 0 0 1 14-5m2 9A8 8 0 0 1 6 19" /><path d="m10 9 4 6m0-6-4 6" /></>,
    code: <><path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-14-2 16" /></>,
    verify: <><path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z" /><path d="m8 12 3 3 5-6" /></>,
    response: <><rect x="3" y="3" width="18" height="14" rx="2" /><path d="m7 21 5-4M7 8h10M7 12h6" /></>,
    layers: <><path d="m12 2 10 5-10 5L2 7Zm-10 10 10 5 10-5M2 17l10 5 10-5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind] ?? paths.signal}</svg>;
}

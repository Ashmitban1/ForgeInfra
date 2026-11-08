import { useCallback, useEffect, useRef, useState } from 'react';

const INITIAL = { data: null, error: null, loading: true, refreshing: false, updatedAt: null };

// Keeps the last good data when a later poll fails so the UI can show stale data plus an error.
export function usePolling(fetcher, { intervalMs = 3000 } = {}) {
  const [state, setState] = useState(INITIAL);
  const fetcherRef = useRef(fetcher);
  const controllerRef = useRef(null);

  useEffect(() => { fetcherRef.current = fetcher; });

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState(s => ({ ...s, refreshing: true }));
    try {
      const data = await fetcherRef.current(controller.signal);
      if (controller.signal.aborted) return;
      setState({ data, error: null, loading: false, refreshing: false, updatedAt: Date.now() });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState(s => ({ ...s, error, loading: false, refreshing: false }));
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(() => { if (!document.hidden) refresh(); }, intervalMs);
    const onVisible = () => { if (!document.hidden) refresh(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
      controllerRef.current?.abort();
    };
  }, [refresh, intervalMs]);

  return { ...state, refresh };
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

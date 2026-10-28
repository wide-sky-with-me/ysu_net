import type { Transport } from './protocol';

interface ObservationEvents {
  window: Pick<EventTarget, 'addEventListener' | 'removeEventListener'>;
  document: Pick<Document, 'addEventListener' | 'removeEventListener' | 'visibilityState'>;
}

/** Advisory browser events request a native query; they never assert online/offline.
 * Decision: .agents/notes/implemented/desktop/2026-10-27-passive-state-observation.md
 */
export function beginStateObservation(transport: Transport, events: ObservationEvents): () => void {
  if (transport.mode !== 'desktop') return () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight = false;
  let requested = false;
  let stopped = false;
  const schedule = () => {
    if (!stopped && requested && !inFlight && timer === undefined) timer = setTimeout(flush, 300);
  };
  const flush = async () => {
    timer = undefined;
    if (stopped) return;
    requested = false;
    inFlight = true;
    try {
      // ACKs are not observations. Only the normal monotonic snapshot stream updates UI.
      await transport.request('observe', {});
    } catch {
      // Passive failures are reported by native fixed diagnostics, never raw IPC toasts.
    } finally {
      inFlight = false;
      schedule();
    }
  };
  const request = () => { if (!stopped) { requested = true; schedule(); } };
  const foreground = () => { if (events.document.visibilityState !== 'hidden') request(); };
  events.window.addEventListener('focus', foreground);
  events.window.addEventListener('online', request);
  events.window.addEventListener('offline', request);
  events.document.addEventListener('visibilitychange', foreground);
  return () => {
    stopped = true;
    requested = false;
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    events.window.removeEventListener('focus', foreground);
    events.window.removeEventListener('online', request);
    events.window.removeEventListener('offline', request);
    events.document.removeEventListener('visibilitychange', foreground);
  };
}

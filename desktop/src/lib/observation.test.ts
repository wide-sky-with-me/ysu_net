import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { beginStateObservation } from './observation';
import { createDemoTransport } from './demo';
import type { Transport } from './protocol';

function fixture(mode: Transport['mode'] = 'desktop') {
  const window = new EventTarget();
  const document = Object.assign(new EventTarget(), { visibilityState: 'visible' as DocumentVisibilityState });
  const request = vi.fn().mockResolvedValue({ accepted: true });
  const transport = { mode, request } as unknown as Transport;
  return { window, document, request, transport };
}
const settled = () => vi.advanceTimersByTimeAsync(300);

describe('passive observation event bridge', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('mounting alone does not duplicate the native startup query', async () => {
    const f = fixture(); const stop = beginStateObservation(f.transport, f);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(f.request).not.toHaveBeenCalled(); stop();
  });

  it('coalesces focus, visibility, and network bursts into only an empty observe request', async () => {
    const f = fixture(); const stop = beginStateObservation(f.transport, f);
    for (let i = 0; i < 20; i++) {
      f.window.dispatchEvent(new Event('focus'));
      f.window.dispatchEvent(new Event('online'));
      f.window.dispatchEvent(new Event('offline'));
      f.document.dispatchEvent(new Event('visibilitychange'));
    }
    expect(f.request).not.toHaveBeenCalled(); await settled();
    expect(f.request.mock.calls).toEqual([['observe', {}]]); stop();
  });

  it('hidden visibility/focus does not trigger a query; restoring visibility does', async () => {
    const f = fixture(); const stop = beginStateObservation(f.transport, f);
    f.document.visibilityState = 'hidden';
    f.document.dispatchEvent(new Event('visibilitychange')); f.window.dispatchEvent(new Event('focus'));
    await settled(); expect(f.request).not.toHaveBeenCalled();
    f.document.visibilityState = 'visible'; f.document.dispatchEvent(new Event('visibilitychange'));
    await settled(); expect(f.request).toHaveBeenCalledExactlyOnceWith('observe', {}); stop();
  });

  it('network events remain advisory and may wake the native tray observer while hidden', async () => {
    const f = fixture(); const stop = beginStateObservation(f.transport, f);
    f.document.visibilityState = 'hidden'; f.window.dispatchEvent(new Event('offline'));
    await settled(); expect(f.request.mock.calls).toEqual([['observe', {}]]); stop();
  });

  it('allows one coalesced follow-up while an ACK is held, never overlapping IPC', async () => {
    const f = fixture(); let resolve!: (value: unknown) => void;
    f.request.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const stop = beginStateObservation(f.transport, f);
    f.window.dispatchEvent(new Event('focus')); await settled();
    for (let i = 0; i < 20; i++) f.window.dispatchEvent(new Event('online'));
    await settled(); expect(f.request).toHaveBeenCalledTimes(1);
    resolve({ status: { online: false }, config: { username: 'untrusted-ack' } });
    await settled(); expect(f.request.mock.calls).toEqual([['observe', {}], ['observe', {}]]); stop();
  });

  it('contains raw passive IPC failures and still admits later foreground requests', async () => {
    const f = fixture(); f.request.mockRejectedValueOnce(new Error('https://fixture.invalid/?token=private /private/client.exe'));
    const stop = beginStateObservation(f.transport, f);
    f.window.dispatchEvent(new Event('focus')); await settled();
    f.window.dispatchEvent(new Event('focus')); await settled();
    expect(f.request.mock.calls).toEqual([['observe', {}], ['observe', {}]]); stop();
  });

  it('cleanup cancels pending timers and detaches every event source', async () => {
    const f = fixture(); const stop = beginStateObservation(f.transport, f);
    f.window.dispatchEvent(new Event('focus')); stop();
    for (const event of ['focus', 'online', 'offline']) f.window.dispatchEvent(new Event(event));
    f.document.dispatchEvent(new Event('visibilitychange')); await settled();
    expect(f.request).not.toHaveBeenCalled();
  });

  it('cleanup during an in-flight ACK suppresses queued follow-up', async () => {
    const f = fixture(); let resolve!: (value: unknown) => void;
    f.request.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const stop = beginStateObservation(f.transport, f);
    f.window.dispatchEvent(new Event('focus')); await settled();
    f.window.dispatchEvent(new Event('online')); stop(); resolve({});
    await settled(); expect(f.request).toHaveBeenCalledTimes(1);
  });

  for (const mode of ['demo', 'web'] as const) it(`${mode} never installs an IPC observation path`, async () => {
    const f = fixture(mode); const stop = beginStateObservation(f.transport, f);
    f.window.dispatchEvent(new Event('focus')); f.window.dispatchEvent(new Event('online'));
    f.document.dispatchEvent(new Event('visibilitychange')); await settled();
    expect(f.request).not.toHaveBeenCalled(); stop();
  });

  it('explicit demo observation is a pure memory snapshot with no state or log mutation', async () => {
    const demo = createDemoTransport(); const before = await demo.request('snapshot', {});
    expect(await demo.request('observe', {})).toEqual(before);
    expect(await demo.request('snapshot', {})).toEqual(before);
  });
});

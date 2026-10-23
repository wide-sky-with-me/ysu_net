import { afterEach, describe, expect, it, vi } from 'vitest';
import { ambientMotion, metricMotion, pageMotion, stateMotion } from './motion';

afterEach(() => { vi.unstubAllGlobals(); });

function fixture(reduced = false) {
  const preference = { matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const frames = new Map<number, FrameRequestCallback>();
  let sequence = 0;
  vi.stubGlobal('window', { matchMedia: vi.fn(() => preference) });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { const id = ++sequence; frames.set(id, callback); return id; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { frames.delete(id); });
  const cancellations = [vi.fn(), vi.fn()];
  const surfaces = cancellations.map((cancel) => ({ animate: vi.fn(() => ({ cancel })) }));
  const node = { isConnected: true, querySelectorAll: vi.fn(() => surfaces) };
  const action = pageMotion(node as unknown as HTMLElement, 'connection')!;
  const flush = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach((callback) => callback(0)); };
  return { preference, frames, surfaces, cancellations, node, action, flush };
}

describe('page motion lifecycle', () => {
  it('reveals existing surfaces after layout using only paint properties', () => {
    const value = fixture();
    expect(value.node.querySelectorAll).not.toHaveBeenCalled();
    value.flush();
    for (const [index, surface] of value.surfaces.entries()) {
      expect(surface.animate).toHaveBeenCalledWith(
        [{ opacity: 0.35, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }],
        { duration: 240, delay: index * 24, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
      );
    }
    value.action.destroy?.();
  });

  it('does not replay on an unchanged page but cancels prior motion on navigation', () => {
    const value = fixture();
    value.flush();
    value.action.update?.('connection');
    expect(value.frames.size).toBe(0);
    value.action.update?.('settings:account');
    expect(value.cancellations.every((cancel) => cancel.mock.calls.length === 1)).toBe(true);
    expect(value.frames.size).toBe(1);
    value.action.destroy?.();
  });

  it('never schedules entrance motion when the system requests reduced motion', () => {
    const value = fixture(true);
    value.action.update?.('account');
    value.flush();
    expect(value.frames.size).toBe(0);
    expect(value.surfaces[0].animate).not.toHaveBeenCalled();
    value.action.destroy?.();
  });

  it('cancels running and queued motion immediately when reduced motion changes', () => {
    const value = fixture();
    value.flush();
    value.action.update?.('account');
    value.preference.matches = true;
    const listener = value.preference.addEventListener.mock.calls[0][1] as () => void;
    listener();
    expect(value.frames.size).toBe(0);
    expect(value.cancellations.every((cancel) => cancel.mock.calls.length === 1)).toBe(true);
    value.action.destroy?.();
  });

  it('cleans up frames and listeners on destruction without touching DOM content', () => {
    const value = fixture();
    value.action.destroy?.();
    value.flush();
    expect(value.frames.size).toBe(0);
    expect(value.node.querySelectorAll).not.toHaveBeenCalled();
    expect(value.preference.removeEventListener).toHaveBeenCalledWith('change', value.preference.addEventListener.mock.calls[0][1]);
  });

  it('does not animate a detached surface', () => {
    const value = fixture();
    value.node.isConnected = false;
    value.flush();
    expect(value.surfaces[0].animate).not.toHaveBeenCalled();
    value.action.destroy?.();
  });
});

function changeFixture(kind = stateMotion, initial = 'online', reduced = false, index = '0') {
  const preference = { matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const frames = new Map<number, FrameRequestCallback>();
  const cancellations: ReturnType<typeof vi.fn>[] = [];
  let sequence = 0;
  vi.stubGlobal('window', { matchMedia: vi.fn(() => preference) });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { const id = ++sequence; frames.set(id, callback); return id; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { frames.delete(id); });
  const node = { isConnected: true, textContent: '80.00 GB', dataset: { motionIndex: index }, animate: vi.fn(() => {
    const cancel = vi.fn(); cancellations.push(cancel); return { cancel };
  }) };
  const action = kind(node as unknown as HTMLElement, initial)!;
  const flush = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach((callback) => callback(0)); };
  return { preference, frames, node, action, cancellations, flush };
}

describe('real status and metric value motion', () => {
  it('uses one finite paint-only transition without changing any actual text', () => {
    const value = changeFixture();
    value.flush();
    expect(value.node.animate).toHaveBeenCalledOnce();
    const [frames, options] = value.node.animate.mock.calls[0] as unknown as [Keyframe[], KeyframeAnimationOptions];
    expect(options).toEqual({ duration: 450, delay: 0, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
    expect(frames.every((frame) => Object.keys(frame).every((key) => ['opacity', 'transform', 'boxShadow', 'offset'].includes(key)))).toBe(true);
    expect(value.node.textContent).toBe('80.00 GB');
    value.action.destroy?.();
  });

  it('moves the complete real metric without counting through fabricated values', () => {
    const value = changeFixture(metricMotion, '80.00 GB');
    value.flush();
    expect(value.node.animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ duration: 450, delay: 0 }));
    value.node.textContent = '79.50 GB';
    value.action.update?.('79.50 GB');
    value.flush();
    expect(value.node.textContent).toBe('79.50 GB');
    expect(value.cancellations[0]).toHaveBeenCalledOnce();
    value.action.destroy?.();
  });

  it('does not replay the same snapshot and replaces queued or running stale effects', () => {
    const value = changeFixture();
    value.action.update?.('offline');
    expect(value.frames.size).toBe(1);
    value.flush();
    value.action.update?.('offline');
    expect(value.frames.size).toBe(0);
    expect(value.node.animate).toHaveBeenCalledOnce();
    value.action.update?.('online');
    expect(value.cancellations[0]).toHaveBeenCalledOnce();
    value.action.destroy?.();
  });

  it('keeps pending/unavailable states still and cancels when a value becomes unavailable', () => {
    const value = changeFixture(stateMotion, '');
    value.flush();
    expect(value.node.animate).not.toHaveBeenCalled();
    value.action.update?.('online');
    value.flush();
    value.action.update?.('');
    expect(value.cancellations[0]).toHaveBeenCalledOnce();
    expect(value.frames.size).toBe(0);
    value.action.destroy?.();
  });

  it.each([stateMotion, metricMotion])('respects initial and live reduced motion without hiding final content', (kind) => {
    const value = changeFixture(kind, '8', true);
    value.flush();
    expect(value.node.animate).not.toHaveBeenCalled();
    value.preference.matches = false;
    const listener = value.preference.addEventListener.mock.calls[0][1] as () => void;
    listener();
    expect(value.frames.size).toBe(0);
    value.action.update?.('9');
    value.flush();
    value.action.update?.('7');
    value.preference.matches = true;
    listener();
    expect(value.frames.size).toBe(0);
    expect(value.cancellations[0]).toHaveBeenCalledOnce();
    expect(value.node.textContent).toBe('80.00 GB');
    value.action.destroy?.();
  });

  it('cleans up listeners and queued work and ignores detached nodes', () => {
    const value = changeFixture();
    value.node.isConnected = false;
    value.flush();
    expect(value.node.animate).not.toHaveBeenCalled();
    value.action.update?.('offline');
    value.action.destroy?.();
    value.flush();
    expect(value.node.animate).not.toHaveBeenCalled();
    expect(value.preference.removeEventListener).toHaveBeenCalledWith('change', value.preference.addEventListener.mock.calls[0][1]);
  });
});

function ambientFixture(reduced = false, supported = true) {
  const preference = { matches: reduced, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const visibility = { visibilityState: 'visible', addEventListener: vi.fn(), removeEventListener: vi.fn() };
  const observe = vi.fn();
  const disconnect = vi.fn();
  let emit = (_visible: boolean) => {};
  class Observer {
    observe = observe;
    disconnect = disconnect;
    constructor(callback: IntersectionObserverCallback) {
      emit = (isIntersecting) => callback([{ isIntersecting } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
  }
  vi.stubGlobal('window', { matchMedia: vi.fn(() => preference) });
  vi.stubGlobal('document', visibility);
  vi.stubGlobal('IntersectionObserver', supported ? Observer : undefined);
  const node = { isConnected: true, dataset: { state: 'available' } as Record<string, string> };
  const action = ambientMotion(node as unknown as HTMLElement)!;
  return { preference, visibility, node, action, observe, disconnect, emit };
}

describe('decorative quota ambient lifecycle', () => {
  it('runs only while the known quota decoration is actually in view', () => {
    const value = ambientFixture();
    expect(value.node.dataset.motion).toBe('paused');
    expect(value.observe).toHaveBeenCalledWith(value.node);
    value.emit(true);
    expect(value.node.dataset.motion).toBe('running');
    expect(value.node.dataset.state).toBe('available');
    value.emit(false);
    expect(value.node.dataset.motion).toBe('paused');
    value.action.destroy?.();
  });

  it('pauses for reduced motion and resumes only when it is explicitly allowed', () => {
    const value = ambientFixture(true);
    value.emit(true);
    expect(value.node.dataset.motion).toBe('paused');
    const change = value.preference.addEventListener.mock.calls[0][1] as () => void;
    value.preference.matches = false;
    change();
    expect(value.node.dataset.motion).toBe('running');
    value.preference.matches = true;
    change();
    expect(value.node.dataset.motion).toBe('paused');
    value.action.destroy?.();
  });

  it('pauses for hidden documents and detached nodes without modifying the quota', () => {
    const value = ambientFixture();
    value.emit(true);
    const change = value.visibility.addEventListener.mock.calls[0][1] as () => void;
    value.visibility.visibilityState = 'hidden';
    change();
    expect(value.node.dataset.motion).toBe('paused');
    value.visibility.visibilityState = 'visible';
    change();
    expect(value.node.dataset.motion).toBe('running');
    value.node.isConnected = false;
    change();
    expect(value.node.dataset.motion).toBe('paused');
    value.action.destroy?.();
  });

  it('disconnects observers and listeners and ignores late callbacks on destruction', () => {
    const value = ambientFixture();
    value.emit(true);
    value.action.destroy?.();
    value.emit(true);
    expect(value.node.dataset.motion).toBeUndefined();
    expect(value.disconnect).toHaveBeenCalledOnce();
    expect(value.visibility.removeEventListener).toHaveBeenCalledWith('visibilitychange', value.visibility.addEventListener.mock.calls[0][1]);
    expect(value.preference.removeEventListener).toHaveBeenCalledWith('change', value.preference.addEventListener.mock.calls[0][1]);
  });

  it('keeps a static decoration when intersection observation is unavailable', () => {
    const value = ambientFixture(false, false);
    expect(value.node.dataset.motion).toBe('paused');
    value.action.destroy?.();
  });
});

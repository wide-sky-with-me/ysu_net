import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFeedbackController } from './feedback';
import type { FeedbackInput, FeedbackNotice, FeedbackView } from './feedback';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.clearAllTimers(); vi.restoreAllMocks(); vi.useRealTimers(); });

function fixture(options?: { busyDelayMs?: number; noticeDurationMs?: number }) {
  const publish = vi.fn<(view: FeedbackView) => void>();
  const dismiss = vi.fn<() => void>();
  const controller = createFeedbackController(publish, dismiss, options);
  const update = (input: Partial<FeedbackInput> = {}) => controller.update({ busy: false, busyMessage: '正在执行…', notice: null, ...input });
  const view = () => publish.mock.lastCall?.[0];
  return { controller, publish, dismiss, update, view };
}

const success = (): FeedbackNotice => ({ message: '已保存。', error: false });

describe('busy presentation timing', () => {
  it('cancels short work without ever flashing a busy message', () => {
    const value = fixture();
    value.update({ busy: true });
    expect(value.view()).toEqual({ busyMessage: null, notice: null });
    vi.advanceTimersByTime(249);
    value.update();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(1000);
    expect(value.publish.mock.calls).toEqual([[{ busyMessage: null, notice: null }]]);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('shows long work at 250ms and hides it immediately when work finishes', () => {
    const value = fixture();
    value.update({ busy: true });
    vi.advanceTimersByTime(249);
    expect(value.view()?.busyMessage).toBeNull();
    vi.advanceTimersByTime(1);
    expect(value.view()).toEqual({ busyMessage: '正在执行…', notice: null });
    vi.advanceTimersByTime(5000);
    expect(value.view()?.busyMessage).toBe('正在执行…');
    value.update();
    expect(value.view()).toEqual({ busyMessage: null, notice: null });
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('uses the latest message without restarting the initial busy delay', () => {
    const value = fixture();
    value.update({ busy: true, busyMessage: '读取…' });
    vi.advanceTimersByTime(200);
    value.update({ busy: true, busyMessage: '保存…' });
    vi.advanceTimersByTime(49);
    expect(value.view()?.busyMessage).toBeNull();
    vi.advanceTimersByTime(1);
    expect(value.view()?.busyMessage).toBe('保存…');
    value.update({ busy: true, busyMessage: '完成校验…' });
    expect(value.view()?.busyMessage).toBe('完成校验…');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('starts a fresh delay for a separate busy interval and ignores its old timer', () => {
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const value = fixture();
    value.update({ busy: true });
    const oldTimer = timers.mock.calls[0][0] as () => void;
    vi.advanceTimersByTime(200);
    value.update();
    value.update({ busy: true, busyMessage: '新任务' });
    oldTimer();
    vi.advanceTimersByTime(249);
    expect(value.view()?.busyMessage).toBeNull();
    vi.advanceTimersByTime(1);
    expect(value.view()?.busyMessage).toBe('新任务');
  });

  it('never changes input business state or invents a success notice on completion', () => {
    const value = fixture();
    const input = Object.freeze({ busy: true, busyMessage: '原生任务', notice: null });
    value.controller.update(input);
    vi.advanceTimersByTime(250);
    expect(input.busy).toBe(true);
    value.controller.update(Object.freeze({ ...input, busy: false }));
    vi.advanceTimersByTime(10_000);
    expect(input).toEqual({ busy: true, busyMessage: '原生任务', notice: null });
    expect(value.publish.mock.calls.every(([view]) => view.notice === null)).toBe(true);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('keeps busy and notice timers independent', () => {
    const value = fixture();
    const notice = success();
    value.update({ busy: true, notice });
    expect(value.view()).toEqual({ busyMessage: null, notice });
    vi.advanceTimersByTime(250);
    expect(value.view()).toEqual({ busyMessage: '正在执行…', notice });
    vi.advanceTimersByTime(4250);
    expect(value.view()).toEqual({ busyMessage: '正在执行…', notice: null });
    expect(value.dismiss).toHaveBeenCalledOnce();
    value.update({ busy: true, notice });
    expect(value.view()?.notice).toBeNull();
  });

  it('allows explicit busy and notice duration overrides', () => {
    const value = fixture({ busyDelayMs: 30, noticeDurationMs: 80 });
    value.update({ busy: true, notice: success() });
    vi.advanceTimersByTime(29);
    expect(value.view()?.busyMessage).toBeNull();
    vi.advanceTimersByTime(1);
    expect(value.view()?.busyMessage).toBe('正在执行…');
    vi.advanceTimersByTime(49);
    expect(value.view()?.notice).not.toBeNull();
    vi.advanceTimersByTime(1);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('honors zero duration overrides instead of substituting defaults', () => {
    const value = fixture({ busyDelayMs: 0, noticeDurationMs: 0 });
    value.update({ busy: true, notice: success() });
    vi.advanceTimersByTime(0);
    expect(value.view()).toEqual({ busyMessage: '正在执行…', notice: null });
    expect(value.dismiss).toHaveBeenCalledOnce();
  });
});

describe('notice identity and expiration', () => {
  it('keeps original text and identity, then hides success at exactly 4500ms before dismissal', () => {
    const value = fixture();
    const notice = Object.freeze({ message: '  <script>文本 & 原文</script>\n', error: false });
    value.dismiss.mockImplementation(() => {
      expect(value.view()?.notice).toBeNull();
      value.update();
    });
    value.update({ notice });
    expect(value.view()?.notice).toBe(notice);
    expect(value.view()?.notice?.message).toBe(notice.message);
    vi.advanceTimersByTime(4499);
    expect(value.view()?.notice).toBe(notice);
    expect(value.dismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(value.view()).toEqual({ busyMessage: null, notice: null });
    expect(value.dismiss).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not renew success on repeated updates or changed busy props', () => {
    const value = fixture();
    const notice = success();
    value.update({ notice });
    for (let index = 0; index < 4; index += 1) {
      vi.advanceTimersByTime(1000);
      value.update({ busy: index % 2 === 0, busyMessage: `步骤 ${index}`, notice });
      value.update({ busy: index % 2 === 0, busyMessage: `步骤 ${index}`, notice });
    }
    vi.advanceTimersByTime(499);
    expect(value.view()?.notice).toBe(notice);
    vi.advanceTimersByTime(1);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('treats a distinct object with identical content as a new full-duration notice', () => {
    const value = fixture();
    const first = success();
    const second = success();
    value.update({ notice: first });
    vi.advanceTimersByTime(4000);
    value.update({ notice: second });
    expect(value.view()?.notice).toBe(second);
    vi.advanceTimersByTime(500);
    expect(value.view()?.notice).toBe(second);
    expect(value.dismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3999);
    expect(value.view()?.notice).toBe(second);
    vi.advanceTimersByTime(1);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('rejects an old timer even when an earlier notice object is reused', () => {
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const value = fixture();
    const first = success();
    value.update({ notice: first });
    const oldTimer = timers.mock.calls[0][0] as () => void;
    vi.advanceTimersByTime(1000);
    value.update({ notice: success() });
    value.update({ notice: first });
    oldTimer();
    expect(value.view()?.notice).toBe(first);
    expect(value.dismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(4499);
    expect(value.view()?.notice).toBe(first);
    vi.advanceTimersByTime(1);
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('keeps errors indefinitely and cancels a success timer when replaced by an error', () => {
    const value = fixture();
    value.update({ notice: success() });
    vi.advanceTimersByTime(4000);
    const error = { message: '保存失败', error: true };
    value.update({ notice: error });
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(60_000);
    value.update({ busy: true, notice: error });
    vi.advanceTimersByTime(250);
    expect(value.view()?.notice).toBe(error);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('starts normal success expiration after a persistent error is replaced', () => {
    const value = fixture();
    value.update({ notice: { message: '失败', error: true } });
    vi.advanceTimersByTime(20_000);
    const notice = success();
    value.update({ notice });
    vi.advanceTimersByTime(4499);
    expect(value.view()?.notice).toBe(notice);
    vi.advanceTimersByTime(1);
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('clears manually removed notices without calling the automatic dismissal callback', () => {
    const value = fixture();
    value.update({ notice: success() });
    vi.advanceTimersByTime(1000);
    value.update();
    expect(value.view()?.notice).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10_000);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('does not resurrect an expired notice while the caller still supplies its old identity', () => {
    const value = fixture();
    const notice = success();
    value.update({ notice });
    vi.advanceTimersByTime(4500);
    value.update({ busy: true, notice });
    value.update({ busy: true, busyMessage: '刷新中', notice });
    vi.advanceTimersByTime(10_000);
    expect(value.view()).toEqual({ busyMessage: '刷新中', notice: null });
    expect(value.dismiss).toHaveBeenCalledOnce();
    value.update();
    value.update({ notice });
    expect(value.view()?.notice).toBe(notice);
    vi.advanceTimersByTime(4500);
    expect(value.dismiss).toHaveBeenCalledTimes(2);
  });

  it('does not dismiss a new notice synchronously published while hiding the old one', () => {
    const value = fixture();
    const first = success();
    const second = success();
    value.update({ notice: first });
    value.publish.mockImplementation((view) => {
      if (view.notice === null) value.update({ notice: second });
    });
    vi.advanceTimersByTime(4500);
    expect(value.view()?.notice).toBe(second);
    expect(value.dismiss).not.toHaveBeenCalled();
    value.publish.mockImplementation(() => {});
    vi.advanceTimersByTime(4500);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('preserves a new notice supplied synchronously by the dismissal callback', () => {
    const value = fixture();
    const second = success();
    value.dismiss.mockImplementationOnce(() => value.update({ notice: second }));
    value.update({ notice: success() });
    vi.advanceTimersByTime(4500);
    expect(value.view()?.notice).toBe(second);
    expect(value.dismiss).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(4499);
    expect(value.view()?.notice).toBe(second);
    vi.advanceTimersByTime(1);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledTimes(2);
  });
});

describe('notice pause and resume', () => {
  it('pauses only remaining time and keeps repeated pause/resume calls idempotent', () => {
    const value = fixture();
    const notice = success();
    value.update({ notice });
    vi.advanceTimersByTime(1500);
    value.controller.pauseNotice();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10_000);
    value.controller.pauseNotice();
    value.update({ notice });
    expect(value.view()?.notice).toBe(notice);
    value.controller.resumeNotice();
    vi.advanceTimersByTime(1000);
    value.controller.resumeNotice();
    vi.advanceTimersByTime(1999);
    expect(value.view()?.notice).toBe(notice);
    expect(value.dismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('retains the remaining duration across multiple pause cycles', () => {
    const value = fixture();
    const notice = success();
    value.update({ notice });
    for (let index = 0; index < 2; index += 1) {
      vi.advanceTimersByTime(1000);
      value.controller.pauseNotice();
      vi.advanceTimersByTime(10_000);
      value.controller.resumeNotice();
    }
    vi.advanceTimersByTime(2499);
    expect(value.view()?.notice).toBe(notice);
    vi.advanceTimersByTime(1);
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('keeps replacements paused but gives their own full duration on resume', () => {
    const value = fixture();
    value.update({ notice: success() });
    vi.advanceTimersByTime(4000);
    value.controller.pauseNotice();
    const replacement = success();
    value.update({ notice: replacement });
    vi.advanceTimersByTime(20_000);
    expect(value.view()?.notice).toBe(replacement);
    expect(value.dismiss).not.toHaveBeenCalled();
    value.controller.resumeNotice();
    vi.advanceTimersByTime(4499);
    expect(value.view()?.notice).toBe(replacement);
    vi.advanceTimersByTime(1);
    expect(value.dismiss).toHaveBeenCalledOnce();
  });

  it('can pause before a notice exists without pausing busy work or timing out errors', () => {
    const value = fixture();
    value.controller.pauseNotice();
    const notice = success();
    value.update({ busy: true, notice });
    vi.advanceTimersByTime(10_000);
    expect(value.view()).toEqual({ busyMessage: '正在执行…', notice });
    expect(value.dismiss).not.toHaveBeenCalled();
    const error = { message: '错误', error: true };
    value.update({ notice: error });
    value.controller.resumeNotice();
    value.controller.pauseNotice();
    value.controller.resumeNotice();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(60_000);
    expect(value.view()?.notice).toBe(error);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('ignores a timer queued before pause after the notice is resumed', () => {
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const value = fixture();
    const notice = success();
    value.update({ notice });
    const oldTimer = timers.mock.calls[0][0] as () => void;
    vi.advanceTimersByTime(1000);
    value.controller.pauseNotice();
    value.controller.resumeNotice();
    oldTimer();
    expect(value.view()?.notice).toBe(notice);
    expect(value.dismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3500);
    expect(value.dismiss).toHaveBeenCalledOnce();
  });
});

describe('feedback disposal', () => {
  it('clears both timers and ignores all methods and late callbacks after dispose', () => {
    const timers = vi.spyOn(globalThis, 'setTimeout');
    const value = fixture();
    value.update({ busy: true, notice: success() });
    const callbacks = timers.mock.calls.map(([callback]) => callback as () => void);
    expect(vi.getTimerCount()).toBe(2);
    const published = value.publish.mock.calls.length;
    value.controller.dispose();
    value.controller.dispose();
    expect(vi.getTimerCount()).toBe(0);
    value.update({ busy: true, notice: success() });
    value.controller.pauseNotice();
    value.controller.resumeNotice();
    callbacks.forEach((callback) => callback());
    vi.advanceTimersByTime(60_000);
    expect(vi.getTimerCount()).toBe(0);
    expect(value.publish).toHaveBeenCalledTimes(published);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('never restarts a paused notice after disposal', () => {
    const value = fixture();
    value.update({ notice: success() });
    value.controller.pauseNotice();
    const published = value.publish.mock.calls.length;
    value.controller.dispose();
    value.controller.resumeNotice();
    vi.advanceTimersByTime(60_000);
    expect(vi.getTimerCount()).toBe(0);
    expect(value.publish).toHaveBeenCalledTimes(published);
    expect(value.dismiss).not.toHaveBeenCalled();
  });

  it('does not dismiss when publishing the hidden notice synchronously disposes it', () => {
    const value = fixture();
    value.update({ notice: success() });
    value.publish.mockImplementation(() => value.controller.dispose());
    vi.advanceTimersByTime(4500);
    expect(value.view()?.notice).toBeNull();
    expect(value.dismiss).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});

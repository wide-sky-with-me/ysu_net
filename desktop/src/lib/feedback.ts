export type FeedbackNotice = { message: string; error: boolean };
export type FeedbackInput = { busy: boolean; busyMessage: string; notice: FeedbackNotice | null };
export type FeedbackView = { busyMessage: string | null; notice: FeedbackNotice | null };

/** Presentation timing only; the caller remains authoritative for business state. */
export function createFeedbackController(
  publish: (view: FeedbackView) => void,
  onDismissNotice: () => void,
  options: { busyDelayMs?: number; noticeDurationMs?: number } = {},
) {
  const busyDelayMs = options.busyDelayMs ?? 250;
  const noticeDurationMs = options.noticeDurationMs ?? 4500;
  let disposed = false;
  let busy = false;
  let busyMessage = '';
  let busyVisible = false;
  let busyTimer: ReturnType<typeof setTimeout> | undefined;
  let busyVersion = 0;
  let inputNotice: FeedbackNotice | null = null;
  let notice: FeedbackNotice | null = null;
  let noticeTimer: ReturnType<typeof setTimeout> | undefined;
  let noticeVersion = 0;
  let noticePaused = false;
  let noticeRemainingMs = noticeDurationMs;
  let noticeStartedAt = 0;
  let published: FeedbackView | undefined;

  function emit() {
    if (disposed) return;
    const view = { busyMessage: busyVisible ? busyMessage : null, notice };
    if (published && published.busyMessage === view.busyMessage && published.notice === view.notice) return;
    published = view;
    publish(view);
  }

  function clearBusyTimer() {
    busyVersion += 1;
    if (busyTimer !== undefined) clearTimeout(busyTimer);
    busyTimer = undefined;
  }

  function clearNoticeTimer() {
    noticeVersion += 1;
    if (noticeTimer !== undefined) clearTimeout(noticeTimer);
    noticeTimer = undefined;
  }

  function startNoticeTimer() {
    if (disposed || noticePaused || !notice || notice.error) return;
    const expiringNotice = notice;
    const version = ++noticeVersion;
    noticeStartedAt = Date.now();
    noticeTimer = setTimeout(() => {
      if (disposed || version !== noticeVersion || notice !== expiringNotice) return;
      noticeTimer = undefined;
      noticeRemainingMs = 0;
      notice = null;
      // Keep input identity until the caller clears it; unrelated updates cannot revive it.
      emit();
      // Publishing can synchronously replace the notice or dispose this controller.
      if (!disposed && version === noticeVersion && inputNotice === expiringNotice) onDismissNotice();
    }, noticeRemainingMs);
  }

  return {
    update(input: FeedbackInput) {
      if (disposed) return;
      const starting = input.busy && !busy;
      busy = input.busy;
      busyMessage = input.busyMessage;
      if (!busy) {
        clearBusyTimer();
        busyVisible = false;
      } else if (starting) {
        const version = ++busyVersion;
        busyTimer = setTimeout(() => {
          if (disposed || version !== busyVersion || !busy) return;
          busyTimer = undefined;
          busyVisible = true;
          emit();
        }, busyDelayMs);
      }
      if (input.notice !== inputNotice) {
        clearNoticeTimer();
        inputNotice = input.notice;
        notice = input.notice;
        noticeRemainingMs = noticeDurationMs;
        startNoticeTimer();
      }
      emit();
    },
    pauseNotice() {
      if (disposed || noticePaused) return;
      noticePaused = true;
      if (noticeTimer !== undefined) {
        noticeRemainingMs = Math.max(0, noticeRemainingMs - (Date.now() - noticeStartedAt));
        clearNoticeTimer();
      }
    },
    resumeNotice() {
      if (disposed || !noticePaused) return;
      noticePaused = false;
      startNoticeTimer();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      clearBusyTimer();
      clearNoticeTimer();
    },
  };
}

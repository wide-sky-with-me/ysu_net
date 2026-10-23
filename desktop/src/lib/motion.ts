import type { Action } from 'svelte/action';

/** Reveal existing content without delaying unmount, focus, or credential cleanup. */
export const pageMotion: Action<HTMLElement, string> = (node, initialPage) => {
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  let page = initialPage;
  let frame: number | undefined;
  let animations: Animation[] = [];

  function stop() {
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = undefined;
    animations.forEach((animation) => animation.cancel());
    animations = [];
  }

  function reveal() {
    stop();
    if (preference.matches) return;
    frame = requestAnimationFrame(() => {
      frame = undefined;
      if (preference.matches || !node.isConnected) return;
      const surfaces = node.querySelectorAll<HTMLElement>(':scope > .connection-overview, :scope > .account-summary, :scope > .account-fields, :scope > .settings-panel, :scope > .log-toolbar, :scope > .log-list, :scope > .empty-state');
      animations = [...surfaces].map((surface, index) => surface.animate(
        [{ opacity: 0.35, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }],
        { duration: 240, delay: Math.min(index, 2) * 24, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
      ));
    });
  }

  const change = () => { if (preference.matches) stop(); };
  preference.addEventListener('change', change);
  reveal();
  return {
    update(nextPage) { if (nextPage !== page) { page = nextPage; reveal(); } },
    destroy() { stop(); preference.removeEventListener('change', change); },
  };
};

/** Animate only the actual new value; repeated snapshots never restart the effect. */
function changedValueMotion(keyframes: Keyframe[]): Action<HTMLElement, string> {
  return (node, initialValue) => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let value = initialValue;
    let frame: number | undefined;
    let animation: Animation | undefined;

    function stop() {
      if (frame !== undefined) cancelAnimationFrame(frame);
      frame = undefined;
      animation?.cancel();
      animation = undefined;
    }

    function reveal() {
      stop();
      if (!value || preference.matches) return;
      frame = requestAnimationFrame(() => {
        frame = undefined;
        if (preference.matches || !node.isConnected) return;
        animation = node.animate(keyframes, {
          duration: 450, delay: 0,
          easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
        });
      });
    }

    const change = () => { if (preference.matches) stop(); };
    preference.addEventListener('change', change);
    reveal();
    return {
      update(nextValue) { if (nextValue !== value) { value = nextValue; reveal(); } },
      destroy() { stop(); preference.removeEventListener('change', change); },
    };
  };
}

export const stateMotion = changedValueMotion([
  { opacity: 0.55, transform: 'scale(0.88)', boxShadow: '0 0 0 0 var(--state-ring)' },
  { opacity: 1, transform: 'scale(1.04)', boxShadow: '0 0 0 5px var(--state-ring)', offset: 0.6 },
  { opacity: 1, transform: 'scale(1)', boxShadow: '0 0 0 11px transparent' },
]);

export const metricMotion = changedValueMotion([
  { opacity: 0.3, transform: 'translateY(7px)' },
  { opacity: 1, transform: 'translateY(-1px)', offset: 0.75 },
  { opacity: 1, transform: 'translateY(0)' },
]);

/** Pause decorative loops when hidden, offscreen, or reduced motion is requested. */
export const ambientMotion: Action<HTMLElement> = (node) => {
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  let inView = false;
  let alive = true;
  const update = () => {
    if (!alive) return;
    node.dataset.motion = node.isConnected && inView && document.visibilityState === 'visible' && !preference.matches ? 'running' : 'paused';
  };
  const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver((entries) => {
    inView = entries.some((entry) => entry.isIntersecting);
    update();
  }) : undefined;
  observer?.observe(node);
  document.addEventListener('visibilitychange', update);
  preference.addEventListener('change', update);
  update();
  return {
    destroy() {
      alive = false;
      observer?.disconnect();
      document.removeEventListener('visibilitychange', update);
      preference.removeEventListener('change', update);
      delete node.dataset.motion;
    },
  };
};

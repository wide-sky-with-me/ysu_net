<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import Icon from './Icon.svelte';
  import { createFeedbackController } from '../lib/feedback';
  import type { FeedbackNotice, FeedbackView } from '../lib/feedback';

  let { busy, busyMessage, notice, ondismiss }: {
    busy: boolean; busyMessage: string; notice: FeedbackNotice | null; ondismiss: () => void;
  } = $props();
  let view = $state<FeedbackView>({ busyMessage: null, notice: null });
  let reducedMotion = $state(false);
  let dock = $state<HTMLDivElement>();
  const controller = createFeedbackController((next) => { view = next; }, () => ondismiss());

  $effect(() => {
    controller.update({ busy, busyMessage, notice });
    if (!notice) controller.resumeNotice();
  });
  onMount(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    reducedMotion = media.matches;
    const change = () => {
      reducedMotion = media.matches;
      if (reducedMotion) for (const animation of dock?.getAnimations({ subtree: true }) || []) {
        try { animation.finish(); } catch { animation.cancel(); }
      }
    };
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  });
  onDestroy(() => controller.dispose());

  function resumeIfOutside(event: PointerEvent | FocusEvent) {
    const node = event.currentTarget as HTMLElement;
    queueMicrotask(() => {
      if (!node.isConnected || !node.matches(':hover, :focus-within')) controller.resumeNotice();
    });
  }
</script>

<div class="feedback-dock" bind:this={dock} aria-label="操作反馈">
  {#if view.notice}
    {@const currentNotice = view.notice}
    {#key currentNotice}
      <div class="feedback-toast feedback-notice" class:error={currentNotice.error} role={currentNotice.error ? 'alert' : 'status'}
        transition:fade={{ duration: reducedMotion ? 0 : 120 }}
        onpointerenter={() => controller.pauseNotice()} onpointerleave={resumeIfOutside}
        onfocusin={() => controller.pauseNotice()} onfocusout={resumeIfOutside}>
        <span class="feedback-symbol" aria-hidden="true"><Icon name={currentNotice.error ? 'alert' : 'check'} size={17} /></span>
        <span class="feedback-message">{currentNotice.message}</span>
        <button type="button" class="quiet-button feedback-close" aria-label="关闭提示" onclick={ondismiss}><Icon name="close" size={16} /></button>
      </div>
    {/key}
  {/if}
  {#if view.busyMessage}
    <div class="feedback-toast feedback-busy" role="status" transition:fade={{ duration: reducedMotion ? 0 : 120 }}>
      <span class="feedback-symbol" aria-hidden="true"><Icon name="refresh" size={17} /></span>
      <span class="feedback-message">{view.busyMessage}</span>
    </div>
  {/if}
</div>

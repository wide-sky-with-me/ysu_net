<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  let { title, message, confirm, danger = false, icon = danger ? 'warning' : 'info', onconfirm, oncancel }: { title: string; message: string; confirm: string; danger?: boolean; icon?: string; onconfirm: () => void; oncancel: () => void } = $props();
  let dialog: HTMLDialogElement;
  onMount(() => {
    const previousFocus = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  });
  function trapFocus(event: KeyboardEvent) {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  }
</script>

<dialog bind:this={dialog} class="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-message" onkeydown={trapFocus} oncancel={(event) => { event.preventDefault(); oncancel(); }}>
  <div class:danger class="dialog-symbol"><Icon name={icon} size={24} /></div>
  <h2 id="confirm-title">{title}</h2>
  <p id="confirm-message">{message}</p>
  <div class="dialog-actions">
    <button type="button" onclick={oncancel}>取消</button>
    <button type="button" class={danger ? 'danger-button' : 'primary-button'} onclick={onconfirm}>{confirm}</button>
  </div>
</dialog>

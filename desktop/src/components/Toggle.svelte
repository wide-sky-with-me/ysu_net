<script lang="ts">
  let { checked, disabled = false, busy = false, label, onchange }: { checked: boolean; disabled?: boolean; busy?: boolean; label: string; onchange: (value: boolean) => void } = $props();
</script>

<button type="button" class="toggle" role="switch" aria-checked={checked} aria-busy={busy} aria-label={label} disabled={disabled || busy} onclick={() => onchange(!checked)}>
  <span class="toggle-knob"></span>
</button>

<script lang="ts">
  let { checked, disabled = false, label, onchange }: { checked: boolean; disabled?: boolean; label: string; onchange: (value: boolean) => void } = $props();
</script>

<button type="button" class="toggle" role="switch" aria-checked={checked} aria-label={label} {disabled} onclick={() => onchange(!checked)}>
  <span class="toggle-knob"></span>
</button>

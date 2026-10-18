<script lang="ts">
  import Icon from './Icon.svelte';
  import { ACCENT_OPTIONS, type Accent } from '../lib/accents';

  let { value, disabled = false, onchange }: { value: Accent; disabled?: boolean; onchange: (value: Accent) => void } = $props();
</script>

<div class="accent-selector" role="group" aria-label="主题色">
  {#each ACCENT_OPTIONS as option}
    <button type="button" class="accent-option" aria-pressed={value === option.value} {disabled} onclick={() => onchange(option.value)}>
      <span class="accent-swatch" aria-hidden="true" style={`--swatch-light: ${option.light}; --swatch-dark: ${option.dark}`}>
        {#if value === option.value}<Icon name="check" size={14} />{/if}
      </span>
      <span>{option.label}</span>
    </button>
  {/each}
</div>

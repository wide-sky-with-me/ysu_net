<script lang="ts">
  type Section = 'account' | 'desktop' | 'authentication' | 'diagnostics';
  let { selected, onchange }: { selected: Section; onchange: (section: Section) => void } = $props();
  const sections: { id: Section; label: string }[] = [
    { id: 'account', label: '校园网账号' },
    { id: 'desktop', label: '外观与启动' },
    { id: 'authentication', label: '认证与重试' },
    { id: 'diagnostics', label: '环境诊断' },
  ];

  function keyboard(event: KeyboardEvent, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % sections.length;
    else if (event.key === 'ArrowLeft') next = (index + sections.length - 1) % sections.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = sections.length - 1;
    else return;
    event.preventDefault();
    onchange(sections[next].id);
    document.getElementById(`settings-tab-${sections[next].id}`)?.focus();
  }
</script>

<div class="settings-tabs" role="tablist" aria-label="设置分区">
  {#each sections as section, index}
    <button type="button" role="tab" id={`settings-tab-${section.id}`} aria-controls="settings-panel"
      aria-selected={selected === section.id} tabindex={selected === section.id ? 0 : -1}
      onclick={() => onchange(section.id)} onkeydown={(event) => keyboard(event, index)}>{section.label}</button>
  {/each}
</div>

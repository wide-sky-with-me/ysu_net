<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { createUpdaterClient, initialUpdateSnapshot, newerUpdateSnapshot, updateDownloadLabel, updateErrorCode, updateErrorMessage, updatePercent, updateWorking } from '../lib/updater';
  import type { StartupUpdatePrompt, UpdateError, UpdatePhase, UpdateSnapshot } from '../lib/updater';

  let { prompt, mode, demo = false, busy = false, currentVersion = '', ondismiss, onignore }: {
    prompt: StartupUpdatePrompt;
    mode: 'desktop' | 'demo' | 'web';
    demo?: boolean;
    busy?: boolean;
    currentVersion?: string;
    ondismiss: (version: string) => void;
    onignore: (version: string) => void;
  } = $props();

  let dialog: HTMLDialogElement;
  let snapshot = $state<UpdateSnapshot>(initialUpdateSnapshot('web'));
  let pending = $state<'install' | 'restart' | null>(null);
  let error = $state<UpdateError | null>(null);

  const client = $derived(createUpdaterClient(mode, demo, currentVersion));
  const versionTag = $derived(prompt.version.startsWith('v') ? prompt.version : `v${prompt.version}`);
  const currentTag = $derived(currentVersion ? (currentVersion.startsWith('v') ? currentVersion : `v${currentVersion}`) : '');
  const restartRequired = $derived(prompt.kind === 'restart_required' || snapshot.phase === 'restart_required');
  const working = $derived(pending === 'install' || updateWorking(snapshot.phase));
  const recoveryRequired = $derived(snapshot.phase === 'recovery_required');
  const visibleError = $derived(error || snapshot.error);
  const progressVisible = $derived(['downloading', 'verifying', 'reconstructing', 'quiescing', 'installing'].includes(snapshot.phase));
  const percentage = $derived(snapshot.phase === 'downloading' ? updatePercent(snapshot) : undefined);

  const phaseLabels: Partial<Record<UpdatePhase, string>> = {
    checking: '正在检查更新…',
    downloading: '正在下载更新…',
    verifying: '正在校验签名…',
    reconstructing: '正在还原完整更新包…',
    quiescing: '正在停止后台任务…',
    installing: '正在安装更新…',
    recovery_required: '安装未完成，请前往关于页面恢复后台服务。',
  };

  const title = $derived(restartRequired ? `更新已就绪 ${versionTag}` : `发现新版本 ${versionTag}`);
  const summary = $derived.by(() => {
    if (restartRequired) return `新版本 ${versionTag} 已完成安装，重启应用后生效。`;
    if (working) return updateDownloadLabel(snapshot) || phaseLabels[snapshot.phase] || '正在更新…';
    if (recoveryRequired) return phaseLabels.recovery_required || '安装未完成，请恢复后台服务。';
    return currentTag ? `当前版本 ${currentTag}，可立即下载并安装。` : '可立即下载并安装更新。';
  });

  function accept(next: UpdateSnapshot) { snapshot = newerUpdateSnapshot(snapshot, next); }

  onMount(() => {
    const previousFocus = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  });

  $effect(() => {
    const activeClient = client;
    let active = true;
    let stop: (() => void) | undefined;
    snapshot = initialUpdateSnapshot(mode, demo, currentVersion);
    error = null;
    void (async () => {
      try {
        const unsubscribe = await activeClient.subscribe(
          (value) => { if (active) accept(value); },
          (code) => { if (active) error = code; },
        );
        if (!active) { unsubscribe(); return; }
        stop = unsubscribe;
        const value = await activeClient.status();
        if (active) accept(value);
      } catch (value) {
        if (active) error = updateErrorCode(value);
      }
    })();
    return () => { active = false; stop?.(); };
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

  async function install() {
    if (pending || working || busy) return;
    pending = 'install';
    error = null;
    try {
      const value = await client.install(prompt.version);
      accept(value);
    } catch (value) {
      error = updateErrorCode(value);
      try { accept(await client.status()); } catch { /* Keep surfaced error code. */ }
    } finally {
      pending = null;
    }
  }

  async function restart() {
    if (pending) return;
    pending = 'restart';
    error = null;
    try {
      await client.restart();
    } catch (value) {
      error = updateErrorCode(value);
    } finally {
      pending = null;
    }
  }

  function closePrompt() {
    if (pending === 'restart') return;
    ondismiss(prompt.version);
  }
</script>

<dialog bind:this={dialog} class="confirm-dialog update-dialog" aria-labelledby="update-prompt-title" aria-describedby="update-prompt-message" onkeydown={trapFocus} oncancel={(event) => { event.preventDefault(); closePrompt(); }}>
  <div class="dialog-symbol"><Icon name="download" size={24} /></div>
  <h2 id="update-prompt-title">{title}</h2>
  <p id="update-prompt-message">{summary}</p>
  {#if prompt.notes && !restartRequired}
    <pre class="update-dialog-notes">{prompt.notes}</pre>
  {/if}
  {#if progressVisible}
    <div class="update-progress" aria-live="polite">
      <progress value={percentage} max={percentage === undefined ? undefined : 100}></progress>
      {#if percentage !== undefined}<span class="meta">{percentage}%</span>{/if}
    </div>
  {/if}
  {#if visibleError}
    <p class="update-error" role="alert">{updateErrorMessage(visibleError)}</p>
  {/if}
  <div class="dialog-actions">
    {#if restartRequired}
      <button type="button" disabled={pending === 'restart'} onclick={closePrompt}>稍后重启</button>
      <button type="button" class="primary-button" disabled={pending === 'restart'} onclick={() => void restart()}>{pending === 'restart' ? '正在重启…' : '立即重启'}</button>
    {:else if working}
      <button type="button" onclick={closePrompt}>后台继续</button>
    {:else}
      <button type="button" class="update-ignore-button" onclick={() => onignore(prompt.version)}>忽略此版本</button>
      <button type="button" onclick={closePrompt}>暂不提醒</button>
      {#if !recoveryRequired}
        <button type="button" class="primary-button" disabled={busy} title={busy ? '后台正在执行其他操作' : undefined} onclick={() => void install()}>{visibleError ? '重试更新' : '立即更新'}</button>
      {/if}
    {/if}
  </div>
</dialog>

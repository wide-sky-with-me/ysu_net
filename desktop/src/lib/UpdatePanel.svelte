<script lang="ts">
  import Confirm from '../components/Confirm.svelte';
  import Icon from '../components/Icon.svelte';
  import { canInstallUpdate, createUpdaterClient, initialUpdateSnapshot, newerUpdateSnapshot, RELEASES_URL, updateErrorCode, updateErrorMessage, updatePercent, updateWorking } from './updater';
  import type { UpdateError, UpdatePhase, UpdateSnapshot } from './updater';

  let { mode, demo = false, busy = false, currentVersion = '' }: { mode: 'desktop' | 'demo' | 'web'; demo?: boolean; busy?: boolean; currentVersion?: string } = $props();
  let snapshot = $state<UpdateSnapshot>(initialUpdateSnapshot('web'));
  let pending = $state(false);
  let openingReleases = $state(false);
  let ready = $state(false);
  let error = $state<UpdateError | null>(null);
  let confirmation = $state<string | null>(null);
  const client = $derived(createUpdaterClient(mode, demo, currentVersion));
  const working = $derived(pending || updateWorking(snapshot.phase));
  const installable = $derived(!working && canInstallUpdate(snapshot, busy));
  const percentage = $derived(updatePercent(snapshot));
  const visibleError = $derived(error || snapshot.error);
  const progressVisible = $derived(['downloading', 'verifying', 'quiescing', 'installing'].includes(snapshot.phase));
  const labels: Record<UpdatePhase, string> = {
    idle: '尚未检查更新', disabled: '模拟模式不联网检查或安装更新。',
    manual: '当前 Linux deb 包请前往发布页手动更新。', checking: '正在检查更新…',
    up_to_date: '当前已是最新版本', available: '发现新版本', downloading: '正在下载更新…',
    verifying: '正在校验签名…', quiescing: '正在停止后台任务…', installing: '正在安装更新…',
    restart_required: '更新已安装，重启后生效。', recovery_required: '后台保持停止', error: '更新未完成',
  };

  function accept(value: UpdateSnapshot) { snapshot = newerUpdateSnapshot(snapshot, value); }

  async function openReleases() {
    if (openingReleases) return;
    openingReleases = true;
    error = null;
    try { await client.openReleases(); }
    catch (value) { error = updateErrorCode(value); }
    finally { openingReleases = false; }
  }

  // Subscriptions and status reads restore native progress after leaving/reopening
  // settings. Neither starts a check/download. Cleanup never cancels installation.
  $effect(() => {
    const activeClient = client;
    let active = true;
    let stop: (() => void) | undefined;
    snapshot = initialUpdateSnapshot(mode, demo, currentVersion);
    ready = false;
    error = null;
    confirmation = null;
    void (async () => {
      try {
        const unsubscribe = await activeClient.subscribe((value) => { if (active) accept(value); }, (code) => { if (active) error = code; });
        if (!active) { unsubscribe(); return; }
        stop = unsubscribe;
        const value = await activeClient.status();
        if (active) { accept(value); ready = true; }
      } catch (value) { if (active) error = updateErrorCode(value); }
    })();
    return () => { active = false; stop?.(); };
  });

  async function run(operation: 'status' | 'check' | 'install' | 'resume' | 'restart', version?: string) {
    if (pending) return;
    if (operation === 'install' && (!installable || version !== snapshot.release?.version)) { error = busy ? 'core_busy' : 'stale_candidate'; return; }
    pending = true;
    error = null;
    try {
      if (operation === 'restart') await client.restart();
      else {
        const value = operation === 'install' ? await client.install(version!) : await client[operation]();
        accept(value);
        ready = true;
      }
    } catch (value) {
      error = updateErrorCode(value);
      // The authoritative state distinguishes an ordinary failure (core restored)
      // from failed core recovery; do not assume rejection means authentication is safe.
      try { accept(await client.status()); ready = true; } catch { /* Keep the fixed error. */ }
    } finally { pending = false; }
  }
</script>

<section class="settings-section update-section" aria-labelledby="software-update-heading">
  <div class="section-heading">
    <h2 id="software-update-heading">软件更新</h2>
    <div class="update-meta">
      {#if snapshot.current_version || currentVersion}<span class="muted numeric">当前版本 {snapshot.current_version || currentVersion}</span>{/if}
      {#if mode !== 'demo' && !demo && snapshot.phase !== 'disabled'}
        {#if mode === 'desktop'}
          <button type="button" class="text-button update-release-link" disabled={openingReleases} onclick={() => { void openReleases(); }}>前往发布页</button>
        {:else}
          <a class="update-release-link" href={RELEASES_URL} target="_blank" rel="noreferrer">前往发布页</a>
        {/if}
      {/if}
    </div>
  </div>
  <div class="setting-row">
    <div aria-live="polite" aria-atomic="true">
      <span>{mode === 'web' ? '请在桌面客户端检查更新。' : snapshot.phase === 'available' && snapshot.release ? `发现新版本 ${snapshot.release.version}` : labels[snapshot.phase]}</span>
      {#if snapshot.release && snapshot.phase !== 'available'}<p class="numeric">新版本 {snapshot.release.version}</p>{/if}
    </div>
    {#if snapshot.phase === 'restart_required'}
      <button type="button" class="primary-button" disabled={working} onclick={() => { void run('restart'); }}>重启应用</button>
    {:else if snapshot.phase === 'recovery_required'}
      {#if snapshot.error === 'recovery_failed'}<button type="button" disabled={working} onclick={() => { void run('resume'); }}>恢复后台</button>{/if}
    {:else if !['disabled', 'manual'].includes(snapshot.phase)}
      <button type="button" disabled={working || busy} onclick={() => { void run(ready ? 'check' : 'status'); }}><Icon name="refresh" size={16} />{!ready ? '重新读取状态' : snapshot.phase === 'checking' ? '正在检查' : '检查更新'}</button>
    {/if}
  </div>
  {#if visibleError}<p class="update-error" role="alert">{updateErrorMessage(visibleError)}</p>{/if}
  {#if snapshot.release?.notes}<details class="update-notes" open><summary><span>更新说明</span></summary><pre>{snapshot.release.notes}</pre></details>{/if}
  {#if progressVisible}
    <div class="update-progress">
      <progress max="100" value={percentage} aria-label="更新下载进度"></progress>
      <span class="muted numeric">{percentage === undefined ? `${Math.floor(snapshot.downloaded / 1024).toLocaleString()} KB` : `${percentage}%`}</span>
    </div>
  {/if}
  {#if snapshot.release && ['available', 'error'].includes(snapshot.phase)}
    <div class="form-actions update-actions">
      {#if busy}<span class="muted">认证任务正在运行，结束后可安装更新。</span>{/if}
      <button type="button" class="primary-button" disabled={!installable} onclick={() => { confirmation = snapshot.release!.version; }}>下载并安装</button>
    </div>
  {/if}
  {#if snapshot.phase === 'restart_required'}<p class="muted update-note">后台已停止，重启后恢复；当前校园网连接未主动下线。</p>{/if}
</section>

{#if confirmation}
  <Confirm title={`安装 ${confirmation}`} message="安装前将停止本客户端的后台任务，不主动下线校园网，不删除账号配置。安装器可能退出客户端；安装完成后需重启。" confirm="确认下载并安装" icon="info" oncancel={() => { confirmation = null; }} onconfirm={() => { const version = confirmation; confirmation = null; if (version) void run('install', version); }} />
{/if}

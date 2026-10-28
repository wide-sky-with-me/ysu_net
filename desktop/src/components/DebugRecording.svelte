<script lang="ts">
  import { onMount } from 'svelte';
  import { parseDebugStatus } from '../lib/debug-recording';
  import type { DebugStatus } from '../lib/debug-recording';
  import type { Transport } from '../lib/protocol';
  let { transport, onnotice }: { transport: Transport; onnotice: (notice: { message: string; error: boolean }) => void } = $props();
  let status = $state<DebugStatus | null>(null);
  let pending = $state(false);
  let mounted = false;
  const labels = { off: '未开启', recording: '正在记录', stopped: '已停止', limit: '已达记录上限', error: '写入失败，记录可能不完整' };
  async function refresh() {
    try {
      const next = parseDebugStatus(await transport.request('debug_status', {}));
      if (mounted) status = next;
    } catch { /* A stopped/update-paused runtime is reported by the main application. */ }
  }
  async function command(name: 'debug_start' | 'debug_stop' | 'debug_open') {
    pending = true;
    try {
      const next = await transport.request(name, {});
      if (!mounted) return;
      if (name !== 'debug_open') { status = parseDebugStatus(next); if (status.state === 'error') throw new Error('recording failed'); }
      onnotice({ message: name === 'debug_start' ? '调试记录已开始，可进行复现。' : name === 'debug_stop' ? '调试记录已停止，文件保留在本机。' : '已请求打开记录目录。', error: false });
    } catch {
      if (mounted) onnotice({ message: name === 'debug_open' ? '无法打开调试记录目录。' : '调试记录操作失败，请检查目录权限或磁盘空间。', error: true });
    } finally {
      if (mounted) { pending = false; await refresh(); }
    }
  }
  onMount(() => {
    mounted = true;
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => { mounted = false; window.clearInterval(timer); };
  });
</script>

<section class="debug-recording" aria-labelledby="debug-recording-heading">
  <div class="debug-heading"><h2 id="debug-recording-heading">链路调试</h2><span role="status">{status ? labels[status.state] : '正在读取状态'}</span></div>
  <div class="form-actions">
    {#if status?.state === 'recording'}
      <button type="button" disabled={pending} onclick={() => { void command('debug_stop'); }}>停止记录</button>
    {:else}
      <button type="button" disabled={pending || !status} onclick={() => { void command('debug_start'); }}>开始调试记录</button>
    {/if}
    <button type="button" disabled={pending || !status?.directory_available} onclick={() => { void command('debug_open'); }}>打开记录目录</button>
  </div>
  <p>记录关键链路，不含密码、Cookie 或认证原文。每份上限 8 MiB，保留最近 5 份。</p>
  {#if status?.file}<p class="debug-file"><code>{status.file}</code><span>{status.records} 条 · {(status.bytes / 1024).toFixed(1)} KiB</span></p>{/if}
</section>

<style>
  .debug-recording { padding: 18px 24px; margin-bottom: 16px; background: var(--surface); border-radius: var(--radius-lg); }
  .debug-heading, .debug-file { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  h2 { font-size: 14px; margin: 0; }
  p, .debug-heading > span { font-size: 12px; color: var(--muted); }
  p { margin: 10px 0 0; }
  .form-actions { margin-top: 12px; }
  code { overflow-wrap: anywhere; }
  @media (forced-colors: active) { .debug-recording { border: 1px solid CanvasText; } }
</style>

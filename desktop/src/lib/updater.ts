import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

export const RELEASES_URL = 'https://github.com/wide-sky-with-me/ysu_net/releases/latest';
export const UPDATE_PHASES = ['idle', 'disabled', 'manual', 'checking', 'up_to_date', 'available', 'downloading', 'verifying', 'reconstructing', 'quiescing', 'installing', 'restart_required', 'recovery_required', 'error'] as const;
export type UpdatePhase = typeof UPDATE_PHASES[number];
export const UPDATE_ERRORS = ['disabled', 'manual_only', 'busy', 'core_busy', 'configuration', 'feed_not_ready', 'check_failed', 'invalid_feed', 'target_missing', 'untrusted_asset', 'no_candidate', 'stale_candidate', 'download_failed', 'signature', 'core_stop_failed', 'install_failed', 'application_restore_failed', 'recovery_failed', 'invalid_state', 'open_failed', 'ipc'] as const;
export type UpdateError = typeof UPDATE_ERRORS[number];
export const DOWNLOAD_MODES = ['full', 'delta', 'cached'] as const;
export type DownloadMode = typeof DOWNLOAD_MODES[number];
export interface UpdateRelease { version: string; notes: string }
export interface UpdateSnapshot {
  sequence: number;
  phase: UpdatePhase;
  current_version: string;
  release: UpdateRelease | null;
  downloaded: number;
  total: number | null;
  download_mode: DownloadMode | null;
  fallback: boolean;
  error: UpdateError | null;
  releases_url: string;
}
export interface UpdaterClient {
  status(): Promise<UpdateSnapshot>;
  check(): Promise<UpdateSnapshot>;
  install(version: string): Promise<UpdateSnapshot>;
  resume(): Promise<UpdateSnapshot>;
  restart(): Promise<void>;
  openReleases(): Promise<void>;
  subscribe(handler: (snapshot: UpdateSnapshot) => void, onerror?: (error: UpdateError) => void): Promise<() => void>;
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const nonnegative = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const includes = <T extends string>(values: readonly T[], value: unknown): value is T => typeof value === 'string' && values.includes(value as T);

export function parseUpdateSnapshot(value: unknown): UpdateSnapshot {
  if (!object(value) || !nonnegative(value.sequence) || !includes(UPDATE_PHASES, value.phase) ||
      typeof value.current_version !== 'string' || !nonnegative(value.downloaded) ||
      !(value.total === null || nonnegative(value.total)) || !(value.error === null || includes(UPDATE_ERRORS, value.error)) ||
      !(value.download_mode === undefined || value.download_mode === null || includes(DOWNLOAD_MODES, value.download_mode)) ||
      !(value.fallback === undefined || typeof value.fallback === 'boolean') ||
      !(value.release === null || (object(value.release) && typeof value.release.version === 'string' &&
        value.release.version.length <= 128 && typeof value.release.notes === 'string' && value.release.notes.length <= 65_536))) {
    throw 'ipc' satisfies UpdateError;
  }
  if (['available', 'downloading', 'verifying', 'reconstructing', 'quiescing', 'installing', 'restart_required'].includes(value.phase) && !value.release) throw 'ipc' satisfies UpdateError;
  return {
    sequence: value.sequence, phase: value.phase, current_version: value.current_version,
    release: value.release === null ? null : { version: String((value.release as Record<string, unknown>).version), notes: String((value.release as Record<string, unknown>).notes) },
    downloaded: value.downloaded, total: value.total as number | null, error: value.error as UpdateError | null,
    download_mode: value.download_mode === undefined ? null : value.download_mode as DownloadMode | null,
    fallback: value.fallback === true,
    // Never trust an IPC/feed-supplied navigation URL.
    releases_url: RELEASES_URL,
  };
}

export function initialUpdateSnapshot(mode: 'desktop' | 'demo' | 'web', demo = false, currentVersion = ''): UpdateSnapshot {
  return { sequence: 0, phase: mode === 'demo' || demo ? 'disabled' : mode === 'web' ? 'manual' : 'idle', current_version: currentVersion, release: null, downloaded: 0, total: null, download_mode: null, fallback: false, error: null, releases_url: RELEASES_URL };
}

export function updateErrorCode(error: unknown): UpdateError {
  // In particular, do not render Error.message or arbitrary rejected IPC strings.
  return includes(UPDATE_ERRORS, error) ? error : 'ipc';
}

export function updateErrorMessage(error: UpdateError): string {
  const messages: Record<UpdateError, string> = {
    disabled: '模拟模式不联网检查或安装更新。',
    manual_only: '当前安装包请前往发布页手动更新。',
    busy: '更新任务正在进行，请稍候。',
    core_busy: '认证任务正在运行，结束后可重试安装。',
    configuration: '更新配置尚未就绪，请前往发布页手动更新。',
    feed_not_ready: '更新源尚未就绪，请稍后重试或前往发布页。',
    check_failed: '检查更新失败，请检查网络后重试。',
    invalid_feed: '更新清单格式异常，请稍后重试。',
    target_missing: '此版本尚未提供当前系统的更新包，请查看发布页。',
    untrusted_asset: '更新包地址校验失败，已停止更新。',
    no_candidate: '请先检查更新。',
    stale_candidate: '待安装版本已变化，请重新检查并确认。',
    download_failed: '下载失败，当前版本未变更，可重试。',
    signature: '更新包签名校验失败，已停止安装。请重新检查或前往发布页。',
    core_stop_failed: '后台任务尚未停止，更新未安装。请等待后重试。',
    install_failed: '安装失败，后台已恢复；可重试或手动更新。',
    application_restore_failed: '安装及旧版本恢复失败。后台保持停止，请退出后从发布页重新安装。',
    recovery_failed: '安装失败且后台恢复失败。请重试恢复后台，或退出后重新打开。',
    invalid_state: '当前更新状态不支持此操作。',
    open_failed: `无法打开发布页，请检查系统默认浏览器，或在浏览器中访问 ${RELEASES_URL}。`,
    ipc: '读取更新状态失败，请重新打开设置后重试。',
  };
  return messages[error];
}

export const updateWorking = (phase: UpdatePhase): boolean => ['checking', 'downloading', 'verifying', 'reconstructing', 'quiescing', 'installing'].includes(phase);
export function canInstallUpdate(snapshot: UpdateSnapshot, authBusy: boolean): boolean {
  return !authBusy && !!snapshot.release && (snapshot.phase === 'available' || snapshot.phase === 'error');
}
export function updatePercent(snapshot: UpdateSnapshot): number | undefined {
  return snapshot.total && snapshot.total > 0 ? Math.min(100, Math.floor(snapshot.downloaded / snapshot.total * 100)) : undefined;
}
export function newerUpdateSnapshot(current: UpdateSnapshot, next: UpdateSnapshot): UpdateSnapshot {
  return next.sequence >= current.sequence ? next : current;
}

export function updateDownloadLabel(snapshot: UpdateSnapshot): string | undefined {
  if (snapshot.phase === 'reconstructing') return '正在还原完整更新包…';
  if (snapshot.phase !== 'downloading') return undefined;
  if (snapshot.download_mode === 'delta') return '正在下载差分补丁…';
  if (snapshot.download_mode === 'cached') return '正在读取已验证更新包…';
  return snapshot.fallback ? '差分不可用，正在下载完整包…' : '正在下载完整更新包…';
}

export function createUpdaterClient(mode: 'desktop' | 'demo' | 'web', demo = false, currentVersion = ''): UpdaterClient {
  const initial = initialUpdateSnapshot(mode, demo, currentVersion);
  if (mode !== 'desktop' || demo) {
    const blocked = async (): Promise<never> => { throw initial.phase === 'disabled' ? 'disabled' : 'manual_only'; };
    // Demo uses real disabled semantics, not invented update versions/progress.
    return { status: async () => initial, check: blocked, install: blocked, resume: blocked, restart: blocked, openReleases: blocked, subscribe: async () => () => {} };
  }
  const request = async (command: string, args?: Record<string, unknown>): Promise<UpdateSnapshot> => {
    try { return parseUpdateSnapshot(await invoke(command, args)); }
    catch (error) { throw updateErrorCode(error); }
  };
  return {
    status: () => request('updater_status'),
    check: () => request('updater_check'),
    install: (version) => request('updater_install', { version }),
    resume: () => request('updater_resume'),
    restart: async () => { try { await invoke('updater_restart'); } catch (error) { throw updateErrorCode(error); } },
    // The native command accepts no URL or application override.
    openReleases: async () => { try { await invoke('updater_open_releases'); } catch (error) { throw updateErrorCode(error); } },
    subscribe: (handler, onerror) => listen('updater-event', (event) => {
      try { handler(parseUpdateSnapshot(event.payload)); } catch { onerror?.('ipc'); }
    }).catch(() => { throw 'ipc' satisfies UpdateError; }),
  };
}

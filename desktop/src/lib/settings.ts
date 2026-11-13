import { parseSnapshot } from './protocol';
import type { CoreCommands, DesktopSettings, Snapshot } from './protocol';
import { parseStartupUpdatePrompt } from './updater';

export type Setting = 'autostart' | 'startup' | 'tray' | 'theme' | 'accent' | 'auto_check_update' | 'auto_install_update' | 'ignore_update';
export const SETTING_UNCONFIRMED = '保存结果尚未确认，请重试。';
export const settingBusyMessage: Record<Setting, string> = {
  autostart: '正在更新系统自启…', startup: '正在保存启动方式…',
  tray: '正在保存托盘设置…', theme: '正在保存界面主题…', accent: '正在保存主题色…',
  auto_check_update: '正在保存自动更新设置…',
  auto_install_update: '正在保存自动下载安装设置…',
  ignore_update: '正在忽略此版本…',
};
const failures: Record<Setting, string> = {
  autostart: '系统自启设置未保存，请检查当前用户权限后重试。',
  startup: '启动方式未保存，请稍后重试。', tray: '托盘设置未保存，请稍后重试。',
  theme: '界面主题未保存，请稍后重试。', accent: '主题色未保存，请稍后重试。',
  auto_check_update: '自动更新设置未保存，请稍后重试。',
  auto_install_update: '自动下载安装设置未保存，请稍后重试。',
  ignore_update: '忽略版本未保存，请稍后重试。',
};

export function settingError(setting: Setting, error: unknown): string {
  const message = error instanceof Error ? error.message : error;
  // These are presentation-owned strings, never arbitrary OS paths or IPC errors.
  return message === SETTING_UNCONFIRMED ? SETTING_UNCONFIRMED : failures[setting];
}

export function parseDesktopSettings(value: unknown): DesktopSettings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(SETTING_UNCONFIRMED);
  const data = value as Record<string, unknown>;
  if (typeof data.autostart !== 'boolean' || typeof data.tray_available !== 'boolean' || typeof data.version !== 'string' ||
      (data.demo !== undefined && typeof data.demo !== 'boolean') || (data.tray_tooltip !== undefined && typeof data.tray_tooltip !== 'boolean') ||
      (data.updater_supported !== undefined && typeof data.updater_supported !== 'boolean')) throw new Error(SETTING_UNCONFIRMED);
  const startupUpdate = parseStartupUpdatePrompt(data.startup_update);
  return { autostart: data.autostart, tray_available: data.tray_available, version: data.version,
    ...(data.demo === undefined ? {} : { demo: data.demo as boolean }),
    ...(data.tray_tooltip === undefined ? {} : { tray_tooltip: data.tray_tooltip as boolean }),
    ...(data.updater_supported === undefined ? {} : { updater_supported: data.updater_supported as boolean }),
    ...(startupUpdate ? { startup_update: startupUpdate } : {}) };
}

export function confirmAutostart(actual: DesktopSettings, requested: boolean): void {
  if (actual.autostart !== requested) throw new Error(SETTING_UNCONFIRMED);
}

export function confirmedPreferences(value: unknown, changes: CoreCommands['save_prefs']): Snapshot {
  const data = value as { prefs?: Record<string, unknown> } | null;
  const entries = Object.entries(changes);
  // Legacy display defaults are not evidence that a newly requested write succeeded.
  if (!entries.length || !data?.prefs || entries.some(([key, expected]) =>
    !['theme', 'accent', 'close_to_tray', 'autostart_minimized', 'auto_check_update', 'auto_install_update', 'ignored_update_version'].includes(key) ||
    !Object.prototype.hasOwnProperty.call(data.prefs, key) || data.prefs![key] !== expected)) throw new Error(SETTING_UNCONFIRMED);
  return parseSnapshot(value);
}

export function preferenceNotice(changes: CoreCommands['save_prefs']): string {
  if (changes.ignored_update_version !== undefined && changes.ignored_update_version) return '已忽略此版本更新';
  if (changes.auto_install_update !== undefined) return changes.auto_install_update ? '已开启自动下载安装更新' : '已关闭自动下载安装更新';
  if (changes.auto_check_update !== undefined) return changes.auto_check_update ? '已开启自动检查更新' : '已关闭自动检查更新';
  if (changes.autostart_minimized !== undefined) return changes.autostart_minimized ? '自启后将进入托盘' : '自启后将显示窗口';
  if (changes.close_to_tray !== undefined) return changes.close_to_tray ? '关闭窗口后保留托盘' : '关闭窗口后退出应用';
  return changes.accent !== undefined ? '主题色已保存' : '界面主题已保存';
}

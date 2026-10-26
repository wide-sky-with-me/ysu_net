import { parseSnapshot } from './protocol';
import type { CoreCommands, DesktopSettings, Snapshot } from './protocol';

export type Setting = 'autostart' | 'startup' | 'tray' | 'theme' | 'accent';
export const SETTING_UNCONFIRMED = '保存结果尚未确认，请重试。';
export const settingBusyMessage: Record<Setting, string> = {
  autostart: '正在更新系统自启…', startup: '正在保存启动方式…',
  tray: '正在保存托盘设置…', theme: '正在保存界面主题…', accent: '正在保存主题色…',
};
const failures: Record<Setting, string> = {
  autostart: '系统自启设置未保存，请检查当前用户权限后重试。',
  startup: '启动方式未保存，请稍后重试。', tray: '托盘设置未保存，请稍后重试。',
  theme: '界面主题未保存，请稍后重试。', accent: '主题色未保存，请稍后重试。',
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
      (data.demo !== undefined && typeof data.demo !== 'boolean') || (data.tray_tooltip !== undefined && typeof data.tray_tooltip !== 'boolean')) throw new Error(SETTING_UNCONFIRMED);
  return { autostart: data.autostart, tray_available: data.tray_available, version: data.version,
    ...(data.demo === undefined ? {} : { demo: data.demo as boolean }),
    ...(data.tray_tooltip === undefined ? {} : { tray_tooltip: data.tray_tooltip as boolean }) };
}

export function confirmAutostart(actual: DesktopSettings, requested: boolean): void {
  if (actual.autostart !== requested) throw new Error(SETTING_UNCONFIRMED);
}

export function confirmedPreferences(value: unknown, changes: CoreCommands['save_prefs']): Snapshot {
  const data = value as { prefs?: Record<string, unknown> } | null;
  const entries = Object.entries(changes);
  // Legacy display defaults are not evidence that a newly requested write succeeded.
  if (!entries.length || !data?.prefs || entries.some(([key, expected]) =>
    !['theme', 'accent', 'close_to_tray', 'autostart_minimized'].includes(key) ||
    !Object.prototype.hasOwnProperty.call(data.prefs, key) || data.prefs![key] !== expected)) throw new Error(SETTING_UNCONFIRMED);
  return parseSnapshot(value);
}

export function preferenceNotice(changes: CoreCommands['save_prefs']): string {
  if (changes.autostart_minimized !== undefined) return changes.autostart_minimized ? '自启后将进入托盘' : '自启后将显示窗口';
  if (changes.close_to_tray !== undefined) return changes.close_to_tray ? '关闭窗口后保留托盘' : '关闭窗口后退出应用';
  return changes.accent !== undefined ? '主题色已保存' : '界面主题已保存';
}

import { normalizeAccent, type Accent } from './accents';

export const SERVICES = ['校园网', '中国移动', '中国联通', '中国电信'] as const;
export type Service = (typeof SERVICES)[number];
export type Theme = 'system' | 'light' | 'dark';
export type Pair = [string, string];
export type LogLevel = 'info' | 'success' | 'error';

export interface PublicConfig {
  username: string;
  service: Service;
  backend: 'api' | 'browser';
  base: string;
  cas_host: string;
  verify_tls: boolean;
  check_interval: number;
  retry_interval: number;
  max_retry_interval: number;
  operation_timeout: number;
  password_set: boolean;
}
export type ConfigChanges = Partial<Omit<PublicConfig, 'password_set'>> & { password?: string };
export interface PublicAccount {
  id: string;
  label: string;
  username: string;
  service: Service;
  backend: 'api' | 'browser';
  enabled: boolean;
  password_set: boolean;
  current: boolean;
}
export interface SaveAccount {
  id?: string;
  label: string;
  username: string;
  password?: string;
  service: Service;
  backend: 'api' | 'browser';
  enabled: boolean;
}
export interface Accounts {
  items: PublicAccount[];
  auto_switch: boolean;
  environment_override: boolean;
  error: string;
  quota: { state: 'unknown' | 'available' | 'zero_reported' | 'unlimited'; message: string };
  message: string;
}
export interface Snapshot {
  sequence: number;
  accounts: Accounts;
  config: PublicConfig;
  prefs: { theme: Theme; accent: Accent; close_to_tray: boolean; auto_reconnect: boolean };
  status: { online: boolean | null; service: string | null; user: string; ip: string; message: string } | null;
  auto: { state: 'off' | 'on' | 'external'; message: string; delay?: number };
  busy: boolean;
  busy_message: string;
  info: { online: boolean; fields: Pair[]; items: Pair[] } | null;
  info_error: string;
  logs: { timestamp: string; level: LogLevel; message: string }[];
  environment: {
    version: string; rust: string; runtime: 'rust'; platform: string;
    browser_available: boolean; browser_component_available: boolean;
  };
}
export interface DesktopSettings { autostart: boolean; tray_available: boolean; tray_tooltip?: boolean; version: string; demo?: boolean }
export interface CoreCommands {
  snapshot: Record<string, never>;
  action: { name: 'status' | 'info' | 'login' | 'logout' | 'switch' | 'set_service' | 'set_auto' | 'switch_account'; value?: string | boolean };
  save_config: ConfigChanges;
  save_account: SaveAccount;
  delete_account: { id: string };
  rotation: { enabled: boolean };
  save_prefs: { theme?: Theme; accent?: Accent; close_to_tray?: boolean };
  diagnostics: Record<string, never>;
  browser_install: Record<string, never>;
}
export interface Transport {
  mode: 'desktop' | 'demo' | 'web';
  request<C extends keyof CoreCommands>(command: C, args: CoreCommands[C]): Promise<unknown>;
  subscribe(handler: (event: unknown) => void): Promise<() => void>;
  getDesktopSettings(): Promise<DesktopSettings>;
  setAutostart(enabled: boolean): Promise<void>;
  quit(): Promise<void>;
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const bool = (value: unknown): value is boolean => typeof value === 'boolean';
const nullableText = (value: unknown) => value === null || text(value);
const pairs = (value: unknown): value is Pair[] => Array.isArray(value) && value.every((pair) => Array.isArray(pair) && pair.length === 2 && pair.every(text));
const enumValue = <T extends string>(value: unknown, values: readonly T[]): value is T => text(value) && values.includes(value as T);
const seconds = (value: unknown): value is number => Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 86400;

const accountId = (value: unknown): value is string => text(value) && (value === 'current' || /^[a-f0-9]{32}$/.test(value));

function parseAccounts(value: unknown): Accounts {
  if (!object(value) || !Array.isArray(value.items) || value.items.length > 33 ||
      ![value.auto_switch, value.environment_override].every(bool) || !text(value.error) || !text(value.message) ||
      !object(value.quota) || !enumValue(value.quota.state, ['unknown', 'available', 'zero_reported', 'unlimited']) || !text(value.quota.message)) throw new Error('桌面核心账号簿格式异常');
  const ids = new Set<string>(); const usernames = new Set<string>();
  let currentCount = 0;
  const items = value.items.map((item): PublicAccount => {
    if (!object(item) || !accountId(item.id) || !text(item.label) || [...item.label].length > 80 ||
        !text(item.username) || !item.username.trim() || !enumValue(item.service, SERVICES) || !enumValue(item.backend, ['api', 'browser']) ||
        !bool(item.enabled) || !bool(item.password_set) || !bool(item.current) || (item.id === 'current' && !item.current) ||
        ids.has(item.id) || usernames.has(item.username)) throw new Error('桌面核心账号条目格式异常');
    ids.add(item.id); usernames.add(item.username);
    if (item.current) currentCount += 1;
    return { id: item.id, label: item.label, username: item.username, service: item.service, backend: item.backend, enabled: item.enabled, password_set: item.password_set, current: item.current };
  });
  if (currentCount > 1 || items.filter((item) => item.id !== 'current').length > 32) throw new Error('桌面核心当前账号格式异常');
  return { items, auto_switch: value.auto_switch as boolean, environment_override: value.environment_override as boolean, error: value.error, quota: { state: value.quota.state, message: value.quota.message }, message: value.message };
}

export function parseSnapshot(value: unknown): Snapshot {
  if (!object(value) || !Number.isSafeInteger(value.sequence) || Number(value.sequence) < 0) throw new Error('桌面核心状态序号格式异常');
  const { config: c, prefs: p, status: s, auto: a, info: i, environment: e } = value;
  // Native IPC requires accounts. No implicit fallback to the retired JSONL schema.
  const accounts = parseAccounts(value.accounts);
  if (!object(c) || !text(c.username) || !enumValue(c.service, SERVICES) || !enumValue(c.backend, ['api', 'browser']) ||
      !text(c.base) || !text(c.cas_host) || !bool(c.verify_tls) || !bool(c.password_set) ||
      ![c.check_interval, c.retry_interval, c.max_retry_interval, c.operation_timeout].every(seconds)) throw new Error('桌面核心配置格式异常');
  if (!object(p) || !enumValue(p.theme, ['system', 'light', 'dark']) || !bool(p.close_to_tray) || !bool(p.auto_reconnect)) throw new Error('桌面核心偏好格式异常');
  if (s !== null && (!object(s) || !(s.online === null || bool(s.online)) || !nullableText(s.service) || !text(s.user) || !text(s.ip) || !text(s.message))) throw new Error('桌面核心连接状态格式异常');
  if (!object(a) || !enumValue(a.state, ['off', 'on', 'external']) || !text(a.message) || (a.delay !== undefined && (typeof a.delay !== 'number' || !Number.isFinite(a.delay) || a.delay < 0))) throw new Error('桌面核心重连状态格式异常');
  if (!bool(value.busy) || !text(value.busy_message)) throw new Error('桌面核心任务状态格式异常');
  if (i !== null && (!object(i) || !bool(i.online) || !pairs(i.fields) || !pairs(i.items))) throw new Error('桌面核心账户信息格式异常');
  if (value.info_error !== undefined && !text(value.info_error)) throw new Error('桌面核心账户读取错误格式异常');
  if (!Array.isArray(value.logs) || !value.logs.every((log) => object(log) && text(log.timestamp) && enumValue(log.level, ['info', 'success', 'error']) && text(log.message))) throw new Error('桌面核心日志格式异常');
  if (!object(e) || ![e.version, e.rust, e.platform].every(text) || e.runtime !== 'rust' || ![e.browser_available, e.browser_component_available].every(bool)) throw new Error('桌面核心环境信息格式异常');
  // Select the public contract so an accidental extra password field never enters UI state.
  return {
    sequence: Number(value.sequence), accounts,
    config: {
      username: c.username, service: c.service, backend: c.backend, base: c.base, cas_host: c.cas_host,
      verify_tls: c.verify_tls, password_set: c.password_set, check_interval: Number(c.check_interval),
      retry_interval: Number(c.retry_interval), max_retry_interval: Number(c.max_retry_interval), operation_timeout: Number(c.operation_timeout),
    },
    prefs: { theme: p.theme, accent: normalizeAccent(p.accent), close_to_tray: p.close_to_tray, auto_reconnect: p.auto_reconnect },
    status: s === null ? null : { online: s.online as boolean | null, service: s.service as string | null, user: s.user as string, ip: s.ip as string, message: s.message as string },
    auto: { state: a.state, message: a.message, ...(a.delay === undefined ? {} : { delay: a.delay as number }) },
    busy: value.busy, busy_message: value.busy_message,
    info: i === null ? null : { online: i.online as boolean, fields: i.fields as Pair[], items: i.items as Pair[] },
    info_error: value.info_error === undefined ? '' : value.info_error as string,
    logs: value.logs.map((log) => ({ timestamp: log.timestamp as string, level: log.level as LogLevel, message: log.message as string })),
    environment: { version: e.version as string, rust: e.rust as string, runtime: 'rust', platform: e.platform as string, browser_available: e.browser_available as boolean, browser_component_available: e.browser_component_available as boolean },
  };
}

export function snapshotEvent(event: unknown): Snapshot | null {
  if (!object(event) || event.kind !== 'event' || event.name !== 'snapshot') return null;
  return parseSnapshot(event.payload);
}

export class SnapshotSequence {
  private latest = -1;
  accept(snapshot: Snapshot): boolean {
    if (snapshot.sequence <= this.latest) return false;
    this.latest = snapshot.sequence;
    return true;
  }
}

export async function synchronizeSnapshots(transport: Transport, receive: (snapshot: Snapshot) => void, failure: (error: unknown) => void): Promise<() => void> {
  const sequence = new SnapshotSequence();
  let active = true;
  const accept = (snapshot: Snapshot) => { if (active && sequence.accept(snapshot)) receive(snapshot); };
  // Event registration completes before the request; a newer event wins any race with its response.
  const unlisten = await transport.subscribe((event) => {
    try { const snapshot = snapshotEvent(event); if (snapshot) accept(snapshot); }
    catch (error) { if (active) failure(error); }
  });
  try { accept(parseSnapshot(await transport.request('snapshot', {}))); }
  catch (error) { active = false; unlisten(); throw error; }
  return () => { active = false; unlisten(); };
}

export function accountItems(info: Snapshot['info']): Pair[] {
  if (!info?.online) return [];
  const items: Pair[] = info.items.map(([name, value]) => [name, value.trim() ? value : '门户未提供']);
  if (!items.some(([name]) => name.includes('剩余流量'))) items.push(['剩余流量', '门户未提供']);
  if (!items.some(([name]) => name.includes('余额'))) items.push(['账户余额', '门户未提供']);
  return items;
}

export function validateAccount(changes: SaveAccount, items: PublicAccount[]): string | null {
  const existing = changes.id ? items.find((item) => item.id === changes.id) : undefined;
  if (changes.id && (!accountId(changes.id) || !existing)) return '账号已变更，请关闭后重新编辑';
  if (!changes.username.trim()) return '请输入校园网账号';
  if (existing && existing.username !== changes.username) return '已保存账号的用户名固定，请新增账号';
  if (items.some((item) => item.id !== changes.id && item.username === changes.username)) return '该用户名已在账号簿中';
  if ([...changes.label].length > 80) return '账号名称最多 80 个字符';
  if (!existing?.password_set && !changes.password) return '新账号须填写密码';
  if (!enumValue(changes.service, SERVICES) || !enumValue(changes.backend, ['api', 'browser']) || !bool(changes.enabled)) return '请选择有效的运营商与认证方式';
  if (!changes.id && items.filter((item) => item.id !== 'current').length >= 32) return '最多保存 32 个账号';
  return null;
}

export function rotationControl(snapshot: Snapshot | null): { canEnable: boolean; reason: string } {
  if (!snapshot) return { canEnable: false, reason: '等待桌面核心' };
  if (snapshot.accounts.environment_override) return { canEnable: false, reason: '环境变量覆盖中，账号切换已停用' };
  if (snapshot.auto.state === 'external') return { canEnable: false, reason: '连接由外部后台服务管理' };
  if (snapshot.accounts.error) return { canEnable: false, reason: snapshot.accounts.error };
  if (snapshot.accounts.items.filter((item) => item.enabled && item.password_set).length < 2) return { canEnable: false, reason: '至少需要两个已启用且已保存密码的账号' };
  if (snapshot.auto.state !== 'on' || !snapshot.prefs.auto_reconnect) return { canEnable: false, reason: '请先开启自动重连' };
  if (snapshot.busy) return { canEnable: false, reason: '当前认证任务完成后可开启' };
  return { canEnable: true, reason: '' };
}

export function validateConfig(changes: ConfigChanges, current: PublicConfig): string | null {
  const config = { ...current, ...changes };
  if (!config.username.trim()) return '请输入校园网账号';
  if (!config.password_set && !changes.password) return '请输入密码；已有密码时可留空保留';
  for (const key of ['base', 'cas_host'] as const) {
    try {
      const url = new URL(config[key]);
      if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) return '认证地址须为不含账号密码的 HTTPS URL';
    } catch { return '请输入完整的 HTTPS 认证地址'; }
  }
  if (![config.check_interval, config.retry_interval, config.max_retry_interval, config.operation_timeout].every(seconds)) return '时间间隔须为 1 至 86400 秒的整数';
  if (config.max_retry_interval < config.retry_interval) return '最长重试间隔须大于或等于首次重试间隔';
  return null;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return '操作未完成，请查看日志或运行诊断';
}

export function formatDiagnostics(value: unknown): string {
  const environment = object(value) && object(value.environment) ? value.environment : null;
  if (!environment) return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || '诊断未返回内容';
  return [
    `客户端版本：${environment.version || '未提供'}`,
    `认证核心：Rust 原生（${environment.rust || '版本未提供'}）`,
    `平台：${environment.platform || '未提供'}`,
    `系统浏览器：${environment.browser_available ? '已发现 Edge / Chrome' : '未发现，请安装 Edge 或 Chrome'}`,
    `浏览器认证：${environment.browser_component_available ? '原生 CDP，无需额外运行时' : '当前安装未包含'}`,
  ].join('\n');
}

export function advanceLogFloor(previous: Snapshot['logs'], next: Snapshot['logs'], floor: number): number {
  if (!floor) return 0;
  const same = (a: Snapshot['logs'][number], b: Snapshot['logs'][number]) => a.timestamp === b.timestamp && a.level === b.level && a.message === b.message;
  // Find suffix/prefix overlap when the core's bounded log buffer rolls over.
  for (let removed = 0; removed < previous.length; removed += 1) {
    const overlap = previous.length - removed;
    if (overlap <= next.length && previous.slice(removed).every((log, index) => same(log, next[index]))) return Math.max(0, floor - removed);
  }
  return 0;
}

export function formatLogTime(timestamp: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T/.test(timestamp)) return timestamp;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleTimeString('zh-CN', { hour12: false });
}

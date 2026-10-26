import { SERVICES, type Service, type Snapshot } from './protocol';

function confirmedOnlineService(snapshot: Snapshot | null): Service | undefined {
  return snapshot?.status?.online === true
    ? SERVICES.find((service) => service === snapshot.status?.service) : undefined;
}

/** Online facts choose the visible carrier; this never rewrites account intent. */
export function connectionService(snapshot: Snapshot | null): Service | undefined {
  return confirmedOnlineService(snapshot) || snapshot?.config.service;
}

export function connectionTitle(snapshot: Snapshot | null): string {
  if (snapshot?.status?.online === true) return `${confirmedOnlineService(snapshot) || '校园网'}已连接`;
  return snapshot?.status?.online === false ? '校园网未连接' : '连接状态未知';
}

const ROUTINE_RECONNECT_MESSAGES = new Set([
  '自动重连已关闭',
  '自动重连已开启，正在检查',
  '正在监测连接，断线后自动登录',
  '已确认在线',
  '重连已独立确认成功',
  '本轮账号检查结束，稍后重新查询',
]);

export function reconnectNotice(auto: Snapshot['auto'] | undefined): string {
  if (!auto || auto.state === 'external' || ROUTINE_RECONNECT_MESSAGES.has(auto.message)) return '';
  return auto.message;
}

const ROUTINE_SWITCH_MESSAGES = new Set([
  '流量自动换号已关闭',
  '随自动重连检查剩余流量',
  '自动换号已关闭',
  '自动换号已开启，额度观测由核心处理',
]);

/** Switch position already conveys routine state; keep failures and unfamiliar results. */
export function accountSwitchNotice(message: string | undefined): string {
  return !message || ROUTINE_SWITCH_MESSAGES.has(message) ? '' : message;
}

export function accountInfoState(snapshot: Snapshot | null): 'error' | 'ready' | 'offline' | 'unread' | 'unknown' {
  if (snapshot?.info_error) return 'error';
  if (snapshot?.info?.online) return 'ready';
  if (snapshot?.status?.online === false || snapshot?.info?.online === false) return 'offline';
  return snapshot?.status?.online === true ? 'unread' : 'unknown';
}

/** Decoration gating only; never use this as quota or rotation evidence. */
export function canAnimateQuota(name: string, value: string): boolean {
  return /流量|用量|额度/.test(name) && /^[+]?\d/.test(value.trim()) && Number.parseFloat(value) > 0;
}

import type { Snapshot } from './protocol';

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

export function accountInfoState(snapshot: Snapshot | null): 'error' | 'ready' | 'offline' | 'unread' | 'unknown' {
  if (snapshot?.info_error) return 'error';
  if (snapshot?.info?.online) return 'ready';
  if (snapshot?.status?.online === false || snapshot?.info?.online === false) return 'offline';
  return snapshot?.status?.online === true ? 'unread' : 'unknown';
}

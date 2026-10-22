import { describe, expect, it } from 'vitest';
import { accountInfoState, reconnectNotice } from './presentation';
import { demoSnapshot } from './demo';

describe('reconnect presentation', () => {
  it.each([
    '自动重连已关闭',
    '自动重连已开启，正在检查',
    '正在监测连接，断线后自动登录',
    '已确认在线',
    '重连已独立确认成功',
    '本轮账号检查结束，稍后重新查询',
  ])('omits routine copy: %s', (message) => {
    expect(reconnectNotice({ state: 'on', message, delay: 15 })).toBe('');
  });

  it.each([
    '操作超过时限，等待重新查询状态',
    '在线；认证暂停保持，修改配置或手动登录后恢复',
    '配置不可用，等待修复，未发起登录',
    '尚未分类的新状态信息',
  ])('retains actionable and unfamiliar messages: %s', (message) => {
    expect(reconnectNotice({ state: 'on', message, delay: 30 })).toBe(message);
  });

  it('leaves the external-service notice to the connection context', () => {
    expect(reconnectNotice({ state: 'external', message: '外部服务管理此配置' })).toBe('');
  });

  it('does not invent status before the core snapshot arrives', () => {
    expect(reconnectNotice(undefined)).toBe('');
  });
});

describe('account information presentation', () => {
  it('separates unknown connection, confirmed offline and unread online data', () => {
    expect(accountInfoState(null)).toBe('unknown');
    expect(accountInfoState(demoSnapshot('?scenario=unknown'))).toBe('unknown');
    expect(accountInfoState(demoSnapshot('?scenario=offline'))).toBe('offline');
    expect(accountInfoState(demoSnapshot('?scenario=info-unread'))).toBe('unread');
    expect(accountInfoState(demoSnapshot())).toBe('ready');
  });

  it('keeps account errors visible independently of connection status', () => {
    const failed = demoSnapshot('?scenario=info-error');
    for (const online of [true, false, null]) {
      expect(accountInfoState({ ...failed, status: { ...failed.status!, online } })).toBe('error');
    }
    expect(accountInfoState({ ...failed, info_error: '' })).toBe('unread');
  });

  it('uses successful account results without rewriting the independent connection observation', () => {
    const state = demoSnapshot();
    const offline = { ...state, status: { ...state.status!, online: false } };
    expect(accountInfoState(offline)).toBe('ready');
    expect(offline.status.online).toBe(false);
    expect(accountInfoState({ ...state, status: { ...state.status!, online: null } })).toBe('ready');
    expect(accountInfoState({ ...state, info: { online: false, fields: [], items: [] }, status: null })).toBe('offline');
  });
});

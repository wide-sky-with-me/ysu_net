import { describe, expect, it } from 'vitest';
import { accountInfoState, accountSwitchNotice, canAnimateQuota, reconnectNotice } from './presentation';
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

describe('account switch presentation', () => {
  it.each([
    '流量自动换号已关闭', '随自动重连检查剩余流量',
    '自动换号已关闭', '自动换号已开启，额度观测由核心处理',
  ])('omits only routine copy already conveyed by the switch: %s', (message) => {
    expect(accountSwitchNotice(message)).toBe('');
  });

  it.each([
    '正在确认目标账号，当前账号尚未变更',
    '已确认切换到备用账号',
    '模拟：目标账号登录失败，已独立确认恢复原连接',
    '流量自动换号已关闭：账号凭据不可用',
    '未知的新轮换状态',
  ])('retains actionable results and unfamiliar states: %s', (message) => {
    expect(accountSwitchNotice(message)).toBe(message);
  });

  it('does not invent state before a snapshot arrives', () => {
    expect(accountSwitchNotice(undefined)).toBe('');
    expect(accountSwitchNotice('')).toBe('');
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

describe('quota decoration is not quota evidence', () => {
  it.each([
    ['剩余流量', '80.00 GB', true], ['已用流量', '0.25 GiB', true],
    ['剩余流量', '门户未提供', false], ['剩余流量', '0 GB', false],
    ['剩余流量', '0.00 GB', false], ['剩余流量', '不限量', false],
    ['剩余流量', '-1 GB', false], ['账户余额', '80.00 元', false],
  ])('keeps decoration separate from the original value: %s / %s', (name, value, expected) => {
    expect(canAnimateQuota(name as string, value as string)).toBe(expected);
  });
});

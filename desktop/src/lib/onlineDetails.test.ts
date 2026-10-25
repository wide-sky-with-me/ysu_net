import { describe, expect, it } from 'vitest';
import { onlineDetailKind, partitionOnlineDetails } from './onlineDetails';

describe('online account detail presentation', () => {
  it.each(['账号', '帐号', '校园网账号', '用户名', '学号', ' UserName ', 'account_id'])('recognizes an identity label without changing it: %s', (name) => {
    const grouped = partitionOnlineDetails([[name, '20260001']]);
    expect(grouped.identity?.name).toBe(name);
    expect(grouped.identity?.value).toBe('20260001');
    expect(grouped.identity?.kind).toBe('identity');
  });

  it('uses a leading account header and keeps every other original field in order', () => {
    const fields = [['当前服务', '中国联通'], ['账号', '  original-user  '], ['IP 地址', '2001:db8::10'], ['自定义字段', '原始\n值']] as const;
    const grouped = partitionOnlineDetails(fields);
    expect(grouped.identity?.index).toBe(1);
    expect(grouped.identity?.value).toBe('  original-user  ');
    expect(grouped.details.map((field) => [field.name, field.value])).toEqual([fields[0], fields[2], fields[3]]);
    const restored = [...(grouped.identity ? [grouped.identity] : []), ...grouped.details].sort((a, b) => a.index - b.index);
    expect(restored.map((field) => [field.name, field.value])).toEqual(fields);
  });

  it('keeps duplicate identities and unknown fields instead of dropping data', () => {
    const grouped = partitionOnlineDetails([['账号', 'first'], ['用户名', 'second'], ['自定义字段', 'value']]);
    expect(grouped.identity?.value).toBe('first');
    expect(grouped.details.map((field) => field.value)).toEqual(['second', 'value']);
    expect(new Set([grouped.identity?.index, ...grouped.details.map((field) => field.index)]).size).toBe(3);
  });

  it('never invents a user identity or a zero value for missing portal data', () => {
    const grouped = partitionOnlineDetails([['当前服务', ''], ['IP 地址', '  '], ['账户余额', '门户未提供'], ['自定义计数', '0']]);
    expect(grouped.identity).toBeUndefined();
    expect(grouped.details.map((field) => field.value)).toEqual(['', '  ', '门户未提供', '0']);
    expect(onlineDetailKind('账户余额')).toBe('other');
  });

  it('selects decorative icons without parsing or changing field values', () => {
    const grouped = partitionOnlineDetails([['当前服务', 'raw service'], ['IPv6 地址', 'not-an-ip'], ['其他', 'raw']]);
    expect(grouped.details.map((field) => field.icon)).toEqual(['connect', 'network', 'info']);
    expect(grouped.details.map((field) => field.value)).toEqual(['raw service', 'not-an-ip', 'raw']);
  });

  it('keeps an empty response empty', () => {
    expect(partitionOnlineDetails([])).toEqual({ identity: undefined, details: [] });
  });
});

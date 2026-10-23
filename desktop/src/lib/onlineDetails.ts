export type OnlineDetailKind = 'identity' | 'service' | 'address' | 'other';

export interface OnlineDetail {
  index: number;
  name: string;
  value: string;
  kind: OnlineDetailKind;
  icon: string;
}

/** Label classification affects presentation only; never parse or replace portal values. */
export function onlineDetailKind(name: string): OnlineDetailKind {
  const label = name.trim();
  if (/^(?:账号|帐号|用户名|用户账号|用户名称|学号|校园网账号|account(?:[_ ]?id)?|username|user(?:[_ ]?id)?|login)$/i.test(label)) return 'identity';
  if (/服务|运营商|carrier|service/i.test(label)) return 'service';
  if (/地址|\b(?:ip(?:v[46])?|mac)\b|address/i.test(label)) return 'address';
  return 'other';
}

export function partitionOnlineDetails(fields: readonly (readonly [string, string])[]) {
  const entries: OnlineDetail[] = fields.map(([name, value], index) => {
    const kind = onlineDetailKind(name);
    return { index, name, value, kind, icon: { identity: 'account', service: 'connect', address: 'network', other: 'info' }[kind] };
  });
  const identity = entries.find((entry) => entry.kind === 'identity');
  return { identity, details: entries.filter((entry) => entry !== identity) };
}

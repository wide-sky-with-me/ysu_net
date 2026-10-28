export interface DebugStatus {
  state: 'off' | 'recording' | 'stopped' | 'limit' | 'error';
  file: string | null;
  bytes: number;
  records: number;
  directory_available: boolean;
  limit_bytes: number;
}

export function parseDebugStatus(value: unknown): DebugStatus {
  if (!value || typeof value !== 'object') throw new Error('调试记录状态无效');
  const v = value as Record<string, unknown>;
  if (!['off', 'recording', 'stopped', 'limit', 'error'].includes(String(v.state)) ||
      !(v.file === null || typeof v.file === 'string' && /^auth-trace-[A-Za-z0-9]{6,32}\.jsonl$/.test(v.file)) ||
      ![v.bytes, v.records, v.limit_bytes].every((n) => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0) ||
      typeof v.directory_available !== 'boolean') throw new Error('调试记录状态无效');
  return v as unknown as DebugStatus;
}

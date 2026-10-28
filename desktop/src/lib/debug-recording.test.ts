import { describe, expect, it } from 'vitest';
import { parseDebugStatus } from './debug-recording';

describe('debug recording status', () => {
  const status = { state: 'recording', file: 'auth-trace-ABC123.jsonl', bytes: 120, records: 2, directory_available: true, limit_bytes: 8 * 1024 * 1024 };
  it('accepts an active native session and a stopped session', () => {
    expect(parseDebugStatus(status).state).toBe('recording');
    expect(parseDebugStatus({ ...status, state: 'stopped' }).state).toBe('stopped');
  });
  it('rejects unknown states, paths and invalid counters', () => {
    for (const changes of [{ state: 'success' }, { file: '../config.json' }, { bytes: -1 }, { records: NaN }, { directory_available: 'true' }]) {
      expect(() => parseDebugStatus({ ...status, ...changes })).toThrow();
    }
  });
});

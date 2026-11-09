import { describe, expect, it } from 'vitest';
import { captchaProblem, captchaSummary, CAPTCHA_DOWNLOAD_FAILED, CAPTCHA_STATUS_FAILED, formatModelSize, parseCaptchaStatus } from './captcha';

const ready = { ready: true, path: '/tmp/ysu-net/captcha/common.onnx', bytes: 54088400, url: 'https://example.test/common.onnx', sha256: 'ab'.repeat(32) };

describe('captcha model status', () => {
  it('accepts the exact snapshot shape', () => {
    expect(parseCaptchaStatus(ready)).toEqual(ready);
    expect(parseCaptchaStatus({ ...ready, ready: false, path: null, bytes: 0 })).toMatchObject({ ready: false, path: null, bytes: 0 });
  });
  it('rejects an incomplete or mistyped snapshot instead of assuming readiness', () => {
    for (const value of [null, {}, { ...ready, ready: 'yes' }, { ...ready, bytes: -1 }, { ...ready, path: 7 }, { ...ready, sha256: null }])
      expect(() => parseCaptchaStatus(value)).toThrow(CAPTCHA_STATUS_FAILED);
  });
  it('describes readiness without implying the model ships with the installer', () => {
    expect(captchaSummary(null)).toContain('正在读取');
    expect(captchaSummary({ ...ready, ready: false, path: null, bytes: 0 })).toContain('人工处理');
    expect(captchaSummary(ready)).toContain('本机识别');
    expect(captchaSummary(ready)).toContain('51.6 MB');
  });
  it('formats sizes and drops an unknown one', () => {
    expect(formatModelSize(54088400)).toBe('51.6 MB');
    expect(formatModelSize(2048)).toBe('2 KB');
    expect(formatModelSize(0)).toBe('');
    expect(formatModelSize(Number.NaN)).toBe('');
  });
  it('keeps a fixed library message and falls back on an opaque one', () => {
    expect(captchaProblem('验证码模型校验失败，已丢弃')).toBe('验证码模型校验失败，已丢弃');
    expect(captchaProblem(new Error(''))).toBe(CAPTCHA_DOWNLOAD_FAILED);
    expect(captchaProblem(undefined)).toBe(CAPTCHA_DOWNLOAD_FAILED);
    expect(captchaProblem(undefined, CAPTCHA_STATUS_FAILED)).toBe(CAPTCHA_STATUS_FAILED);
  });
});

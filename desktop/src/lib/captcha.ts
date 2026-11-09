import type { CaptchaStatus } from './protocol';

export const CAPTCHA_STATUS_FAILED = '验证码模型状态读取失败。';
export const CAPTCHA_DOWNLOAD_FAILED = '验证码模型下载失败，请检查网络后重试。';
export const CAPTCHA_WEB_UNAVAILABLE = '当前为普通网页，请在桌面客户端中下载验证码模型；离线预览需明确使用 ?demo=1';

export function parseCaptchaStatus(value: unknown): CaptchaStatus {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(CAPTCHA_STATUS_FAILED);
  const data = value as Record<string, unknown>;
  if (typeof data.ready !== 'boolean' || (data.path !== null && typeof data.path !== 'string') ||
      typeof data.bytes !== 'number' || !Number.isFinite(data.bytes) || data.bytes < 0 ||
      typeof data.url !== 'string' || typeof data.sha256 !== 'string') throw new Error(CAPTCHA_STATUS_FAILED);
  return { ready: data.ready, path: data.path as string | null, bytes: data.bytes, url: data.url, sha256: data.sha256 };
}

export function formatModelSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

/** One line the settings row can show without pretending the model is bundled. */
export function captchaSummary(status: CaptchaStatus | null): string {
  if (!status) return '正在读取模型状态…';
  if (!status.ready) return '未下载，遇到验证码时仍按需人工处理';
  const size = formatModelSize(status.bytes);
  return size ? `已就绪（${size}），验证码在本机识别` : '已就绪，验证码在本机识别';
}

export function captchaProblem(error: unknown, fallback = CAPTCHA_DOWNLOAD_FAILED): string {
  const message = typeof error === 'string' ? error.trim() : error instanceof Error ? error.message.trim() : '';
  return message || fallback;
}

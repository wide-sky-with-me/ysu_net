export const ACCENT_OPTIONS = [
  { value: 'teal', label: '松石青', light: '#007b6b', dark: '#0bd8b6' },
  { value: 'blue', label: '海蓝', light: '#0969c3', dark: '#70b8ff' },
  { value: 'indigo', label: '靛蓝', light: '#3e63dd', dark: '#9eb1ff' },
  { value: 'violet', label: '紫罗兰', light: '#6e56cf', dark: '#baa7ff' },
  { value: 'rose', label: '玫瑰', light: '#cb1d63', dark: '#ff92ad' },
  { value: 'amber', label: '琥珀', light: '#a05c00', dark: '#ffca16' },
] as const;

export type Accent = (typeof ACCENT_OPTIONS)[number]['value'];

export function normalizeAccent(value: unknown): Accent {
  return ACCENT_OPTIONS.find((option) => option.value === value)?.value ?? 'teal';
}

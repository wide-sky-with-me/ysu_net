export const DEFAULT_ACCENT = 'blue' as const;

export const ACCENT_OPTIONS = [
  { value: 'blue', label: '雾蓝', light: '#3265c5', dark: '#9bbcff' },
  { value: 'teal', label: '松石青', light: '#007566', dark: '#81d5c1' },
  { value: 'indigo', label: '靛蓝', light: '#465bc7', dark: '#a8b5ff' },
  { value: 'violet', label: '紫罗兰', light: '#7153bd', dark: '#c4adf5' },
  { value: 'rose', label: '玫瑰', light: '#bb3564', dark: '#f0a2ba' },
  { value: 'amber', label: '琥珀', light: '#996020', dark: '#e3bb7a' },
] as const;

export type Accent = (typeof ACCENT_OPTIONS)[number]['value'];

export function normalizeAccent(value: unknown): Accent {
  return ACCENT_OPTIONS.find((option) => option.value === value)?.value ?? DEFAULT_ACCENT;
}

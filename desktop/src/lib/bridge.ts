import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { createDemoTransport } from './demo';
import type { CoreCommands, DesktopSettings, Transport } from './protocol';

export function selectMode(native: boolean, search: string): Transport['mode'] {
  return native ? 'desktop' : new URLSearchParams(search).get('demo') === '1' ? 'demo' : 'web';
}

export function createDesktopTransport(): Transport {
  return {
    mode: 'desktop',
    request: <C extends keyof CoreCommands>(command: C, args: CoreCommands[C]) => invoke('core_request', { command, args }),
    subscribe: (handler) => listen('core-event', (event) => handler(event.payload)),
    getDesktopSettings: () => invoke<DesktopSettings>('get_desktop_settings'),
    setAutostart: async (enabled) => { await invoke('set_autostart', { enabled }); },
    quit: async () => { await invoke('quit_app', {}); },
  };
}

export function createTransport(search = window.location.search): Transport {
  const mode = selectMode(isTauri(), search);
  if (mode === 'desktop') return createDesktopTransport();
  if (mode === 'demo') return createDemoTransport(search);
  const unavailable = async (): Promise<never> => { throw new Error('当前为普通网页，请在桌面客户端中操作；离线预览需明确使用 ?demo=1'); };
  return { mode, request: unavailable, subscribe: unavailable, getDesktopSettings: unavailable, setAutostart: unavailable, quit: unavailable };
}

import { SERVICES, rotationControl, validateAccount } from './protocol';
import { normalizeAccent } from './accents';
import packageInfo from '../../package.json';
import type { ConfigChanges, CoreCommands, DesktopSettings, PublicAccount, SaveAccount, Snapshot, Transport } from './protocol';

const DEMO_VERSION = `${packageInfo.version}-demo`;

export function demoSnapshot(search = ''): Snapshot {
  const params = new URLSearchParams(search);
  const scenario = params.get('scenario');
  const online = scenario === 'offline' || scenario === 'empty' ? false : scenario === 'unknown' ? null : true;
  const items: PublicAccount[] = scenario === 'empty' ? [] : [
    { id: 'a'.repeat(32), label: '常用账号', username: '20260001', service: '中国移动', backend: 'api', enabled: true, password_set: true, current: true },
    { id: 'b'.repeat(32), label: '备用账号', username: 'fixture-student-b', service: '中国联通', backend: 'api', enabled: true, password_set: true, current: false },
    { id: 'c'.repeat(32), label: '访客账号', username: 'fixture-guest-c', service: '校园网', backend: 'browser', enabled: false, password_set: true, current: false },
  ];
  return {
    sequence: 1,
    config: {
      username: scenario === 'empty' ? '' : '20260001', service: '中国移动', backend: 'api',
      base: 'https://auth1.ysu.edu.cn', cas_host: 'https://cer.ysu.edu.cn', verify_tls: true,
      check_interval: 15, retry_interval: 30, max_retry_interval: 900, operation_timeout: 180, password_set: scenario !== 'empty',
    },
    prefs: { theme: params.get('theme') === 'dark' ? 'dark' : params.get('theme') === 'light' ? 'light' : 'system', accent: normalizeAccent(params.get('accent')), close_to_tray: true, auto_reconnect: scenario !== 'external' && scenario !== 'no-auto', autostart_minimized: true },
    status: { online, service: online ? '中国移动' : null, user: online ? '20260001' : '', ip: online ? '10.24.16.82' : '', message: online === null ? '模拟查询超时，在线状态尚未确认' : online ? '已确认校园网连接' : '校园网尚未连接' },
    auto: { state: scenario === 'external' ? 'external' : scenario === 'no-auto' ? 'off' : 'on', message: scenario === 'external' ? '由外部后台服务管理，请先在命令行停止服务' : scenario === 'no-auto' ? '自动重连已关闭' : '正在监测连接，断线后自动登录' },
    accounts: {
      items, auto_switch: params.get('rotation') === '1', environment_override: scenario === 'environment',
      error: scenario === 'accounts-error' ? '模拟：账号簿读取失败，请检查本机文件' : '',
      quota: { state: online === true && scenario !== 'quota-unknown' ? 'available' : 'unknown', message: online === true && scenario !== 'quota-unknown' ? '门户报告剩余流量 80.00 GB' : '门户未提供可确认的剩余流量' },
      message: '',
    },
    busy: scenario === 'busy', busy_message: scenario === 'busy' ? '模拟：正在独立确认在线状态…' : '',
    info: online && !['info-error', 'info-failure', 'info-unread'].includes(scenario || '') ? { online: true,
      fields: scenario === 'online-details' ? [['账号', '20260001'], ['用户', '演示用户'], ['IP 地址', '2001:db8::42'], ['SSID', 'Campus Demo'], ['当前服务', '中国移动']] : [['账号', '20260001'], ['当前服务', '中国移动'], ['IP 地址', '10.24.16.82']],
      items: [['套餐', '中国移动校园套餐'], ['剩余流量', '80.00 GB']] } : null,
    info_error: scenario === 'info-error' ? '账户信息获取失败，请稍后重试' : '',
    logs: [
      { timestamp: '08:42:03', level: 'info', message: '离线模拟已启动；所有数据和操作均为演示' },
      { timestamp: '08:42:04', level: 'success', message: '模拟：校园网状态查询完成' },
      { timestamp: '08:42:05', level: 'info', message: '模拟：自动重连监测已开启' },
    ],
    environment: { version: DEMO_VERSION, rust: '离线演示', runtime: 'rust', platform: '离线演示', browser_available: true, browser_component_available: true },
  };
}

export function createDemoTransport(search = ''): Transport {
  const scenario = new URLSearchParams(search).get('scenario');
  let state = demoSnapshot(search);
  const handlers = new Set<(event: unknown) => void>();
  let settings: DesktopSettings = { autostart: false, tray_available: true, version: DEMO_VERSION };
  let switchTimer: ReturnType<typeof setTimeout> | undefined;
  let infoTimer: ReturnType<typeof setTimeout> | undefined;
  let nextId = 1;
  const snapshot = () => structuredClone(state);
  const publish = () => {
    state.sequence += 1;
    for (const handler of handlers) handler({ kind: 'event', name: 'snapshot', payload: snapshot() });
  };
  const log = (message: string, level: 'info' | 'error' = 'info') => { state.logs.push({ timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }), level, message: `模拟：${message}` }); state.logs = state.logs.slice(-2000); };
  const current = () => state.accounts.items.find((item) => item.current);
  const syncCurrent = () => {
    const item = current();
    if (item && item.username === state.config.username) Object.assign(item, { service: state.config.service, backend: state.config.backend, password_set: state.config.password_set });
  };
  const guardAccounts = () => {
    if (state.auto.state === 'external') throw new Error('模拟：连接由外部服务管理，请先停止后台服务');
    if (state.accounts.environment_override) throw new Error('模拟：环境变量覆盖中，账号切换已停用');
    if (state.accounts.error) throw new Error(state.accounts.error);
  };
  return {
    mode: 'demo',
    subscribe: async (handler) => { handlers.add(handler); return () => { handlers.delete(handler); }; },
    request: async <C extends keyof CoreCommands>(command: C, args: CoreCommands[C]) => {
      if (command === 'snapshot') return snapshot();
      if (command === 'action') {
        const { name, value } = args as CoreCommands['action'];
        if (state.auto.state === 'external' && ['login', 'logout', 'switch', 'set_auto', 'switch_account'].includes(name)) throw new Error('模拟：连接由外部服务管理，请先停止后台服务');
        if (name === 'info') {
          if (state.busy) throw new Error('模拟：当前任务尚未完成');
          state.busy = true; state.busy_message = '正在读取账户信息'; publish();
          infoTimer = setTimeout(() => {
            if (scenario === 'info-failure' || state.status?.online == null) {
              state.info = null; state.info_error = '账户信息获取失败，请稍后重试';
              log(state.info_error, 'error');
            } else {
              state.info = state.status.online ? { online: true, fields: [['账号', state.config.username], ['当前服务', state.status.service || '门户未提供'], ['IP 地址', state.status.ip]], items: [['套餐', '校园网络套餐'], ['剩余流量', '80.00 GB']] } : { online: false, fields: [], items: [] };
              state.info_error = ''; log('账户查询完成');
            }
            state.busy = false; state.busy_message = ''; publish();
          }, 300);
          return { accepted: true, message: '模拟：账户读取已排队' };
        }
        if (name === 'switch_account') {
          guardAccounts();
          const target = state.accounts.items.find((item) => item.id === value);
          if (state.busy) throw new Error('模拟：当前任务尚未完成');
          if (!target || target.current || !target.enabled || !target.password_set) throw new Error('模拟：请选择已启用且已保存密码的其他账号');
          if (state.status?.online === null) throw new Error('模拟：在线状态尚未确认，未执行切换');
          state.busy = true; state.busy_message = '模拟：正在切换账号并独立核验…';
          state.accounts.message = '正在确认目标账号，当前账号尚未变更';
          publish();
          // The acknowledgement deliberately precedes the authoritative completion snapshot.
          switchTimer = setTimeout(() => {
            if (scenario === 'switch-failure') {
              state.accounts.message = '模拟：目标账号登录失败，已独立确认恢复原连接';
              log('账号切换失败，当前账号保持不变', 'error');
            } else {
              for (const item of state.accounts.items) item.current = item.id === target.id;
              Object.assign(state.config, { username: target.username, service: target.service, backend: target.backend, password_set: target.password_set });
              state.status = { online: true, service: target.service, user: target.username, ip: '10.24.16.83', message: '模拟：独立查询已确认目标账号在线' };
              state.info = null; state.info_error = ''; state.accounts.quota = { state: 'unknown', message: '目标账号剩余流量待核心确认' };
              state.accounts.message = `已确认切换到${target.label || target.username}`; log('目标账号切换与核验完成');
            }
            state.busy = false; state.busy_message = ''; publish();
          }, 800);
          return { accepted: true, message: '模拟：切换已排队' };
        }
        if (['set_service', 'switch'].includes(name)) {
          if (!SERVICES.includes(value as (typeof SERVICES)[number])) throw new Error('请选择有效运营商');
          state.config.service = value as Snapshot['config']['service']; syncCurrent();
        }
        if (name === 'login' || name === 'switch') {
          if (!state.config.username || !state.config.password_set) throw new Error('模拟：请先设置账号密码');
          state.status = { online: true, service: state.config.service, user: state.config.username, ip: '10.24.16.82', message: '模拟：独立查询已确认在线' };
        }
        if (name === 'logout') {
          state.status = { online: false, service: null, user: '', ip: '', message: '模拟：已断开连接' };
          state.auto = { state: 'off', message: '自动重连已关闭' }; state.prefs.auto_reconnect = false; state.info = null; state.info_error = ''; state.accounts.auto_switch = false;
        }
        if (name === 'set_auto') {
          state.auto = { state: value ? 'on' : 'off', message: value ? '正在监测连接，断线后自动登录' : '自动重连已关闭' }; state.prefs.auto_reconnect = !!value;
          if (!value) state.accounts.auto_switch = false;
        }
        log({ login: '连接并独立查询状态完成', logout: '下线完成', switch: `已切换到${value}`, set_service: `下次连接使用${value}`, set_auto: value ? '自动重连已开启' : '自动重连已关闭', info: '账户查询完成', status: '状态查询完成' }[name]);
      } else if (command === 'save_account') {
        guardAccounts();
        const changes = args as SaveAccount;
        const error = validateAccount(changes, state.accounts.items);
        if (error) throw new Error(error);
        if (scenario === 'save-failure') throw new Error('模拟：账号保存失败，未修改账号簿');
        const item = state.accounts.items.find((account) => account.id === changes.id);
        const saved: PublicAccount = { id: item?.id && item.id !== 'current' ? item.id : (nextId++).toString(16).padStart(32, '0'), label: changes.label, username: changes.username, service: changes.service, backend: changes.backend, enabled: changes.enabled, password_set: !!changes.password || !!item?.password_set, current: !!item?.current };
        if (item) Object.assign(item, saved); else state.accounts.items.push(saved);
        if (saved.current) Object.assign(state.config, { service: saved.service, backend: saved.backend, password_set: saved.password_set });
        log('账号簿已保存');
      } else if (command === 'delete_account') {
        guardAccounts();
        const item = state.accounts.items.find((account) => account.id === (args as CoreCommands['delete_account']).id);
        if (!item || item.current) throw new Error('模拟：当前账号保留，请先切换到其他账号');
        if (scenario === 'delete-failure') throw new Error('模拟：删除失败，账号已保留');
        state.accounts.items = state.accounts.items.filter((account) => account.id !== item.id); log('账号已删除');
      } else if (command === 'rotation') {
        const { enabled } = args as CoreCommands['rotation'];
        if (enabled) {
          const control = rotationControl(state);
          if (!control.canEnable) throw new Error(control.reason);
          if (scenario === 'rotation-failure') throw new Error('模拟：轮换设置保存失败，保持关闭');
        }
        state.accounts.auto_switch = enabled;
        state.accounts.message = enabled ? '自动换号已开启，额度观测由核心处理' : '自动换号已关闭'; log(state.accounts.message);
      } else if (command === 'save_config') {
        const { password, ...changes } = args as ConfigChanges;
        const oldCurrent = current();
        state.config = { ...state.config, ...changes, password_set: password ? true : state.config.password_set };
        if (!oldCurrent || oldCurrent.username !== state.config.username) {
          if (oldCurrent) {
            if (oldCurrent.id === 'current') oldCurrent.id = (nextId++).toString(16).padStart(32, '0');
            oldCurrent.current = false;
          }
          const existing = state.accounts.items.find((item) => item.username === state.config.username);
          if (existing) existing.current = true;
          else if (state.config.username && state.config.password_set) state.accounts.items.push({ id: 'current', label: '', username: state.config.username, service: state.config.service, backend: state.config.backend, enabled: true, password_set: true, current: true });
        }
        syncCurrent(); log('配置已保存');
      } else if (command === 'save_prefs') {
        const changes = args as CoreCommands['save_prefs'];
        if ('accent' in changes && normalizeAccent(changes.accent) !== changes.accent) throw new Error('模拟：主题色值无效');
        if (scenario === 'prefs-failure') throw new Error('模拟：界面偏好保存失败，原设置已保留');
        if ('autostart_minimized' in changes && typeof changes.autostart_minimized !== 'boolean') throw new Error('模拟：启动方式值无效');
        state.prefs = { ...state.prefs, ...changes }; log('界面偏好已保存');
        publish(); return snapshot();
      } else if (command === 'diagnostics') {
        log('本地环境诊断完成'); publish();
        return { summary: '离线模拟诊断，不检查真实环境', environment: snapshot().environment };
      } else if (command === 'browser_install') {
        log('浏览器状态已刷新；原生认证不下载额外运行时');
      }
      publish();
      return { ok: true, message: '离线模拟操作完成' };
    },
    getDesktopSettings: async () => ({ ...settings }),
    setAutostart: async (enabled) => { settings = { ...settings, autostart: enabled }; log(enabled ? '开机自启已开启' : '开机自启已关闭'); publish(); },
    setStartupMode: async (minimized) => {
      if (typeof minimized !== 'boolean') throw new Error('模拟：启动方式值无效');
      if (scenario === 'prefs-failure') throw new Error('模拟：启动方式保存失败');
      state.prefs.autostart_minimized = minimized; log('启动方式已保存'); publish(); return snapshot();
    },
    quit: async () => { clearTimeout(switchTimer); clearTimeout(infoTimer); state.busy = false; state.busy_message = ''; state.auto = { state: 'off', message: '自动重连已关闭' }; state.prefs.auto_reconnect = false; state.accounts.auto_switch = false; log('退出按钮已触发（演示页面保留）'); publish(); },
  };
}

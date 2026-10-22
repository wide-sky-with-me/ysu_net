<script lang="ts">
  import { onMount, tick } from 'svelte';
  import Icon from './components/Icon.svelte';
  import Toggle from './components/Toggle.svelte';
  import Confirm from './components/Confirm.svelte';
  import SettingsTabs from './components/SettingsTabs.svelte';
  import AccentPicker from './components/AccentPicker.svelte';
  import AccountBook from './components/AccountBook.svelte';
  import { createTransport } from './lib/bridge';
  import { accountInfoState, reconnectNotice } from './lib/presentation';
  import { accountItems, advanceLogFloor, errorMessage, formatDiagnostics, formatLogTime, rotationControl, SERVICES, synchronizeSnapshots, validateConfig } from './lib/protocol';
  import type { ConfigChanges, CoreCommands, DesktopSettings, PublicAccount, PublicConfig, SaveAccount, Service, Snapshot, Theme } from './lib/protocol';

  type Page = 'connection' | 'account' | 'settings' | 'logs';
  const navigation: { id: Page; label: string; icon: string }[] = [
    { id: 'connection', label: '连接', icon: 'network' }, { id: 'account', label: '账户', icon: 'account' },
    { id: 'settings', label: '设置', icon: 'settings' }, { id: 'logs', label: '日志', icon: 'logs' },
  ];
  const transport = createTransport();
  let page = $state<Page>('connection');
  let settingsSection = $state<'account' | 'desktop' | 'authentication' | 'diagnostics'>('account');
  let snapshot = $state<Snapshot | null>(null);
  let native = $state<DesktopSettings | null>(null);
  let starting = $state(transport.mode !== 'web');
  let pending = $state(false);
  let systemDark = $state(false);
  let notice = $state<{ message: string; error: boolean } | null>(null);
  let confirmation = $state<{ title: string; message: string; confirm: string; danger?: boolean; icon?: string; run: () => void } | null>(null);
  let stop: (() => void) | undefined;
  let mounted = false;
  let accountUsername = $state('');
  let password = $state('');
  let revealPassword = $state(false);
  let accountDirty = $state(false);
  let parametersDirty = $state(false);
  let parameters = $state<PublicConfig>({ username: '', service: '校园网', backend: 'api', base: 'https://auth1.ysu.edu.cn', cas_host: 'https://cer.ysu.edu.cn', verify_tls: true, check_interval: 15, retry_interval: 30, max_retry_interval: 900, operation_timeout: 180, password_set: false });
  let diagnostic = $state('');
  let diagnosticUpdated = $state('');
  let accountBookError = $state<{ id: string; message: string } | null>(null);
  let logFilter = $state('all');
  let logSearch = $state('');
  let logFloor = $state(0);
  let previousConfig = '';
  let selectedAccount = $state('');
  let accountSelect = $state<HTMLSelectElement>();

  const online = $derived(snapshot?.status?.online === true);
  const external = $derived(snapshot?.auto.state === 'external');
  const busy = $derived(pending || !!snapshot?.busy || starting);
  const available = $derived(transport.mode !== 'web' && snapshot !== null);
  const locked = $derived(busy || !available);
  const localLocked = $derived(starting || !available);
  const accountBlocked = $derived(external || !!snapshot?.accounts.environment_override || !!snapshot?.accounts.error);
  const rotation = $derived(rotationControl(snapshot));
  const reconnectMessage = $derived(reconnectNotice(snapshot?.auto));
  const targetAccount = $derived(snapshot?.accounts.items.find((item) => item.id === selectedAccount));
  const quotaTitle = $derived(snapshot ? { unknown: '额度未知', available: '门户已提供额度', zero_reported: '门户报告剩余流量为零', unlimited: '门户报告不限量' }[snapshot.accounts.quota.state] : '额度待确认');
  const theme = $derived(snapshot?.prefs.theme || 'system');
  const accent = $derived(snapshot?.prefs.accent || 'teal');
  const actualTheme = $derived(theme === 'system' ? systemDark ? 'dark' : 'light' : theme);
  const selectedService = $derived(snapshot?.config.service);
  const statusTitle = $derived(transport.mode === 'web' ? '等待桌面核心' : starting && !snapshot ? '正在读取状态' : online ? '校园网已连接' : snapshot?.status?.online === false ? '校园网未连接' : '连接状态未知');
  const statusTone = $derived(online ? 'online' : snapshot?.status?.online === false ? 'offline' : 'unknown');
  const sidebarStatus = $derived(transport.mode === 'web' ? { label: '未连接核心', text: '待核心' }
    : online ? { label: '网络在线', text: '在线' }
    : snapshot?.status?.online === false ? { label: '网络离线', text: '离线' }
    : { label: '状态未知', text: '未知' });
  const statusDescription = $derived.by(() => {
    if (transport.mode === 'web') return '请在桌面客户端连接校园网。';
    const message = snapshot?.status?.message || '';
    // Only omit routine messages already expressed by the status heading.
    const routine = online
      ? ['已确认校园网连接', '校园网已连接', '模拟：独立查询已确认在线']
      : snapshot?.status?.online === false ? ['校园网尚未连接', '校园网未连接', '模拟：已断开连接'] : [];
    if (message) return routine.includes(message) ? '' : message;
    return starting ? '正在连接桌面核心…' : !snapshot?.status || snapshot.status.online === null ? '点击刷新重试。' : '';
  });
  const accountState = $derived(accountInfoState(snapshot));
  const items = $derived(accountItems(snapshot?.info || null));
  const logs = $derived((snapshot?.logs || []).slice(logFloor).filter((log) => (logFilter === 'all' || log.level === logFilter) && log.message.toLowerCase().includes(logSearch.toLowerCase())));
  const pageTitle = $derived(navigation.find((item) => item.id === page)?.label || '连接');
  const environment = $derived(snapshot?.environment);
  const parameterFields = [
    { key: 'check_interval', label: '在线检查间隔' },
    { key: 'retry_interval', label: '首次重试间隔' },
    { key: 'max_retry_interval', label: '最长重试间隔' },
    { key: 'operation_timeout', label: '单次操作超时' },
  ] as const;
  const hasParameterChanges = $derived(!!snapshot && (
    parameters.backend !== snapshot.config.backend || parameters.base.trim() !== snapshot.config.base ||
    parameters.cas_host.trim() !== snapshot.config.cas_host || parameters.verify_tls !== snapshot.config.verify_tls ||
    parameterFields.some(({ key }) => parameters[key] !== snapshot?.config[key])
  ));

  $effect(() => {
    document.documentElement.dataset.theme = actualTheme;
    document.documentElement.dataset.accent = accent;
    document.documentElement.style.colorScheme = actualTheme;
  });

  function receive(next: Snapshot) {
    if (!mounted) return;
    if (snapshot) logFloor = advanceLogFloor(snapshot.logs, next.logs, logFloor);
    snapshot = next;
    if (!next.accounts.items.some((item) => item.id === selectedAccount && !item.current)) selectedAccount = next.accounts.items.find((item) => item.current)?.id || '';
    const configKey = JSON.stringify(next.config);
    if (configKey !== previousConfig) {
      if (!accountDirty) accountUsername = next.config.username;
      if (!parametersDirty) parameters = { ...next.config };
      previousConfig = configKey;
    }
    if (logFloor > next.logs.length) logFloor = 0;
  }

  async function initialize() {
    if (transport.mode === 'web') return;
    starting = true;
    stop?.();
    try {
      const cleanup = await synchronizeSnapshots(transport, receive, (error) => { notice = { message: errorMessage(error), error: true }; });
      if (!mounted) { cleanup(); return; }
      stop = cleanup;
    } catch (error) { if (mounted) { snapshot = null; notice = { message: errorMessage(error), error: true }; } }
    finally { if (mounted) starting = false; }
  }

  function refreshDesktopSettings() {
    if (!mounted || transport.mode === 'web') return;
    void transport.getDesktopSettings().then((settings) => { if (mounted) native = settings; }).catch((error) => { if (mounted) notice = { message: `桌面设置读取失败：${errorMessage(error)}`, error: true }; });
  }

  onMount(() => {
    mounted = true;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    systemDark = media.matches;
    const change = (event: MediaQueryListEvent) => { systemDark = event.matches; };
    media.addEventListener('change', change);
    void initialize();
    refreshDesktopSettings();
    return () => { mounted = false; stop?.(); password = ''; media.removeEventListener('change', change); };
  });

  async function execute(job: () => Promise<unknown>, message?: string, independent = false, onerror?: (message: string) => void) {
    if (independent ? localLocked : locked) return;
    if (!independent) pending = true;
    notice = null;
    try { const result = await job(); if (message) notice = { message, error: false }; return result; }
    catch (error) { const message = errorMessage(error); if (onerror) onerror(message); else notice = { message, error: true }; }
    finally { if (!independent) pending = false; }
  }

  function action(name: CoreCommands['action']['name'], value?: string | boolean) {
    return execute(() => transport.request('action', { name, ...(value === undefined ? {} : { value }) }), undefined, name === 'set_auto' && value === false);
  }

  // The switch button disappears once the target becomes current. Focus cannot return to it while it is
  // disabled during the switch, so hand keyboard focus back to the picker instead of leaving it on <body>.
  function keepFocus(node: HTMLElement) {
    return () => { if (document.activeElement === node || document.activeElement === document.body) void tick().then(() => accountSelect?.focus({ preventScroll: true })); };
  }

  function clearPassword() { password = ''; revealPassword = false; }
  function resetScroll() { void tick().then(() => { document.getElementById('main-content')?.scrollTo({ top: 0 }); }); }

  function navigate(target: Page) {
    if (page === 'settings' && target !== 'settings') clearPassword();
    if (target === 'settings' && page !== 'settings') settingsSection = 'account';
    page = target;
    resetScroll();
    if (target === 'account' && online && !snapshot?.info?.online && !snapshot?.info_error && !locked) void action('info');
  }

  function chooseSettings(section: typeof settingsSection) {
    if (section !== 'account') clearPassword();
    settingsSection = section;
    resetScroll();
  }

  function connect() {
    if (online) {
      confirmation = { title: '断开校园网连接', message: snapshot?.auto.state === 'on' ? '下线会同时关闭自动重连。之后可随时重新连接。' : '将退出当前校园网连接，之后可随时重新连接。', confirm: '断开连接', danger: true, icon: 'power', run: () => { void action('logout'); } };
    } else if (!snapshot?.config.username || !snapshot.config.password_set) {
      navigate('settings'); notice = { message: '请先保存校园网账号和密码，再连接。', error: false };
    } else { void action('login'); }
  }

  function chooseService(service: Service) {
    if (locked || external) return;
    if (online && snapshot?.status?.service !== service) {
      confirmation = { title: `切换到${service}`, message: `将从${snapshot?.status?.service || '当前服务'}下线，再连接${service}。网络会短暂中断；新服务登录失败时，核心会尝试恢复原连接并独立确认结果。`, confirm: '确认切换', icon: 'network', run: () => { void action('switch', service); } };
    } else if (service !== selectedService) { void action('set_service', service); }
  }

  function chooseAccount() {
    const target = targetAccount;
    if (locked || accountBlocked || !target || target.current || !target.enabled || !target.password_set) return;
    confirmation = { title: `切换到${target.label || target.username}`, message: `将使用 ${target.username} 连接${target.service}。${online ? '当前连接会短暂中断；失败时核心会尝试恢复原连接。' : '核心会先确认当前网络状态，再连接目标账号。'}只有独立核验完成后才更新当前账号。`, confirm: '确认切换账号', icon: 'rotation', run: () => { void action('switch_account', target.id); } };
  }

  async function saveBookAccount(changes: SaveAccount): Promise<true | string> {
    let failure = '保存未完成，请重试。';
    const result = await execute(async () => { await transport.request('save_account', changes); return true; }, '账号簿已保存。', false, (message) => { failure = message; });
    return result === true ? true : failure;
  }

  function deleteBookAccount(item: PublicAccount) {
    if (locked || accountBlocked || item.current) return;
    clearPassword(); accountBookError = null;
    confirmation = { title: `删除${item.label || item.username}`, message: `从本机账号簿移除 ${item.username} 及其保存的凭据。`, confirm: '删除账号', danger: true, icon: 'trash', run: () => {
      void execute(() => transport.request('delete_account', { id: item.id }), undefined, false, (message) => {
        accountBookError = { id: item.id, message };
        void tick().then(() => document.getElementById('account-operation-error')?.focus());
      });
    } };
  }

  function setRotation(enabled: boolean) {
    if (enabled && (locked || !rotation.canEnable)) return;
    void execute(() => transport.request('rotation', { enabled }), undefined, !enabled);
  }

  async function saveAccount() {
    if (!snapshot) return;
    const changes: ConfigChanges = { username: accountUsername.trim(), password };
    clearPassword();
    const error = validateConfig(changes, snapshot.config);
    if (error) { notice = { message: error, error: true }; return; }
    await execute(async () => {
      await transport.request('save_config', changes);
      password = ''; revealPassword = false; accountDirty = false;
      accountUsername = snapshot?.config.username || changes.username || '';
    }, '账号已保存；密码输入已清空。');
  }

  function saveParameters() {
    if (!snapshot) return;
    const changes: ConfigChanges = { backend: parameters.backend, base: parameters.base.trim(), cas_host: parameters.cas_host.trim(), verify_tls: parameters.verify_tls, check_interval: parameters.check_interval, retry_interval: parameters.retry_interval, max_retry_interval: parameters.max_retry_interval, operation_timeout: parameters.operation_timeout };
    // Parameter-only saves do not require the account to have been configured yet.
    const error = validateConfig(changes, { ...snapshot.config, username: snapshot.config.username || 'pending', password_set: true });
    if (error) { notice = { message: error, error: true }; return; }
    const save = () => { void execute(async () => { await transport.request('save_config', changes); parametersDirty = false; if (snapshot) parameters = { ...snapshot.config }; }, '连接参数已保存，在下一轮核心操作时生效。'); };
    if (!changes.verify_tls && snapshot.config.verify_tls) confirmation = { title: '关闭 HTTPS 证书校验', message: '关闭校验后，认证时将不再验证服务器身份，账号密码可能被中间人截获。确认仅在确有必要的网络环境下使用。', confirm: '仍然关闭并保存', danger: true, run: save };
    else save();
  }

  function savePreference(changes: CoreCommands['save_prefs']) {
    void execute(() => transport.request('save_prefs', changes));
  }

  function refreshBrowser() {
    void execute(async () => { diagnostic = formatDiagnostics(await transport.request('diagnostics', {})); }, '浏览器状态已刷新。');
  }

  function runDiagnostics() {
    page = 'settings'; chooseSettings('diagnostics');
    void execute(async () => {
      diagnostic = formatDiagnostics(await transport.request('diagnostics', {}));
      diagnosticUpdated = new Date().toISOString();
      await tick();
      document.getElementById('diagnostic-result-heading')?.focus();
    });
  }

  function shortcut(event: KeyboardEvent) {
    if (confirmation) return;
    if (event.key === 'F5') { event.preventDefault(); if (available) void action(page === 'account' ? 'info' : 'status'); else if (!starting) void initialize(); }
    if ((event.ctrlKey || event.metaKey) && /^[1-4]$/.test(event.key)) { event.preventDefault(); navigate(navigation[Number(event.key) - 1].id); }
  }

  async function copyLogs() {
    try { await navigator.clipboard.writeText(logs.map((log) => `${log.timestamp}  [${log.level}] ${log.message}`).join('\n')); notice = { message: '当前筛选日志已复制。', error: false }; }
    catch (error) { notice = { message: `复制失败：${errorMessage(error)}`, error: true }; }
  }
</script>

<svelte:window onkeydown={shortcut} onfocus={refreshDesktopSettings} />

<div class="app-shell">
  <aside class="sidebar" aria-label="主导航">
    <div class="brand">
      <div class="brand-mark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4.6 4.8 12 13 19.4 4.8" />
          <path d="M12 13v6.4" />
        </svg>
      </div>
      <div class="brand-copy"><strong>YSU <em>Net</em></strong><span>燕山大学校园网</span></div>
    </div>
    <nav>
      {#each navigation as item}
        <button type="button" class:active={page === item.id} aria-current={page === item.id ? 'page' : undefined} onclick={() => navigate(item.id)} title={`${item.label}（Ctrl+${navigation.indexOf(item) + 1}）`}>
          <Icon name={item.icon} size={18} /><span>{item.label}</span>
        </button>
      {/each}
    </nav>
    <div class="sidebar-bottom">
      <div class="sidebar-status" role="status" aria-label={sidebarStatus.label} title={sidebarStatus.label}><span class={`status-dot ${statusTone}`} aria-hidden="true"></span><span>{sidebarStatus.text}</span></div>
    </div>
  </aside>

  <div class="workspace">
    {#if transport.mode === 'demo' || native?.demo}
      <div class="mode-banner" role="status"><Icon name="info" size={16} /><strong>离线模拟</strong><span>不访问校园网，不保存真实配置。</span></div>
    {:else if transport.mode === 'web'}
      <div class="mode-banner web-mode" role="status"><Icon name="info" size={16} /><strong>普通网页</strong><span>连接操作仅在桌面客户端启用。</span><a href="?demo=1">打开离线模拟</a></div>
    {/if}
    <header class="page-header">
      <h1>{pageTitle}</h1>
      {#if page === 'account'}<button type="button" class="text-button header-account-action" onclick={() => navigate('settings')}>管理账号</button>{/if}
      {#if page === 'connection' || page === 'account'}
        <button type="button" class="icon-button header-action" aria-label={page === 'account' ? '刷新账户' : '刷新状态'} title="刷新（F5）" disabled={busy || transport.mode === 'web'} onclick={() => available ? action(page === 'account' ? 'info' : 'status') : initialize()}><Icon name="refresh" size={18} /></button>
      {/if}
    </header>
    {#if notice}
      <div class:error={notice.error} class="notice" role={notice.error ? 'alert' : 'status'}><Icon name={notice.error ? 'alert' : 'check'} size={18} /><span>{notice.message}</span><button type="button" class="quiet-button" aria-label="关闭提示" onclick={() => { notice = null; }}><Icon name="close" size={16} /></button></div>
    {/if}
    {#if busy}
      <div class="busy-line" role="status"><span class="busy-mark"></span>{snapshot?.busy_message || (starting ? '正在读取核心状态…' : '正在执行，请稍候…')}</div>
    {/if}

    <main id="main-content" class:connection-page={page === 'connection'} class:log-page={page === 'logs'} class:settings-page={page === 'settings'}>
      {#if page === 'connection'}
        <div class={`connection-overview ${statusTone}`}>
          <div class="connection-context">
          <section class={`connection-state ${statusTone}`} aria-label="当前连接状态">
            <div class="connection-emblem" aria-hidden="true"><Icon name="network" size={28} /><span class={`emblem-status ${statusTone}`}></span></div>
            <div class="state-copy"><h2>{statusTitle}</h2>{#if statusDescription}<p>{statusDescription}</p>{/if}</div>
            <button type="button" class={`connection-action ${online ? 'disconnect-button' : 'primary-button'}`} disabled={locked || external} onclick={connect}><Icon name={online ? 'power' : 'connect'} size={18} />{online ? '断开连接' : '连接校园网'}</button>
          </section>
          {#if external}<p class="external-note">{snapshot?.auto.message || '后台服务正在管理此配置，请先执行 ysu stop'}</p>{/if}
          <dl class="connection-details">
            <div><dt>当前运营商</dt><dd>{online ? snapshot?.status?.service || '门户未提供' : snapshot?.status?.online === false ? '未连接' : '待核心确认'}</dd></div>
            <div><dt>{online ? '校园网账号' : '待连接账号'}</dt><dd>{online ? snapshot?.status?.user || '门户未提供' : snapshot?.config.username || '尚未设置'}{#if !snapshot?.config.username}<button type="button" class="text-button" onclick={() => navigate('settings')}>设置账号</button>{/if}</dd></div>
            <div><dt>IP 地址</dt><dd class="numeric">{online ? snapshot?.status?.ip || '门户未提供' : snapshot?.status?.online === false ? '待连接后获取' : '待核心确认'}</dd></div>
          </dl>
          <div class="connection-footer" class:unverified={Boolean(snapshot && !snapshot.config.verify_tls)}><Icon name={snapshot && !snapshot.config.verify_tls ? 'warning' : 'shield'} size={14} /><span>{!snapshot ? '认证配置待核心提供' : snapshot.config.verify_tls ? 'HTTPS 证书校验已开启' : 'HTTPS 证书校验已关闭'}</span><span class="footer-backend">{!snapshot ? '桌面核心未连接' : snapshot.config.backend === 'browser' ? '浏览器认证' : 'API 认证'}</span></div>
          </div>
        <div class="connection-automation">
        <section class="auto-section">
          <span class="automation-icon" class:active={snapshot?.auto.state === 'on'} aria-hidden="true"><Icon name="reconnect" size={18} /></span>
          <div><h2>自动重连</h2>{#if reconnectMessage}<p>{reconnectMessage}{#if snapshot?.auto.delay !== undefined && snapshot.auto.delay > 0}<span> 本轮等待 {snapshot.auto.delay} 秒。</span>{/if}</p>{/if}</div>
          <Toggle checked={snapshot?.auto.state === 'on'} disabled={localLocked || external || (busy && snapshot?.auto.state !== 'on')} label="自动重连" onchange={(value) => { void action('set_auto', value); }} />
        </section>
        <section class="auto-section rotation-section" aria-label="账号自动轮换">
          <span class="automation-icon" class:active={Boolean(snapshot?.accounts.auto_switch)} aria-hidden="true"><Icon name="rotation" size={18} /></span>
          <div><h2>自动换号</h2>{#if !external && rotation.reason}<p>{rotation.reason}</p>{/if}<p class="quota-status" role="status" aria-label="流量状态" data-state={snapshot?.accounts.quota.state || 'unknown'}>{#if snapshot?.accounts.quota.state === 'available' && snapshot.accounts.quota.message}{snapshot.accounts.quota.message}{:else}{quotaTitle}{#if snapshot?.accounts.quota.message}：{snapshot.accounts.quota.message}{/if}{#if snapshot?.accounts.quota.state === 'zero_reported'}；门户显示可能舍入，待核心复核。{/if}{/if}</p></div>
          <Toggle checked={snapshot?.accounts.auto_switch || false} disabled={localLocked || (!snapshot?.accounts.auto_switch && (pending || !rotation.canEnable))} label="自动换号" onchange={setRotation} />
        </section>
        </div>
          <div class="connection-controls">
          <section class="account-choice" aria-label="切换校园网账号">
            <div class="section-heading"><h2>连接账号</h2><button type="button" class="text-button" onclick={() => navigate('settings')}>管理账号</button></div>
            <div class="account-choice-controls"><select bind:this={accountSelect} aria-label="选择连接账号" title={targetAccount ? `${targetAccount.label ? `${targetAccount.label}（${targetAccount.username}）` : targetAccount.username}${targetAccount.current ? ' · 当前' : !targetAccount.enabled ? ' · 已停用' : !targetAccount.password_set ? ' · 待设置密码' : ''}` : undefined} value={selectedAccount} disabled={locked || accountBlocked || !snapshot?.accounts.items.length} onchange={(event) => { selectedAccount = event.currentTarget.value; }}>
              {#if !snapshot?.accounts.items.length}<option value="">尚未保存账号</option>{/if}
              {#each snapshot?.accounts.items || [] as item (item.id)}<option value={item.id} disabled={!item.current && (!item.enabled || !item.password_set)}>{item.label ? `${item.label}（${item.username}）` : item.username}{item.current ? ' · 当前' : !item.enabled ? ' · 已停用' : !item.password_set ? ' · 待设置密码' : ''}</option>{/each}
            </select>{#if targetAccount && !targetAccount.current}<button type="button" {@attach keepFocus} disabled={locked || accountBlocked || !targetAccount.enabled || !targetAccount.password_set} onclick={chooseAccount}>切换账号</button>{/if}</div>
            {#if snapshot?.accounts.error}<p class="account-error" role="alert">{snapshot.accounts.error}</p>{:else if snapshot?.accounts.environment_override}<p class="account-hint section-note">环境变量覆盖中，账号切换已停用。</p>{/if}
            {#if snapshot?.accounts.message}<p class="account-hint section-note" role="status">{snapshot.accounts.message}</p>{/if}
          </section>
        <section class="service-section">
          <div class="section-heading"><h2>运营商</h2></div>
          <div class="service-selector" role="group" aria-label="选择运营商">
            {#each SERVICES as service}
              <button type="button" class:selected={selectedService === service} aria-pressed={selectedService === service} disabled={locked || external} onclick={() => chooseService(service)}><span>{service}</span></button>
            {/each}
          </div>
        </section>
        </div>
        </div>

      {:else if page === 'account'}
        {#if accountState === 'ready' && snapshot?.info}
          <section class="account-summary"><h2>套餐与用量</h2><dl>{#each items as [name, value]}<div><dt>{name}</dt><dd class:metric={/流量|余额|用量|额度/.test(name) && /^[+-]?\d/.test(value)} class:missing={value === '门户未提供'}>{value}</dd></div>{/each}</dl></section>
          {#if items.some(([, value]) => value === '门户未提供') || snapshot.info.fields.some(([, value]) => !value.trim())}<p class="portal-note"><Icon name="info" size={16} />门户未提供的项目不代表 0 或不限量。</p>{/if}
          <section class="account-fields"><h2>在线信息</h2>{#if snapshot.info.fields.length}<dl>{#each snapshot.info.fields as [name, value]}<div><dt>{name}</dt><dd>{value.trim() ? value : '门户未提供'}</dd></div>{/each}</dl>{:else}<p class="muted">门户未提供在线信息。</p>{/if}</section>
        {:else}
          <div class="empty-state"><Icon name={accountState === 'error' ? 'alert' : 'account'} size={32} /><h2 role={accountState === 'error' ? 'alert' : undefined}>{accountState === 'error' ? snapshot?.info_error : accountState === 'offline' ? '连接后查看账户信息' : accountState === 'unknown' ? '连接状态未知' : '尚未读取账户信息'}</h2><button type="button" class="primary-button" disabled={locked} onclick={() => accountState === 'offline' ? navigate('connection') : action('info')}>{accountState === 'error' ? '重试读取账户信息' : accountState === 'offline' ? '前往连接' : '读取账户信息'}</button></div>
        {/if}

      {:else if page === 'settings'}
        <SettingsTabs selected={settingsSection} onchange={chooseSettings} />
        <div id="settings-panel" class="settings-panel" class:desktop-settings={settingsSection === 'desktop'} role="tabpanel" aria-labelledby={`settings-tab-${settingsSection}`}>
          {#if settingsSection === 'account'}
            <section class="settings-section">
              <div class="section-heading"><h2>当前账号</h2>{#if snapshot?.config.password_set}<span class="saved-indicator"><Icon name="check" size={14} />密码已保存</span>{/if}</div>
              <form onsubmit={(event) => { event.preventDefault(); void saveAccount(); }}>
                <fieldset class="current-account-form" disabled={locked}>
                  <label class="form-row"><span>账号</span><input name="username" autocomplete="off" placeholder="学号 / 工号" bind:value={accountUsername} oninput={() => { accountDirty = true; }} /></label>
                  <div class="form-row"><label for="account-password">密码</label><div class="password-control"><input id="account-password" name="password" type={revealPassword ? 'text' : 'password'} autocomplete="new-password" placeholder={snapshot?.config.password_set ? '留空保留原密码' : '请输入校园网密码'} bind:value={password} oninput={() => { accountDirty = true; }} /><button type="button" class="quiet-button" aria-label={revealPassword ? '隐藏密码' : '显示密码'} aria-pressed={revealPassword} onclick={() => { revealPassword = !revealPassword; }}><Icon name="eye" size={18} /></button></div></div>
                  <div class="form-actions"><button type="submit" class="primary-button">保存账号</button></div>
                </fieldset>
              </form>
            </section>
            <AccountBook accounts={snapshot?.accounts} locked={locked || external} lockedReason={external ? '外部后台服务正在管理，请先执行 ysu stop。' : ''} operationError={accountBookError} onsave={saveBookAccount} ondelete={deleteBookAccount} onedit={() => { clearPassword(); accountBookError = null; }} />
          {:else if settingsSection === 'desktop'}
            <section class="settings-section">
              <div class="section-heading"><h2>外观</h2></div>
              <div class="setting-row"><div><span>界面主题</span></div><div class="theme-selector" role="group" aria-label="外观">{#each [{ value: 'system', label: '系统' }, { value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }] as option}<button type="button" class:selected={theme === option.value} aria-pressed={theme === option.value} disabled={locked} onclick={() => savePreference({ theme: option.value as Theme })}>{option.label}</button>{/each}</div></div>
              <div class="setting-row accent-setting"><div><span>主题色</span></div><AccentPicker value={accent} disabled={locked} onchange={(value) => savePreference({ accent: value })} /></div>
            </section>
            <section class="settings-section">
              <div class="section-heading"><h2>启动与退出</h2></div>
              <div class="setting-row"><div><span>登录系统后自动启动</span>{#if transport.mode === 'desktop' && native?.demo}<p>离线模拟不修改系统自启。</p>{/if}</div><Toggle checked={native?.autostart || false} disabled={locked || !native || (transport.mode === 'desktop' && native.demo)} label="登录系统后自动启动" onchange={(enabled) => { void execute(async () => { await transport.setAutostart(enabled); native = await transport.getDesktopSettings(); }, '开机自启设置已保存。'); }} /></div>
              <div class="setting-row"><div><span>关闭窗口时驻留托盘</span>{#if !native?.tray_available}<p>{!native ? transport.mode === 'web' ? '请在桌面客户端设置。' : '托盘状态待确认。' : '当前环境未提供系统托盘，关闭窗口将退出应用。'}</p>{/if}</div><Toggle checked={snapshot?.prefs.close_to_tray || false} disabled={locked || !native?.tray_available} label="关闭窗口时驻留托盘" onchange={(value) => savePreference({ close_to_tray: value })} /></div>
              <div class="quit-row"><button type="button" disabled={localLocked} onclick={() => { confirmation = { title: '退出 YSU Net', message: '退出后，本客户端的自动重连将停止；当前已建立的校园网连接不会因此自动下线。', confirm: '退出应用', icon: 'exit', run: () => { void execute(() => transport.quit(), undefined, true); } }; }}><Icon name="exit" size={16} />退出应用</button></div>
            </section>
          {:else if settingsSection === 'authentication'}
            <form class="authentication-settings" onsubmit={(event) => { event.preventDefault(); saveParameters(); }}>
              <fieldset disabled={locked}>
                <section class="settings-section">
                  <div class="section-heading"><h2>认证</h2></div>
                  <label class="setting-row"><div><span>认证方式</span></div><select aria-label="认证方式" bind:value={parameters.backend} onchange={() => { parametersDirty = true; }}><option value="api">API 认证（推荐）</option><option value="browser">浏览器认证</option></select></label>
                  {#if parameters.backend === 'browser'}
                    <div class="browser-section">
                      <div class="browser-status"><Icon name="browser" size={18} /><div><strong>{!environment ? '待核心提供浏览器状态' : !environment.browser_component_available ? '当前安装未包含浏览器认证' : environment.browser_available ? '系统浏览器可用' : '未发现系统浏览器'}</strong>{#if environment && !environment.browser_component_available}<p>请使用 API 认证。</p>{:else if environment && !environment.browser_available}<p>请在本机安装 Edge 或 Chrome，再刷新状态。</p>{/if}</div></div>
                      <button type="button" disabled={locked} onclick={refreshBrowser}><Icon name="refresh" size={16} />刷新浏览器状态</button>
                    </div>
                  {/if}
                  <div class="address-fields">
                    <label class="form-row url-row"><span>门户地址</span><input type="url" bind:value={parameters.base} oninput={() => { parametersDirty = true; }} /></label>
                    <label class="form-row url-row"><span>CAS 地址</span><input type="url" bind:value={parameters.cas_host} oninput={() => { parametersDirty = true; }} /></label>
                  </div>
                  <div class="setting-row"><div><span>HTTPS 证书校验</span>{#if !parameters.verify_tls}<p class="certificate-warning">{snapshot?.config.verify_tls ? '保存后将关闭校验，需确认后生效。' : '校验已关闭，认证时不验证服务器身份。'}</p>{/if}</div><Toggle checked={parameters.verify_tls} disabled={locked} label="HTTPS 证书校验" onchange={(value) => { parameters.verify_tls = value; parametersDirty = true; }} /></div>
                </section>
                <section class="settings-section">
                  <div class="section-heading"><h2>检查与重试</h2></div>
                  <div class="parameter-grid">
                    {#each parameterFields as field}<label class="setting-row"><div><span>{field.label}</span></div><div class="number-input"><input type="number" min="1" max="86400" step="1" bind:value={parameters[field.key]} oninput={() => { parametersDirty = true; }} /><span>秒</span></div></label>{/each}
                  </div>
                </section>
                <div class="form-actions parameter-actions"><span class="muted">{hasParameterChanges ? '有未保存的修改；' : ''}保存后下次操作生效。</span><button type="submit" class="primary-button">保存参数</button></div>
              </fieldset>
            </form>
          {:else}
            <section class="settings-section diagnostics-section">
              <dl class="environment-list"><div><dt>客户端</dt><dd>YSU Net {native?.version || environment?.version || '0.2.0'}</dd></div><div><dt>认证核心</dt><dd>{environment ? `Rust 原生（${environment.rust}）` : '待核心提供'}</dd></div><div><dt>系统</dt><dd>{environment?.platform || '待核心提供'}</dd></div><div><dt>系统浏览器</dt><dd>{!environment ? '待核心提供' : environment.browser_available ? '已发现 Edge / Chrome' : '未发现 Edge / Chrome'}</dd></div></dl>
              <div class="form-actions"><button type="button" disabled={locked} onclick={runDiagnostics}><Icon name="doctor" size={16} />运行本地诊断</button></div>
              {#if diagnostic}<details class="diagnostic-result"><summary id="diagnostic-result-heading"><span>详细诊断结果</span><span class="saved-indicator" role="status">诊断已完成{#if diagnosticUpdated}<time datetime={diagnosticUpdated}>{new Date(diagnosticUpdated).toLocaleTimeString('zh-CN', { hour12: false })}</time>{/if}</span></summary><pre class="diagnostic-output" aria-label="诊断结果">{diagnostic}</pre></details>{/if}
            </section>
          {/if}
        </div>

      {:else if page === 'logs'}
        <div class="log-toolbar"><label class="search-input"><Icon name="search" size={18} /><input aria-label="搜索日志" placeholder="搜索日志内容" bind:value={logSearch} /></label><select aria-label="筛选日志级别" bind:value={logFilter}><option value="all">全部级别</option><option value="info">信息</option><option value="success">成功</option><option value="error">错误</option></select><button type="button" class="icon-button" title="复制筛选日志" aria-label="复制筛选日志" disabled={!logs.length} onclick={() => { void copyLogs(); }}><Icon name="copy" size={18} /></button><button type="button" title="仅清空当前视图，保留核心日志" disabled={!logs.length} onclick={() => { logFloor = snapshot?.logs.length || 0; }}>清空视图</button></div>
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (The scrollable log needs keyboard focus for reading.) -->
        <div class="log-list" role="log" aria-label="本次运行日志" tabindex="0">
          {#each logs as log}<div class={`log-entry ${log.level}`}><time title={log.timestamp}>{formatLogTime(log.timestamp)}</time><span class="log-level">{log.level === 'error' ? '错误' : log.level === 'success' ? '成功' : '信息'}</span><p>{log.message}</p></div>{/each}
          {#if !logs.length}<div class="log-empty"><Icon name="logs" size={28} /><p>{logSearch || logFilter !== 'all' ? '没有匹配的日志' : '当前视图暂无日志'}</p></div>{/if}
        </div>
        <p class="log-note">{logs.length} 条记录</p>
      {/if}
    </main>
  </div>
</div>

{#if confirmation}
  <Confirm title={confirmation.title} message={confirmation.message} confirm={confirmation.confirm} danger={confirmation.danger} icon={confirmation.icon} oncancel={() => { confirmation = null; }} onconfirm={() => { const run = confirmation?.run; confirmation = null; run?.(); }} />
{/if}

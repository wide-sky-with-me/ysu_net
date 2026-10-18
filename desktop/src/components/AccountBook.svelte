<script lang="ts">
  import { onDestroy, tick } from 'svelte';
  import Toggle from './Toggle.svelte';
  import { SERVICES, validateAccount } from '../lib/protocol';
  import type { Accounts, PublicAccount, SaveAccount } from '../lib/protocol';

  let { accounts, locked, lockedReason = '', operationError = null, onsave, ondelete, onedit }: {
    accounts: Accounts | undefined;
    locked: boolean;
    lockedReason?: string;
    operationError?: { id: string; message: string } | null;
    onsave: (changes: SaveAccount) => Promise<true | string>;
    ondelete: (item: PublicAccount) => void;
    onedit: () => void;
  } = $props();
  let editor = $state<Omit<SaveAccount, 'password'> | null>(null);
  let password = $state('');
  let error = $state('');
  let saving = $state(false);
  let previousFocus: Element | null = null;
  let previousAccountId: string | undefined;
  let previousScroll = 0;
  const blocked = $derived(locked || !!accounts?.environment_override || !!accounts?.error);
  const existing = $derived(accounts?.items.find((item) => item.id === editor?.id));

  function open(item?: PublicAccount) {
    onedit(); password = ''; error = '';
    previousFocus = document.activeElement;
    previousAccountId = item?.id;
    previousScroll = document.getElementById('main-content')?.scrollTop || 0;
    editor = item ? { id: item.id, label: item.label, username: item.username, service: item.service, backend: item.backend, enabled: item.enabled }
      : { label: '', username: '', service: '校园网', backend: 'api', enabled: true };
    void tick().then(() => {
      document.querySelector('.account-editor')?.scrollIntoView({ block: 'start' });
      document.getElementById('saved-account-label')?.focus({ preventScroll: true });
    });
  }
  function close() {
    password = ''; error = ''; editor = null;
    void tick().then(() => {
      const target = previousFocus instanceof HTMLElement && previousFocus.isConnected ? previousFocus
        : previousAccountId ? document.querySelector<HTMLElement>(`[data-account-id="${CSS.escape(previousAccountId)}"] .account-row-actions button`)
        : document.querySelector<HTMLElement>('.account-book > .section-heading > button');
      document.getElementById('main-content')?.scrollTo({ top: previousScroll });
      target?.focus({ preventScroll: true });
    });
  }
  async function save() {
    if (!editor || blocked || saving) return;
    const changes: SaveAccount = { ...editor, username: editor.username.trim(), label: editor.label.trim(), ...(password ? { password } : {}) };
    password = '';
    error = validateAccount(changes, accounts?.items || []) || '';
    if (error) { await tick(); document.getElementById('account-editor-error')?.focus(); return; }
    saving = true;
    try {
      const result = await onsave(changes);
      if (result === true) close();
      else { error = result; await tick(); document.getElementById('account-editor-error')?.focus(); }
    } finally { saving = false; }
  }
  onDestroy(() => { password = ''; });
</script>

<svelte:window onkeydown={(event) => { if (event.key === 'Escape' && editor && !document.querySelector('dialog[open]')) { event.preventDefault(); close(); } }} />

<section class="settings-section account-book" aria-label="账号管理">
  <div class="section-heading"><h2>{editor ? editor.id ? '编辑账号' : '新增账号' : '保存的账号'}</h2>{#if editor}<button type="button" class="text-button" aria-label="关闭账号编辑" onclick={close}>返回列表</button>{:else}<button type="button" disabled={blocked || saving} onclick={() => open()}>新增账号</button>{/if}</div>
  {#if lockedReason}<p class="section-note account-hint">{lockedReason}</p>{/if}
  {#if accounts?.error}<p class="account-error" role="alert">{accounts.error}</p>{/if}
  {#if accounts?.environment_override}<p class="section-note account-hint">环境变量覆盖中，账号簿编辑与切换已停用。</p>{/if}
  {#if !editor}
  <ul class="account-list" aria-label="保存的账号">
    {#each accounts?.items || [] as item (item.id)}
      <li class:current={item.current} data-account-id={item.id}>
        <div class="account-identity"><div><strong>{item.label || item.username}</strong>{#if item.current}<span class="inline-label">当前</span>{/if}{#if !item.enabled}<span class="inline-label idle">已停用</span>{/if}{#if !item.password_set}<span class="inline-label warning">待设置密码</span>{/if}</div><span>{item.username} · {item.service}</span></div>
        <div class="account-row-actions"><button type="button" class="quiet-button" aria-label={`编辑${item.label || item.username}`} disabled={blocked || saving} onclick={() => open(item)}>编辑</button><button type="button" class="quiet-button" aria-label={`删除${item.label || item.username}`} disabled={blocked || saving || item.current} title={item.current ? '先切换到其他账号，再删除当前账号' : undefined} onclick={() => ondelete(item)}>删除</button></div>
        {#if operationError?.id === item.id}<p id="account-operation-error" class="account-error account-row-error" role="alert" tabindex="-1">{operationError.message}</p>{/if}
      </li>
    {/each}
  </ul>
  {#if !accounts?.items.length}<p class="section-note account-hint">尚未保存其他账号。</p>{/if}
  {/if}
  {#if editor}
    <form class="account-editor" aria-label={editor.id ? '编辑保存的账号' : '新增账号'} onsubmit={(event) => { event.preventDefault(); void save(); }}>
      <fieldset class="account-editor-fields" disabled={blocked || saving}>
        <label class="form-row"><span>名称</span><input id="saved-account-label" maxlength="160" autocomplete="off" placeholder="可选，例如备用账号" bind:value={editor.label} /></label>
        <label class="form-row"><span>用户名</span><input autocomplete="off" readonly={!!editor.id} aria-describedby={editor.id ? 'fixed-username-note' : undefined} bind:value={editor.username} /></label>
        <label class="form-row"><span>账号密码</span><input name="saved-account-password" type="password" autocomplete="new-password" placeholder={existing?.password_set ? '留空保留原密码' : '请输入账号密码'} bind:value={password} /></label>
        <label class="form-row"><span>运营商</span><select aria-label="运营商" bind:value={editor.service}>{#each SERVICES as service}<option value={service}>{service}</option>{/each}</select></label>
        <label class="form-row"><span>账号认证方式</span><select aria-label="账号认证方式" bind:value={editor.backend}><option value="api">API 认证</option><option value="browser">浏览器认证</option></select></label>
        <div class="setting-row"><div><span>参与账号选择与轮换</span></div><Toggle checked={editor.enabled} disabled={blocked || saving} label="启用此账号" onchange={(value) => { if (editor) editor.enabled = value; }} /></div>
      </fieldset>
      {#if editor.id}<p id="fixed-username-note" class="section-note fixed-username-note">用户名创建后固定；更换用户请新增账号。</p>{/if}
      {#if error}<p id="account-editor-error" class="account-error" role="alert" tabindex="-1">{error}</p>{/if}
      <div class="form-actions"><div class="account-editor-actions"><button type="button" onclick={close}>取消编辑</button><button type="submit" class="primary-button" disabled={blocked || saving}>保存到账号簿</button></div></div>
    </form>
  {/if}
</section>

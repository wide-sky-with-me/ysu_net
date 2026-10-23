<script lang="ts">
  import Icon from './Icon.svelte';
  import { partitionOnlineDetails } from '../lib/onlineDetails';

  let { fields }: { fields: readonly (readonly [string, string])[] } = $props();
  const grouped = $derived(partitionOnlineDetails(fields));
</script>

<section class="account-fields" aria-labelledby="online-info-heading">
  <h2 id="online-info-heading">在线信息</h2>
  {#if fields.length}
    <div class="online-info-card" class:has-identity={!!grouped.identity && grouped.details.length > 0}>
      {#if grouped.identity}
        <div class="online-identity">
          <span class="online-identity-symbol" aria-hidden="true"><Icon name="account" size={24} /></span>
          <dl><div><dt>{grouped.identity.name}</dt><dd class:missing={!grouped.identity.value.trim()}>{grouped.identity.value.trim() ? grouped.identity.value : '门户未提供'}</dd></div></dl>
        </div>
      {/if}
      {#if grouped.details.length}
        <dl class="online-detail-list">
          {#each grouped.details as field (field.index)}
            <div class="online-detail" data-kind={field.kind}>
              <dt><span class="online-field-symbol" aria-hidden="true"><Icon name={field.icon} size={16} /></span><span>{field.name}</span></dt>
              <dd class:missing={!field.value.trim()}>{field.value.trim() ? field.value : '门户未提供'}</dd>
            </div>
          {/each}
        </dl>
      {/if}
    </div>
  {:else}
    <p class="muted online-info-empty">门户未提供在线信息。</p>
  {/if}
</section>

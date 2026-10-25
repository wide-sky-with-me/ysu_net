<script lang="ts">
  import UpdatePanel from '../lib/UpdatePanel.svelte';
  import {
    contributorSnapshot, createProjectClient, projectLinkErrorCode, projectLinkErrorMessage,
    PROJECT_CONTRIBUTORS_URL, PROJECT_RELEASES_URL, PROJECT_REPOSITORY_URL, releaseNotes,
  } from '../lib/project';
  import type { ProjectLinkError, ProjectLinkTarget, ProjectMode } from '../lib/project';

  let { mode, demo = false, busy = false, currentVersion = '' }: {
    mode: ProjectMode; demo?: boolean; busy?: boolean; currentVersion?: string;
  } = $props();
  let opening = $state<ProjectLinkTarget | null>(null);
  let error = $state<ProjectLinkError | null>(null);
  let failedTarget = $state<ProjectLinkTarget | null>(null);
  const client = $derived(createProjectClient(mode, demo));
  const canOpen = $derived(mode === 'desktop' && !demo);
  const publicUrls = { repository: PROJECT_REPOSITORY_URL, contributors: PROJECT_CONTRIBUTORS_URL, releases: PROJECT_RELEASES_URL };
  const projectLinks: { target: ProjectLinkTarget; label: string }[] = [
    { target: 'repository', label: 'GitHub 仓库' },
    { target: 'releases', label: '完整发布日志' },
  ];

  async function open(target: ProjectLinkTarget) {
    if (!canOpen || opening) return;
    opening = target;
    error = null;
    failedTarget = null;
    try { await client.openLink(target); }
    catch (value) { error = projectLinkErrorCode(value); failedTarget = target; }
    finally { opening = null; }
  }
</script>

<div class="about-content">
  <UpdatePanel {mode} {demo} {busy} {currentVersion} />

  <section class="settings-section about-project" aria-labelledby="project-heading">
    <div class="section-heading"><h2 id="project-heading">开源项目</h2></div>
    <p class="project-address">{PROJECT_REPOSITORY_URL}</p>
    <div class="project-actions">
      {#each projectLinks as link (link.target)}
        {#if mode === 'web' && !demo}
          <a class="project-link" href={publicUrls[link.target]} target="_blank" rel="noreferrer noopener">{link.label}</a>
        {:else}
          <button type="button" class="project-link" disabled={!canOpen || opening !== null} aria-busy={opening === link.target}
            title={mode === 'demo' || demo ? '离线模拟不打开外部链接' : undefined} onclick={() => { void open(link.target); }}>{link.label}</button>
        {/if}
      {/each}
    </div>
    {#if error && failedTarget}
      <p class="about-link-error" role="alert">{projectLinkErrorMessage(error)}<span class="project-address">{publicUrls[failedTarget]}</span></p>
    {/if}

    <div class="about-contributors" aria-labelledby="contributors-heading">
      <div class="contributors-heading">
        <h3 id="contributors-heading">贡献者</h3>
        <span class="muted contributor-date">名单快照 <time datetime={contributorSnapshot.verified_at}>{contributorSnapshot.verified_at.slice(0, 10)}</time></span>
      </div>
      <ul class="contributor-list" aria-label="GitHub 公开贡献者">
        {#each contributorSnapshot.contributors as contributor (contributor.login)}
          <li><span class="contributor-avatar" aria-hidden="true">{contributor.login.slice(0, 1).toUpperCase()}</span><span>{contributor.login}</span></li>
        {/each}
      </ul>
      {#if mode === 'web' && !demo}
        <a class="contributor-source" href={PROJECT_CONTRIBUTORS_URL} target="_blank" rel="noreferrer noopener">查看 GitHub 贡献者</a>
      {:else}
        <button type="button" class="text-button contributor-source" disabled={!canOpen || opening !== null}
          title={mode === 'demo' || demo ? '离线模拟不打开外部链接' : undefined} onclick={() => { void open('contributors'); }}>查看 GitHub 贡献者</button>
      {/if}
    </div>
  </section>

  <section class="settings-section about-changelog" aria-labelledby="changelog-heading">
    <div class="section-heading"><h2 id="changelog-heading">更新日志</h2></div>
    {#each releaseNotes as release (release.version)}
      <details class="about-release">
        <summary><span>{release.title}</span></summary>
        <pre>{release.body}</pre>
      </details>
    {/each}
  </section>
</div>

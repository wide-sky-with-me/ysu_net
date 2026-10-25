import { invoke } from '@tauri-apps/api/core';
import releaseNotesSource from '../../../packaging/release-notes.md?raw';
import projectInfo from './project-info.json';
import type { Transport } from './protocol';

export const PROJECT_REPOSITORY_URL = projectInfo.repository_url;
export const PROJECT_RELEASES_URL = `${PROJECT_REPOSITORY_URL}/releases`;
export const PROJECT_CONTRIBUTORS_URL = `${PROJECT_REPOSITORY_URL}/graphs/contributors`;

export interface ReleaseNote { readonly version: string; readonly title: string; readonly body: string }
export interface Contributor { readonly login: string; readonly profile_url: string; readonly type: string }
export interface ContributorSnapshot {
  readonly source_url: string;
  readonly verified_at: string;
  readonly http_status: number;
  readonly link_header: string | null;
  readonly pagination_complete: boolean;
  readonly contributors: readonly Contributor[];
}

// A dated, offline snapshot, not a live GitHub request or a claim about authorship.
export const contributorSnapshot: ContributorSnapshot = Object.freeze({
  ...projectInfo.contributor_snapshot,
  contributors: Object.freeze(projectInfo.contributor_snapshot.contributors.map((contributor) => Object.freeze({ ...contributor }))),
});

function plainReleaseText(markdown: string): string {
  // Formatting only: retain HTML and URL-looking input as inert text, never render it.
  return markdown
    .replace(/^ {0,3}#{1,6}[ \t]+/gm, '')
    .replace(/!\[([^\]\n]*)\]\([^\n)]*\)/g, '$1')
    .replace(/\[([^\]\n]+)\]\(([^\n)]+)\)/g, '$1 ($2)')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$/gm, '')
    .trim();
}

/** Parse the bundled release log into strings for escaped text interpolation, never HTML. */
export function parseReleaseNotes(markdown: string): ReleaseNote[] {
  const notes: ReleaseNote[] = [];
  let current: { version: string; title: string; lines: string[] } | undefined;
  let fence: { marker: string; length: number } | undefined;
  const finish = () => {
    if (current) notes.push({ version: current.version, title: current.title, body: plainReleaseText(current.lines.join('\n')) });
  };
  for (const line of markdown.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n')) {
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1];
    if (marker) {
      if (!fence) fence = { marker: marker[0], length: marker.length };
      else if (marker[0] === fence.marker && marker.length >= fence.length && line.trim() === marker) fence = undefined;
      current?.lines.push(line);
      continue;
    }
    const heading = !fence && /^##[ \t]+((?:YSU Net[ \t]+)?v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?))[ \t]*$/.exec(line);
    if (heading) {
      finish();
      current = { version: heading[2], title: heading[1], lines: [] };
    } else current?.lines.push(line);
  }
  finish();
  return notes;
}

// The sole release-note source is the local/tagged packaging log, not main or latest.json.notes.
export const releaseNotes: readonly ReleaseNote[] = Object.freeze(parseReleaseNotes(releaseNotesSource).map((note) => Object.freeze(note)));

export const PROJECT_LINK_TARGETS = Object.freeze(['repository', 'contributors', 'releases'] as const);
export type ProjectLinkTarget = typeof PROJECT_LINK_TARGETS[number];
export const PROJECT_LINK_ERRORS = Object.freeze(['invalid_target', 'disabled', 'manual_only', 'open_failed', 'ipc'] as const);
export type ProjectLinkError = typeof PROJECT_LINK_ERRORS[number];
export type ProjectMode = Transport['mode'];
export type ProjectInvoke = (command: 'project_open_link' | 'updater_open_releases', args?: { target: 'repository' | 'contributors' }) => Promise<unknown>;
export interface ProjectClient { openLink(target: ProjectLinkTarget): Promise<void> }
export interface ProjectClientDependencies { invoke?: ProjectInvoke }

export function projectLinkErrorCode(error: unknown): ProjectLinkError {
  return typeof error === 'string' && PROJECT_LINK_ERRORS.includes(error as ProjectLinkError) ? error as ProjectLinkError : 'ipc';
}

export function projectLinkErrorMessage(error: ProjectLinkError): string {
  const messages: Record<ProjectLinkError, string> = {
    invalid_target: '不支持的项目链接。',
    disabled: '模拟模式不打开外部浏览器。',
    manual_only: '请使用网页中的项目链接。',
    open_failed: '无法打开项目页面，请检查系统默认浏览器。',
    ipc: '打开项目页面失败，请稍后重试。',
  };
  return messages[error];
}

export function createProjectClient(mode: ProjectMode, demo = false, dependencies: ProjectClientDependencies = {}): ProjectClient {
  const nativeInvoke = dependencies.invoke ?? invoke;
  return {
    openLink: async (target) => {
      if (typeof target !== 'string' || !PROJECT_LINK_TARGETS.includes(target)) throw 'invalid_target' satisfies ProjectLinkError;
      if (mode === 'demo' || demo) throw 'disabled' satisfies ProjectLinkError;
      if (mode !== 'desktop') throw 'manual_only' satisfies ProjectLinkError;
      try {
        // Native code owns the URL allowlist. Never pass a URL, profile, command or app override.
        if (target === 'releases') await nativeInvoke('updater_open_releases');
        else await nativeInvoke('project_open_link', { target });
      } catch (error) { throw projectLinkErrorCode(error); }
    },
  };
}

export function openProjectLink(target: ProjectLinkTarget, mode: ProjectMode, demo = false): Promise<void> {
  return createProjectClient(mode, demo).openLink(target);
}

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
import releaseNotesSource from '../../../packaging/release-notes.md?raw';
import projectSource from './project.ts?raw';
import projectInfo from './project-info.json';
import packageInfo from '../../package.json';
import {
  contributorSnapshot, createProjectClient, openProjectLink, parseReleaseNotes,
  PROJECT_CONTRIBUTORS_URL, PROJECT_LINK_TARGETS, PROJECT_RELEASES_URL, PROJECT_REPOSITORY_URL,
  projectLinkErrorCode, projectLinkErrorMessage, releaseNotes,
} from './project';
import type { ProjectLinkTarget } from './project';

describe('bundled project metadata', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('derives every release entry from the sole packaging log, not an online main or feed copy', () => {
    expect(releaseNotes).toEqual(parseReleaseNotes(releaseNotesSource));
    expect(releaseNotes[0].version).toBe(packageInfo.version);
    expect(releaseNotes.map((note) => note.title)).toEqual([...releaseNotesSource.matchAll(/^## (.+)$/gm)].map((match) => match[1]));
    expect(projectSource.match(/import .+ from ['"].+release-notes\.md\?raw['"]/g)).toHaveLength(1);
    expect(Object.keys(projectInfo).sort()).toEqual(['contributor_snapshot', 'repository_url']);
    expect(Object.isFrozen(releaseNotes)).toBe(true);
    expect(releaseNotes.every(Object.isFrozen)).toBe(true);
  });

  it('parses CRLF, BOM, prerelease versions and nested sections into displayable plain text', () => {
    expect(parseReleaseNotes('\uFEFF# Log\r\n\r\n## YSU Net v1.2.3-rc.1\r\n\r\n### Fixes\r\n- **Safe** `value` and [docs](https://example.invalid/docs).\r\n\r\n## 1.2.2\r\nPrevious.')).toEqual([
      { version: '1.2.3-rc.1', title: 'YSU Net v1.2.3-rc.1', body: 'Fixes\n- Safe value and docs (https://example.invalid/docs).' },
      { version: '1.2.2', title: '1.2.2', body: 'Previous.' },
    ]);
    expect(parseReleaseNotes('No version sections.')).toEqual([]);
  });

  it('does not mistake release-like headings inside code fences for new releases', () => {
    const parsed = parseReleaseNotes('## YSU Net v1.2.3\nExample:\n```md\n## YSU Net v9.9.9\n```\nDone.\n## YSU Net v1.2.2\nEarlier.');
    expect(parsed.map((note) => note.version)).toEqual(['1.2.3', '1.2.2']);
    expect(parsed[0].body).toContain('9.9.9');
    expect(parsed[0].body).toContain('Done.');
  });

  it('keeps HTML, executable-looking URLs and image content as inert strings without execution or fetching', () => {
    const execute = vi.fn(); const fetch = vi.fn(); const open = vi.fn();
    vi.stubGlobal('executeProjectNote', execute);
    vi.stubGlobal('fetch', fetch);
    vi.stubGlobal('window', { open });
    const body = '<script>executeProjectNote()</script>\n<img src="https://example.invalid/avatar" onerror="executeProjectNote()">\n[click](javascript:executeProjectNote)\n![avatar](https://example.invalid/avatar)';
    const [note] = parseReleaseNotes(`## YSU Net v1.0.0\n${body}`);
    expect(typeof note.body).toBe('string');
    expect(Object.keys(note).sort()).toEqual(['body', 'title', 'version']);
    expect(note.body).toContain('<script>executeProjectNote()</script>');
    expect(note.body).toContain('onerror="executeProjectNote()"');
    expect(note.body).toContain('click (javascript:executeProjectNote)');
    expect(note.body).not.toContain('![avatar]');
    expect(execute).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(projectSource).not.toMatch(/innerHTML|DOMParser|\beval\s*\(/);
  });

  it('records only the verified contributor identity and dated, complete anonymous API evidence', () => {
    expect(contributorSnapshot).toEqual({
      source_url: 'https://api.github.com/repos/wide-sky-with-me/ysu_net/contributors?per_page=100&anon=false',
      verified_at: '2026-10-25T02:21:11Z', http_status: 200, link_header: null, pagination_complete: true,
      contributors: [{ login: 'wide-sky-with-me', profile_url: 'https://github.com/wide-sky-with-me', type: 'User' }],
    });
    expect(Object.isFrozen(contributorSnapshot)).toBe(true);
    expect(Object.isFrozen(contributorSnapshot.contributors)).toBe(true);
    expect(contributorSnapshot.contributors.every(Object.isFrozen)).toBe(true);
    expect(JSON.stringify(contributorSnapshot)).not.toMatch(/avatar|email|author|role/);
  });

  it('exposes fixed project, contributor and release pages without claiming main is the latest release log', () => {
    expect(PROJECT_REPOSITORY_URL).toBe('https://github.com/wide-sky-with-me/ysu_net');
    expect(PROJECT_RELEASES_URL).toBe(`${PROJECT_REPOSITORY_URL}/releases`);
    expect(PROJECT_CONTRIBUTORS_URL).toBe(`${PROJECT_REPOSITORY_URL}/graphs/contributors`);
  });
});

describe('user-initiated allowlisted project links', () => {
  beforeEach(() => vi.resetAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it('constructs without IPC and uses exact native command routing without URL arguments', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const client = createProjectClient('desktop', false, { invoke });
    expect(invoke).not.toHaveBeenCalled();
    for (const target of PROJECT_LINK_TARGETS) await client.openLink(target);
    expect(invoke.mock.calls).toEqual([
      ['project_open_link', { target: 'repository' }],
      ['project_open_link', { target: 'contributors' }],
      ['updater_open_releases'],
    ]);
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('offers the direct helper using the same native allowlist', async () => {
    for (const target of PROJECT_LINK_TARGETS) await openProjectLink(target, 'desktop');
    expect(mocks.invoke.mock.calls).toEqual([
      ['project_open_link', { target: 'repository' }],
      ['project_open_link', { target: 'contributors' }],
      ['updater_open_releases'],
    ]);
  });

  it.each([['demo', false], ['desktop', true], ['web', false], ['web', true]] as const)('%s demo=%s cannot reach native IPC, fetch or browser handoff', async (mode, demo) => {
    const invoke = vi.fn(); const fetch = vi.fn(); const open = vi.fn();
    vi.stubGlobal('fetch', fetch); vi.stubGlobal('window', { open });
    const client = createProjectClient(mode, demo, { invoke });
    for (const target of PROJECT_LINK_TARGETS) {
      const expected = mode === 'demo' || demo ? 'disabled' : 'manual_only';
      await expect(client.openLink(target)).rejects.toBe(expected);
      await expect(openProjectLink(target, mode, demo)).rejects.toBe(expected);
    }
    expect(invoke).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });

  it.each([undefined, null, '', 'Repository', 'profile', 'https://github.com/wide-sky-with-me/ysu_net', 'javascript:alert(1)', ['repository'], { target: 'repository' }, '__proto__', 'toString'])('rejects illegal target %j before any IPC', async (target) => {
    const invoke = vi.fn();
    for (const mode of ['desktop', 'demo', 'web'] as const) {
      await expect(createProjectClient(mode, false, { invoke }).openLink(target as ProjectLinkTarget)).rejects.toBe('invalid_target');
    }
    expect(invoke).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('never coerces untrusted objects into allowed targets', async () => {
    const toString = vi.fn(() => 'repository');
    await expect(createProjectClient('desktop').openLink({ toString } as unknown as ProjectLinkTarget)).rejects.toBe('invalid_target');
    expect(toString).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it('maps native failures to public codes instead of displaying raw OS paths, URLs or executable text', async () => {
    const invoke = vi.fn().mockRejectedValue('open_failed');
    const client = createProjectClient('desktop', false, { invoke });
    await expect(client.openLink('repository')).rejects.toBe('open_failed');
    const raw = new Error('private/path https://example.invalid?token=private <script>');
    invoke.mockRejectedValue(raw);
    await expect(client.openLink('contributors')).rejects.toBe('ipc');
    await expect(client.openLink('releases')).rejects.toBe('ipc');
    expect(projectLinkErrorCode(raw)).toBe('ipc');
    expect(projectLinkErrorCode('open_failed')).toBe('open_failed');
    expect(projectLinkErrorMessage(projectLinkErrorCode(raw))).not.toMatch(/private|script|example/);
    expect(projectLinkErrorMessage('open_failed')).toContain('默认浏览器');
  });
});

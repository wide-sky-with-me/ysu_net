import assert from 'node:assert/strict';
import test from 'node:test';
import { buildCommands, options, validateSources } from './desktop.mjs';

const cargo = '[package]\nname = "ysu-net"\nversion = "0.1.0"\n\n[dependencies]\ntauri = "2"\n';
const pkg = { version: '0.1.0' };
const config = { version: '0.1.0', bundle: {} };

test('desktop version is independent of Python packaging and internally consistent', () => {
  assert.equal(validateSources(pkg, config, cargo), '0.1.0');
  assert.throws(() => validateSources(pkg, { version: '0.2.0' }, cargo));
  assert.throws(() => validateSources(pkg, config, cargo.replace('version = "0.1.0"', 'version.workspace = true')));
});

test('rejects accidental reintroduction of an authentication sidecar', () => {
  assert.throws(() => validateSources(pkg, { ...config, bundle: { externalBin: ['binaries/ysu-core'] } }, cargo));
  assert.throws(() => validateSources(pkg, config, cargo + 'tauri-plugin-shell = "2"\n'));
});

test('native platform bundle plans never invoke a Python freezer or auth runtime', () => {
  for (const [platform, bundle] of [['linux', 'deb'], ['win32', 'nsis'], ['darwin', 'app,dmg']]) {
    const commands = buildCommands(options([]), platform);
    assert.equal(commands.length, 2);
    assert.deepEqual(commands[1].slice(-5), ['build', '--bundles', bundle, '--', '--locked']);
    assert.doesNotMatch(JSON.stringify(commands), /PyInstaller|ysu-core|python|playwright/i);
  }
  assert.throws(() => buildCommands(options([]), 'freebsd'));
});

test('preparation is icons only; dev and unbundled build are explicit', () => {
  assert.equal(buildCommands(options(['--prepare-only']), 'linux').length, 1);
  assert.equal(buildCommands(options(['--dev']), 'linux')[1].at(-1), 'dev');
  assert.deepEqual(buildCommands(options(['--no-bundle']), 'linux')[1].slice(-4), ['build', '--no-bundle', '--', '--locked']);
});

test('rejects contradictory flags and removed Python driver options', () => {
  assert.throws(() => options(['--dev', '--bundles', 'deb']));
  assert.throws(() => options(['--no-bundle', '--bundles', 'deb']));
  assert.throws(() => options(['--api-only']));
  assert.throws(() => options(['unrecognized']));
});

test('signed updates use only the official config override and retain the lockfile', () => {
  for (const platform of ['win32', 'darwin']) {
    const args = buildCommands(options(['--signed-update']), platform)[1];
    assert.deepEqual(JSON.parse(args[args.indexOf('--config') + 1]), { bundle: { createUpdaterArtifacts: true } });
    assert.deepEqual(args.slice(-2), ['--', '--locked']);
    assert.doesNotMatch(JSON.stringify(args), /PRIVATE_KEY|password|private-key-path/);
  }
});

test('unsigned normal builds do not request updater artifacts or a key', () => {
  assert.ok(!buildCommands(options([]), 'win32')[1].includes('--config'));
  assert.throws(() => buildCommands(options(['--signed-update']), 'linux'));
  assert.ok(buildCommands(options(['--signed-update', '--bundles', 'appimage']), 'linux')[1].includes('--config'));
});

test('signed updater builds reject non-bundle modes', () => {
  for (const flag of ['--dev', '--prepare-only', '--no-bundle']) assert.throws(() => options(['--signed-update', flag]));
});

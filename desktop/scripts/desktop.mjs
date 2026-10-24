// Decision: .agents/notes/proposals/desktop/2026-10-14-rust-desktop.md
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { spawnSync } from 'node:child_process';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const native = join(desktop, 'src-tauri');
const root = resolve(desktop, '..');
const defaults = { linux: 'deb', win32: 'nsis', darwin: 'app,dmg' };

export function options(args) {
  const { values } = parseArgs({ args, allowPositionals: false, options: {
    help: { type: 'boolean', short: 'h' },
    verbose: { type: 'boolean', short: 'v' },
    dev: { type: 'boolean' },
    'prepare-only': { type: 'boolean' },
    'no-bundle': { type: 'boolean' },
    'signed-update': { type: 'boolean' },
    bundles: { type: 'string' },
  } });
  if (values.dev && (values.bundles || values['no-bundle'])) throw new Error('开发启动不接受安装包参数');
  if (values.bundles && values['no-bundle']) throw new Error('bundles 与 no-bundle 只能选择一个');
  if (values['signed-update'] && (values.dev || values['prepare-only'] || values['no-bundle'])) throw new Error('signed-update 仅用于安装包构建');
  return values;
}

export function validateSources(pkg, config, cargo) {
  const section = cargo.match(/\[package\]([\s\S]*?)(?:\n\[|$)/)?.[1];
  const version = section?.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  if (!version || version !== pkg.version || version !== config.version) throw new Error('桌面 package.json / Cargo.toml / tauri.conf.json 版本不一致');
  if (config.bundle?.externalBin?.length || /^tauri-plugin-shell\s*=/m.test(cargo)) throw new Error('原生桌面构建仍声明旧进程旁车');
  return version;
}

export function buildCommands(values, platform = process.platform) {
  if (!defaults[platform]) throw new Error('请在 Windows、Linux 或 macOS 的原生构建环境运行');
  const cli = join(desktop, 'node_modules/@tauri-apps/cli/tauri.js');
  const commands = [[process.execPath, cli, 'icon', join(root, 'packaging/tauri-icon.svg'), '--output', join(native, 'icons')]];
  if (!values['prepare-only']) {
    const bundles = values.bundles || defaults[platform];
    if (values['signed-update'] && platform === 'linux' && !bundles.split(',').includes('appimage')) throw new Error('Linux 在线更新需要 AppImage，deb 使用手动更新');
    const signing = values['signed-update'] ? ['--config', JSON.stringify({ bundle: { createUpdaterArtifacts: true } })] : [];
    const verbosity = values.verbose ? ['--verbose'] : [];
    const args = values.dev ? ['dev', ...verbosity] : ['build', ...verbosity, ...(values['no-bundle'] ? ['--no-bundle'] : ['--bundles', bundles]), ...signing, '--', '--locked'];
    commands.push([process.execPath, cli, ...args]);
  }
  return commands;
}

function run(command) {
  const result = spawnSync(command[0], command.slice(1), { cwd: desktop, env: process.env, stdio: 'inherit' });
  if (result.error) throw new Error(`启动构建工具失败：${result.error.code || 'unknown'}`);
  if (result.status !== 0) throw new Error(`构建工具退出：${result.status ?? result.signal}`);
}

export function main(args = process.argv.slice(2)) {
  const values = options(args);
  if (values.help) {
    console.log('原生 Rust 桌面构建\n--dev              启动 Tauri 开发应用\n--prepare-only     仅校验桌面版本并生成图标\n--bundles KIND     deb / nsis / app,dmg（在对应系统运行）\n--signed-update    为安装包生成带版本绑定的更新签名，需要签名环境变量\n--verbose          显示原生构建诊断\n--no-bundle        仅构建原生程序\n构建需要 Node 与 Rust；安装后的客户端不依赖它们的命令行运行时。');
    return;
  }
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (!((major === 22 && minor >= 12) || major === 24 || major >= 26)) throw new Error('构建需要 Node 22.12、24 或 26 及更新版本');
  if (!existsSync(join(desktop, 'node_modules/@tauri-apps/cli/tauri.js'))) throw new Error('先运行 npm ci --prefix desktop 安装锁定的构建依赖');
  const pkg = JSON.parse(readFileSync(join(desktop, 'package.json'), 'utf8'));
  const config = JSON.parse(readFileSync(join(native, 'tauri.conf.json'), 'utf8'));
  const cargo = readFileSync(join(native, 'Cargo.toml'), 'utf8');
  validateSources(pkg, config, cargo);
  if (values['signed-update'] && !process.env.TAURI_SIGNING_PRIVATE_KEY) throw new Error('signed-update 需要 TAURI_SIGNING_PRIVATE_KEY');
  run(['rustc', '-vV']);
  for (const command of buildCommands(values)) run(command);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}

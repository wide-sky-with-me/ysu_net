"""Cloud-only dependency resolution inputs and PUBLIC signed delta test data.

No production key is used. The temporary test private key stays in RUNNER_TEMP,
its tool output is captured, and only the explicit public files are uploaded.
This helper never invokes Cargo itself or installs/executes a payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {
    'bzip2': 'bzip2 = "0.6"',
    'qbsdiff': 'qbsdiff = "=1.4.4"',
    'reqwest': 'reqwest = { version = "=0.13.5", default-features = false, features = ["rustls-no-provider", "stream"] }',
    'semver': 'semver = "1"',
    'sha2': 'sha2 = "0.10"',
}
PUBLIC_FILES = ('base.bin', 'base.sig', 'target.bin', 'target.sig', 'patch.bsdiff',
                'patch.sig', 'public.key', 'fixture.json')


def prepare_dependencies() -> None:
    path = ROOT / 'desktop/src-tauri/Cargo.toml'
    text = path.read_text(encoding='utf-8')
    parsed = tomllib.loads(text)
    for name, line in DEPENDENCIES.items():
        expected = tomllib.loads(line)[name]
        if name in parsed['dependencies'] and parsed['dependencies'][name] != expected:
            raise ValueError('dependency already has a different declaration: ' + name)
    additions = [line for name, line in DEPENDENCIES.items() if name not in parsed['dependencies']]
    if additions:
        anchor = '\n[target.'
        assert anchor in text
        text = text.replace(anchor, '\n' + '\n'.join(additions) + '\n' + anchor, 1)
    parsed = tomllib.loads(text)
    unix = parsed.get('target', {}).get('cfg(unix)', {}).get('dependencies', {})
    if unix.get('libc', '0.2') != '0.2':
        raise ValueError('unexpected libc declaration')
    if 'libc' not in unix:
        anchor = '\n[dev-dependencies]'
        assert anchor in text
        text = text.replace(anchor, '\n[target.\'cfg(unix)\'.dependencies]\nlibc = "0.2"\n' + anchor, 1)
    path.write_text(text, encoding='utf-8')


def checked(command: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    if result.returncode:
        # A signer error can contain key material. Never echo either captured stream.
        raise RuntimeError('public delta fixture tool failed: ' + Path(command[0]).name)


def make_public_fixture(output: Path) -> None:
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not os.environ.get('RUNNER_TEMP'):
        raise ValueError('test signing is permitted only on an Actions runner')
    output = output.resolve()
    if output != ROOT / 'desktop/src-tauri/fixtures/delta' or output.exists():
        raise ValueError('fixture output must be the fresh fixed public fixture directory')
    cli = ROOT / 'desktop/node_modules/@tauri-apps/cli/tauri.js'
    if not cli.is_file() or not shutil.which('qbsdiff') or not shutil.which('qbspatch'):
        raise ValueError('locked Tauri CLI and qbsdiff/qbspatch are required')
    output.mkdir(parents=True)
    # Plain text, deliberately not an executable installer or application archive.
    base = (b'YSU Net PUBLIC delta fixture; never execute.\n' + b'0123456789abcdef' * 8192)
    target = base.replace(b'0123456789abcdef', b'0123456789abcdeF', 7) + b'\nTARGET 2.0.0\n'
    (output / 'base.bin').write_bytes(base)
    (output / 'target.bin').write_bytes(target)
    env = os.environ.copy()
    for name in ('TAURI_SIGNING_PRIVATE_KEY', 'TAURI_SIGNING_PRIVATE_KEY_PATH', 'TAURI_SIGNING_PRIVATE_KEY_PASSWORD'):
        env.pop(name, None)
    env['CI'] = 'true'
    env['TAURI_SIGNING_PRIVATE_KEY_PASSWORD'] = ''
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve()
    with tempfile.TemporaryDirectory(prefix='ysu-delta-test-key-', dir=runner_temp) as temporary:
        private_dir = Path(temporary).resolve()
        assert private_dir.parent == runner_temp and not private_dir.is_symlink()
        key = private_dir / 'test.key'
        checked(['node', str(cli), 'signer', 'generate', '--ci', '--password', '', '--write-keys', str(key)], env)
        assert key.is_file() and not key.is_symlink()
        public = [path for path in private_dir.iterdir() if path.name.endswith('.pub')]
        assert len(public) == 1 and public[0].is_file() and not public[0].is_symlink()
        (output / 'public.key').write_bytes(public[0].read_bytes())
        checked(['qbsdiff', str(output / 'base.bin'), str(output / 'target.bin'), str(output / 'patch.bsdiff')], env)
        reconstructed = private_dir / 'reconstructed.bin'
        checked(['qbspatch', str(output / 'base.bin'), str(reconstructed), str(output / 'patch.bsdiff')], env)
        assert reconstructed.read_bytes() == target
        env['TAURI_SIGNING_PRIVATE_KEY_PATH'] = str(key)
        for name, version, destination in (('base.bin', '1.0.0', 'base.sig'),
                                           ('target.bin', '2.0.0', 'target.sig'),
                                           ('patch.bsdiff', '2.0.0', 'patch.sig')):
            path = output / name
            checked(['node', str(cli), 'signer', 'sign', '--app-version', version, str(path)], env)
            signature = Path(str(path) + '.sig')
            assert signature.is_file() and signature.stat().st_size <= 16384
            # Public signature only; retain the private key solely in TemporaryDirectory.
            (output / destination).write_bytes(signature.read_bytes())
        manifest = {
            'purpose': 'PUBLIC, non-executable signed delta test data; independent ephemeral test key',
            'base_version': '1.0.0', 'target_version': '2.0.0', 'algorithm': 'bsdiff40',
            'files': {name: {'sha256': hashlib.sha256((output / name).read_bytes()).hexdigest(),
                             'bytes': (output / name).stat().st_size}
                      for name in PUBLIC_FILES if name != 'fixture.json'},
        }
        (output / 'fixture.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Generated only public signatures, public key and non-executable fixture payloads.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-dependencies', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare_dependencies:
        prepare_dependencies()
    if args.output is not None:
        make_public_fixture(args.output)
    if not args.prepare_dependencies and args.output is None:
        parser.error('select --prepare-dependencies or --output')


if __name__ == '__main__':
    main()

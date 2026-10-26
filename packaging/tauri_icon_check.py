"""Cloud-only generated icon integrity evidence; does not render or execute payloads."""
import hashlib
import json
import os
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]


def png_size(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('generated PNG header is invalid')
    width, height = struct.unpack('>II', data[16:24])
    if not width or width != height or width > 4096:
        raise ValueError('generated PNG dimensions are invalid')
    return width


def ico_sizes(data):
    if len(data) < 6:
        raise ValueError('generated ICO header is missing')
    reserved, kind, count = struct.unpack('<HHH', data[:6])
    if reserved or kind != 1 or not 1 <= count <= 32 or len(data) < 6 + count * 16:
        raise ValueError('generated ICO directory is invalid')
    sizes = []
    for index in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        width, height = width or 256, height or 256
        if width != height or not length or offset < 6 + count * 16 or offset + length > len(data):
            raise ValueError('generated ICO image range is invalid')
        sizes.append(width)
    if not {16, 32, 256}.issubset(sizes):
        raise ValueError('generated ICO lacks required small/large sizes')
    return sizes


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('generated icon acceptance runs only in GitHub Actions')
    icons = ROOT / 'desktop/src-tauri/icons'
    results = []
    for name, expected in [('32x32.png', 32), ('128x128.png', 128), ('128x128@2x.png', 256)]:
        path = icons / name
        data = path.read_bytes()
        if path.is_symlink() or png_size(data) != expected:
            raise ValueError('generated PNG size differs from bundle configuration')
        results.append({'file': name, 'size': expected, 'sha256': hashlib.sha256(data).hexdigest()})
    ico = (icons / 'icon.ico').read_bytes()
    sizes = ico_sizes(ico)
    icns = (icons / 'icon.icns').read_bytes()
    if len(icns) < 8 or icns[:4] != b'icns' or struct.unpack('>I', icns[4:8])[0] != len(icns):
        raise ValueError('generated ICNS envelope is invalid')
    config = json.loads((ROOT / 'desktop/src-tauri/tauri.conf.json').read_text())
    nsis = config['bundle']['windows']['nsis']
    if nsis.get('installerIcon') != 'icons/icon.ico' or nsis.get('uninstallerIcon') != 'icons/icon.ico':
        raise ValueError('NSIS icons must explicitly use the generated application ICO')
    output = ROOT / 'dist/rust-desktop-icons'
    output.mkdir(parents=True, exist_ok=True)
    report = {'ok': True, 'platform': os.environ.get('RUNNER_OS'), 'sourceSha256': hashlib.sha256((ROOT / 'packaging/tauri-icon.svg').read_bytes()).hexdigest(),
              'pngs': results, 'icoSizes': sizes, 'icoSha256': hashlib.sha256(ico).hexdigest(),
              'icnsSha256': hashlib.sha256(icns).hexdigest(), 'visualReviewRequired': True, 'payloadExecuted': False}
    (output / 'generated-icons.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'ok': True, 'icoSizes': sizes, 'pngSizes': [item['size'] for item in results]}))


if __name__ == '__main__':
    main()

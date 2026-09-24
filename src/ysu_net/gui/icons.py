"""Small stroke icons rendered from inline SVG so they follow the current theme."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
                '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "logs": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".6"/>'
            '<circle cx="4.5" cy="12" r=".6"/><circle cx="4.5" cy="18" r=".6"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>',
    "power": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "wifi": '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/>'
            '<circle cx="12" cy="19.5" r=".8"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
}


def svg(name, color, stroke=2.0):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
            f'{_PATHS[name]}</svg>')


_cache = None


def svg_file(name, color):
    """Write an icon to a private temp file; style sheets can only reference files."""
    global _cache
    import atexit
    import hashlib
    import shutil
    import tempfile
    from pathlib import Path
    if _cache is None:
        _cache = Path(tempfile.mkdtemp(prefix="ysu-net-gui-"))  # 0700, unique per process
        atexit.register(shutil.rmtree, _cache, True)
    data = svg(name, color, 2.4)
    path = _cache / f"{name}-{hashlib.sha1(data.encode()).hexdigest()[:10]}.svg"
    if not path.exists():
        path.write_text(data, encoding="utf-8")
    return path.as_posix()


def render(data, size, ratio=2.0):
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(data.encode())).render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(name, color, size=20):
    return QIcon(render(svg(name, color), size))


def app_svg(dot=None):
    """Rounded tile with a Wi-Fi glyph; an optional status dot for the tray."""
    badge = (f'<circle cx="50" cy="50" r="11" fill="{dot}" stroke="#ffffff" stroke-width="4"/>' if dot else "")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#4f7cff"/><stop offset="1" stop-color="#2447c9"/></linearGradient></defs>'
        '<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#g)"/>'
        '<g fill="none" stroke="#ffffff" stroke-width="5" stroke-linecap="round">'
        '<path d="M12 27a28 28 0 0 1 40 0"/><path d="M19 34.5a18 18 0 0 1 26 0"/><path d="M26 42a8 8 0 0 1 12 0"/></g>'
        f'<circle cx="32" cy="49" r="3.4" fill="#ffffff"/>{badge}</svg>'
    )


def app_icon(dot=None):
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(render(app_svg(dot), size, 1.0))
    return result

"""Generate the OpenWrench application icon deterministically with Qt.

The repository ships source, not binary blobs, so the icon is rendered at build
time instead of being committed. Rendering is deterministic: the same Qt version
produces byte-identical PNG/ICO output, so the installer and the frozen app always
embed the same artwork. Run standalone or import build() from a packaging script.

    python scripts/make_icon.py --output-dir build/assets
"""

import argparse
from pathlib import Path
import sys

# Icon geometry, in a 256x256 design space that is scaled to every requested size.
DESIGN = 256
BACKGROUND = '#1f2937'
BACKGROUND_EDGE = '#111827'
ACCENT = '#f59e0b'
ACCENT_DARK = '#b45309'
FOREGROUND = '#f9fafb'
# Windows icon sizes; Qt writes a multi-image .ico from the largest QImage.
ICO_SIZES = (256, 128, 64, 48, 32, 16)
PNG_SIZE = 256


def _qt():
    """Import Qt lazily so the module can be inspected without a display."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
    return Qt, QColor, QFont, QImage, QPainter, QPen


def render(size=DESIGN):
    """Render the icon at one square pixel size and return a QImage."""
    Qt, QColor, QFont, QImage, QPainter, QPen = _qt()
    from PySide6.QtGui import QLinearGradient
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    scale = size / DESIGN

    # Rounded body with a subtle vertical gradient so the icon reads on light and
    # dark taskbars without a drop shadow (which Qt cannot antialias reliably here).
    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0.0, QColor(BACKGROUND))
    gradient.setColorAt(1.0, QColor(BACKGROUND_EDGE))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size, size, 48 * scale, 48 * scale)

    # A wrench silhouette drawn from a ring plus a tapered handle, the accent colour
    # reserved for the jaw so the mark stays legible at 16 px.
    pen = QPen(QColor(ACCENT), max(2.0, 26 * scale))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring_center = (96 * scale, 96 * scale)
    ring_radius = 44 * scale
    painter.drawEllipse(int(ring_center[0] - ring_radius), int(ring_center[1] - ring_radius),
                        int(ring_radius * 2), int(ring_radius * 2))
    painter.setPen(QPen(QColor(ACCENT_DARK), max(2.0, 30 * scale)))
    painter.drawLine(int(120 * scale), int(120 * scale), int(188 * scale), int(188 * scale))

    # "OW" monogram: the primary wordmark when the icon is large enough to carry it.
    if size >= 48:
        painter.setPen(QColor(FOREGROUND))
        font = QFont('DejaVu Sans')
        font.setBold(True)
        font.setPixelSize(int(74 * scale))
        painter.setFont(font)
        painter.drawText(image.rect().adjusted(0, int(28 * scale), 0, 0),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, 'OW')
    painter.end()
    return image


def _png_bytes(image):
    """PNG-encode a QImage to bytes via an in-memory QBuffer."""
    from PySide6.QtCore import QBuffer, QByteArray
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.ReadWrite)
    if not image.save(buffer, 'PNG'):
        raise RuntimeError('Could not encode PNG')
    return bytes(buffer.data())


def _write_ico(path, images):
    """Write a multi-image .ico (PNG-compressed entries, Windows Vista+ format).

    Qt's ICO writer emits a single image; Windows shell, taskbar and Start Menu each
    request a different size, so the file must carry every size explicitly.
    """
    import struct
    entries, payloads = [], []
    offset = 6 + 16 * len(images)
    for image in images:
        data = _png_bytes(image)
        width = 0 if image.width() >= 256 else image.width()
        height = 0 if image.height() >= 256 else image.height()
        entries.append(struct.pack('<BBBBHHII', width, height, 0, 0, 1, 32, len(data), offset))
        payloads.append(data)
        offset += len(data)
    header = struct.pack('<HHH', 0, 1, len(images))
    path.write_bytes(header + b''.join(entries) + b''.join(payloads))


def build(output_dir):
    """Write openwrench.png and a multi-size openwrench.ico; return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    png = output_dir / 'openwrench.png'
    ico = output_dir / 'openwrench.ico'
    # Qt's font/glyph cache is populated lazily and the first render at each pixel
    # size is not byte-identical to later ones. Render every size once and discard
    # it so the written files are reproducible across processes and machines.
    for size in (*ICO_SIZES, PNG_SIZE):
        render(size)
    master = render(PNG_SIZE)
    if not master.save(str(png), 'PNG'):
        raise RuntimeError(f'Could not write {png}')
    _write_ico(ico, [render(size) for size in ICO_SIZES])
    return png, ico


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate the OpenWrench icon')
    parser.add_argument('--output-dir', type=Path, default=Path('build/assets'))
    parser.add_argument('--sizes', type=int, nargs='*', default=None,
                        help='Extra PNG sizes to write (e.g. for Linux hicolor themes)')
    arguments = parser.parse_args(argv)
    # QImage/QPainter need a QGuiApplication; offscreen keeps this headless in CI.
    from PySide6.QtGui import QGuiApplication
    application = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    png, ico = build(arguments.output_dir)
    written = [png, ico]
    for size in arguments.sizes or ():
        extra = arguments.output_dir / f'openwrench-{size}.png'
        if not render(size).save(str(extra), 'PNG'):
            raise RuntimeError(f'Could not write {extra}')
        written.append(extra)
    print('\n'.join(str(path) for path in written))
    del application
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

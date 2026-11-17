#!/usr/bin/env python3
"""Render icons/qwkhnd-48.png and icons/qwkhnd-256.png
from icons/qwkhnd.svg.

Build-time helper, shipped in the zip: build_zip.py calls it when
the PNGs are missing, as in a fresh clone (the repo holds only the
SVG). Uses QSvgRenderer when available, else draws the same shapes
with QPainter. Verifies the PNGs by reading them back.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def render_with_svg(app):
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(
        os.path.join(ROOT, "icons", "qwkhnd.svg"))
    if not renderer.isValid():
        return False
    for size in (48, 256):
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        out = os.path.join(ROOT, "icons", "qwkhnd-%d.png" % size)
        image.save(out, "PNG")
    return True


def render_with_painter(app):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    bars = [
        (48, 64, 160, "#f2c14e"),
        (48, 118, 104, "#7fd4ff"),
        (48, 172, 56, "#ffffff"),
    ]
    for size in (48, 256):
        scale = size / 256.0
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(scale, scale)
        painter.setBrush(QColor("#14202e"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
        for x, y, width, colour in bars:
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(QRectF(x, y, width, 20), 10, 10)
        painter.end()
        out = os.path.join(ROOT, "icons", "qwkhnd-%d.png" % size)
        image.save(out, "PNG")
    return True


def main():
    from PySide6.QtGui import QGuiApplication, QImage
    svg_path = os.path.join(ROOT, "icons", "qwkhnd.svg")
    if not os.path.exists(svg_path):
        # T20: no source asset at all means the tree is broken;
        # say so plainly instead of silently drawing fallbacks.
        print("cannot render icons: %s is missing" % svg_path)
        return 1
    app = QGuiApplication(sys.argv)
    try:
        if render_with_svg(app):
            used = "svg"
        else:
            # T20: a corrupt SVG falls back to the painter, which
            # draws the same shapes. (The old code set used to
            # "painter" here without ever calling it.)
            render_with_painter(app)
            used = "painter"
    except ImportError:
        render_with_painter(app)
        used = "painter"
    ok = True
    for size in (48, 256):
        path = os.path.join(ROOT, "icons", "qwkhnd-%d.png" % size)
        if not os.path.exists(path):
            # T20: report a missing file instead of crashing on
            # os.path.getsize.
            print("%s: missing" % path)
            ok = False
            continue
        image = QImage(path)
        size_bytes = os.path.getsize(path)
        good = (not image.isNull() and image.width() == size
                and image.height() == size
                and size_bytes > 100)
        print("%s: %dx%d, %d bytes, ok=%s"
              % (path, image.width(), image.height(),
                 size_bytes, good))
        ok = ok and good
    print("renderer: %s" % used)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

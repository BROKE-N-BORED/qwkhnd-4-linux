#!/usr/bin/env python3
"""Build qwkhnd-v<version>.zip with correct stored file modes.

Scripts and launchers are stored as 0o100755 (regular file + exec
bits, so GUI extractors keep the exec bit); everything else is
0o100644. The venv, logs, and caches stay out. The version comes
from qwkhnd/__init__.py — the one place it lives.

The PNG icons are rendered from the SVG when they are missing, so
the build works from a fresh clone (the repo holds only
icons/qwkhnd.svg; the PNGs are zip-only). render_icons.py ships
in the zip for exactly that: without it, a fresh clone would have
nothing to render with.
"""

import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from qwkhnd import APP_ID, VERSION  # noqa: E402

ZIP_NAME = "%s-v%s.zip" % (APP_ID, VERSION)
PREFIX = APP_ID + "/"

EXEC_FILES = {
    "install.sh",
    "uninstall.sh",
    "run.sh",
    "Qwkhnd.desktop",
    "Install-Qwkhnd.desktop",
    "Uninstall-Qwkhnd.desktop",
}

PLAIN_FILES = [
    "build_zip.py",
    "render_icons.py",
    "requirements.txt",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    ".gitignore",
    "icons/qwkhnd.svg",
    "icons/qwkhnd-48.png",
    "icons/qwkhnd-256.png",
    "qwkhnd/__init__.py",
    "qwkhnd/__main__.py",
    "qwkhnd/app.py",
    "qwkhnd/engine.py",
    "qwkhnd/extract.py",
    "qwkhnd/debug_log.py",
    "qwkhnd/samples/sample-what-qwkhnd-does.txt",
    "qwkhnd/samples/sample-how-shorthand-works.txt",
    "qwkhnd/samples/sample-why-fewer-tokens.txt",
    "tests/__init__.py",
    "tests/fixtures.py",
    "tests/test_engine.py",
    "tests/test_extract.py",
    "tests/test_debug_log.py",
    "tests/test_gui.py",
    "tests/test_install.py",
    "tests/test_perf.py",
]


def _ensure_icons():
    """Render the PNG icons from the SVG when they are missing."""
    missing = [name for name in ("icons/qwkhnd-48.png",
                                 "icons/qwkhnd-256.png")
               if not os.path.exists(os.path.join(ROOT, name))]
    if not missing:
        return True
    print("icons missing (%s), rendering from the SVG..."
          % ", ".join(missing))
    try:
        import render_icons
    except ImportError as exc:
        print("cannot render icons: %s" % exc)
        return False
    try:
        return render_icons.main() == 0
    except Exception as exc:
        print("icon render failed: %s" % exc)
        return False


def build():
    if not _ensure_icons():
        return 1
    zip_path = os.path.join(ROOT, ZIP_NAME)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    files = [(name, 0o100755) for name in sorted(EXEC_FILES)]
    files += [(name, 0o100644) for name in PLAIN_FILES]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, mode in files:
            full = os.path.join(ROOT, name)
            if not os.path.exists(full):
                print("MISSING: %s" % name)
                return 1
            info = zipfile.ZipInfo(PREFIX + name)
            # T23: a fixed timestamp, so the same tree always
            # builds the same zip (same SHA-256).
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.create_system = 3  # Unix, so the mode bits are kept
            info.external_attr = mode << 16
            with open(full, "rb") as fh:
                zf.writestr(info, fh.read())
    # Verify stored modes.
    ok = True
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            mode = info.external_attr >> 16
            want = 0o100755 if os.path.basename(info.filename) \
                in EXEC_FILES else 0o100644
            if mode != want:
                print("BAD MODE: %s has %o, want %o"
                      % (info.filename, mode, want))
                ok = False
    size = os.path.getsize(zip_path)
    digest = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        digest.update(fh.read())
    print("built %s" % zip_path)
    print("files: %d" % len(files))
    print("size: %d bytes" % size)
    print("sha256: %s" % digest.hexdigest())
    print("modes ok: %s" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(build())

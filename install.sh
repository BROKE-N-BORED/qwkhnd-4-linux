#!/usr/bin/env bash
# Qwkhnd installer: private .venv with PySide6 + pypdf, menu icon,
# and a qwkhnd launcher. Run with BASH (never sh). No terminal is
# needed to use Qwkhnd — double-click Install-Qwkhnd instead.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Installing Qwkhnd..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed and was not found."
  exit 1
fi

# T25: Qwkhnd needs Python 3.10 or newer.
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
  echo "Qwkhnd needs Python 3.10 or newer."
  echo "This machine has: $(python3 --version 2>&1)"
  echo "Install a newer Python, then run install.sh again."
  exit 1
fi

# python3-venv missing is the common failure on a fresh Mint install:
# say exactly how to fix it instead of failing mid-venv with a
# confusing ensurepip error. This script never runs apt itself.
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  echo "python3-venv is missing."
  echo "Install it with this one command, then run install.sh again:"
  echo "  sudo apt install python3-venv"
  exit 1
fi

if [ ! -d .venv ]; then
  if ! python3 -m venv .venv; then
    echo "Creating the virtual environment failed."
    echo "On Mint this usually means python3-venv is missing:"
    echo "  sudo apt install python3-venv"
    echo "Then run install.sh again."
    exit 1
  fi
fi
# T19: pip failures get a plain-words message, not a bare abort
# under set -e (with --quiet, pip prints almost nothing itself).
if ! .venv/bin/pip install --quiet --upgrade pip; then
  echo "Updating pip failed."
  echo "This usually means no internet connection, or the Python"
  echo "package index is unreachable right now."
  echo "Check your connection and run install.sh again."
  exit 1
fi
if ! .venv/bin/pip install --quiet -r requirements.txt; then
  echo "Installing Qwkhnd's libraries failed."
  echo "This usually means no internet connection, or the Python"
  echo "package index is unreachable right now."
  echo "Check your connection and run install.sh again."
  exit 1
fi

# Fatal check: the packages must actually be present before the
# installer reports success (a silent ModuleNotFoundError behind a
# menu icon is how installs die quietly). No native libs are loaded
# here — importlib.metadata only.
if ! .venv/bin/python - <<'PYEOF'
import sys
from importlib import metadata
# NOTE: the installed distribution is PySide6-Essentials, not
# "PySide6" — metadata.version("PySide6") raises PackageNotFoundError
# even though `import PySide6` works. The full PySide6 wheel depends
# on PySide6-Essentials too, so this name is right in both cases.
missing = []
for package in ("PySide6-Essentials", "pypdf"):
    try:
        metadata.version(package)
    except metadata.PackageNotFoundError:
        missing.append(package)
if missing:
    print("Install failed: missing packages: %s" % ", ".join(missing))
    sys.exit(1)
print("Packages present: PySide6-Essentials %s, pypdf %s"
      % (metadata.version("PySide6-Essentials"),
         metadata.version("pypdf")))
PYEOF
then
  exit 1
fi

# Warning only: can the GUI actually start on this machine's system
# Qt libraries? If not, name the failure — the install itself is
# still complete, and the message says what is missing.
if ! QT_QPA_PLATFORM=offscreen .venv/bin/python -c "
from PySide6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv)
" 2>"$DIR/.gui-smoke-error.txt"; then
  echo "WARNING: the Qwkhnd window could not start here."
  echo "The install is complete, but the GUI failed its first start:"
  sed 's/^/  /' "$DIR/.gui-smoke-error.txt" | head -5
  # T19: name the actual missing library from the error, and the
  # Mint package that provides it, instead of guessing libegl1
  # and libgl1 for every failure.
  missing_lib=$(grep -o "lib[^ :]*\.so[^ :]*" \
    "$DIR/.gui-smoke-error.txt" | head -1 || true)
  package=""
  case "$missing_lib" in
    libEGL.so*) package="libegl1" ;;
    libGL.so*) package="libgl1" ;;
    libGLdispatch.so*) package="libglvnd0" ;;
    libxkbcommon-x11.so*) package="libxkbcommon-x11-0" ;;
    libxkbcommon.so*) package="libxkbcommon0" ;;
    libdbus-1.so*) package="libdbus-1-3" ;;
    libfontconfig.so*) package="libfontconfig1" ;;
    libfreetype.so*) package="libfreetype6" ;;
    libX11.so*) package="libx11-6" ;;
    libXext.so*) package="libxext6" ;;
    libXrender.so*) package="libxrender1" ;;
    libXi.so*) package="libxi6" ;;
    libSM.so*) package="libsm6" ;;
    libICE.so*) package="libice6" ;;
    libxcb-cursor.so*) package="libxcb-cursor0" ;;
    libxcb-xinerama.so*) package="libxcb-xinerama0" ;;
    libxcb-icccm.so*) package="libxcb-icccm4" ;;
    libxcb-image.so*) package="libxcb-image0" ;;
    libxcb-keysyms.so*) package="libxcb-keysyms1" ;;
    libxcb-render-util.so*) package="libxcb-render-util0" ;;
    libxcb-randr.so*) package="libxcb-randr0" ;;
    libxcb-shape.so*) package="libxcb-shape0" ;;
    libxcb-shm.so*) package="libxcb-shm0" ;;
    libxcb-sync.so*) package="libxcb-sync1" ;;
    libxcb-xfixes.so*) package="libxcb-xfixes0" ;;
    libxcb-xkb.so*) package="libxcb-xkb1" ;;
    libxcb.so*) package="libxcb1" ;;
  esac
  if [ -n "$package" ]; then
    echo "The missing library is $missing_lib."
    echo "Install it with: sudo apt install $package"
  else
    echo "This usually means a system Qt library is missing."
    echo "Try: sudo apt install libegl1 libgl1"
  fi
fi
rm -f "$DIR/.gui-smoke-error.txt"

mkdir -p "$HOME/.local/share/applications" "$HOME/.local/bin"

sed "s|__APP_DIR__|$DIR|g" Qwkhnd.desktop \
  > "$HOME/.local/share/applications/Qwkhnd.desktop"

if [ -d "$HOME/Desktop" ]; then
  cp "$HOME/.local/share/applications/Qwkhnd.desktop" \
    "$HOME/Desktop/Qwkhnd.desktop" || true
  chmod +x "$HOME/Desktop/Qwkhnd.desktop" || true
  gio set "$HOME/Desktop/Qwkhnd.desktop" metadata::trusted true \
    2>/dev/null || true
fi

{
  echo '#!/usr/bin/env bash'
  echo "exec \"$DIR/.venv/bin/python\" -m qwkhnd \"\$@\""
} > "$HOME/.local/bin/qwkhnd"
chmod +x "$HOME/.local/bin/qwkhnd"

echo "Qwkhnd installed."
echo "Start it from the Qwkhnd icon, or run: qwkhnd"
echo "If 'qwkhnd' is not found, log out and back in once."

if [ "${QWKHND_GUI_INSTALL:-}" = "1" ]; then
  read -rp "Done. Press Enter to close."
fi

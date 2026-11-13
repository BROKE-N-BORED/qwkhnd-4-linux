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
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

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
  echo "This usually means a system Qt library is missing."
  echo "Try: sudo apt install libegl1 libgl1"
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

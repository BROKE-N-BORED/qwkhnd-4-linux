#!/usr/bin/env bash
# Qwkhnd uninstaller: removes the installed app (the private
# .venv, the menu icon, the desktop copy and the qwkhnd launcher).
# Your files in ~/Qwkhnd are only removed if you say so.
# Run with BASH (never sh). No terminal is needed to use it —
# double-click Uninstall-Qwkhnd instead.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Uninstalling Qwkhnd..."

rm -rf "$DIR/.venv"
rm -f "$HOME/.local/share/applications/Qwkhnd.desktop"
rm -f "$HOME/Desktop/Qwkhnd.desktop"
rm -f "$HOME/.local/bin/qwkhnd"

if [ -d "$HOME/Qwkhnd" ]; then
  echo ""
  echo "Your Qwkhnd files (Source Material folder, dictionary,"
  echo "and logs) live in $HOME/Qwkhnd."
  read -rp "Delete them too? [y/N] " answer || true
  case "$answer" in
    y|Y|yes|YES)
      rm -rf "$HOME/Qwkhnd"
      echo "Your Qwkhnd files were deleted."
      ;;
    *)
      echo "Your Qwkhnd files were left alone."
      ;;
  esac
fi

echo ""
echo "Qwkhnd is uninstalled."
echo "You can now delete this folder: $DIR"

if [ "${QWKHND_GUI_INSTALL:-}" = "1" ]; then
  read -rp "Done. Press Enter to close." || true
fi

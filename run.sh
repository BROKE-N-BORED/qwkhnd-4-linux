#!/usr/bin/env bash
# Run Qwkhnd from its private .venv. Install first with install.sh.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -x .venv/bin/python ]; then
  echo "Qwkhnd is not installed yet."
  echo "Double-click Install-Qwkhnd, or run: bash install.sh"
  exit 1
fi

# T19: a failed start leaves its error where the user (and the
# debug report) can find it; a good start removes a stale one.
LOG_DIR="$HOME/Qwkhnd/logs"
ERROR_FILE="$LOG_DIR/startup-error.txt"
TMP_ERROR="$LOG_DIR/.startup-error.tmp"
mkdir -p "$LOG_DIR"
if ! .venv/bin/python -m qwkhnd "$@" 2>"$TMP_ERROR"; then
  {
    echo "Qwkhnd failed to start: $(date)"
    cat "$TMP_ERROR"
  } > "$ERROR_FILE"
  rm -f "$TMP_ERROR"
  echo "Qwkhnd could not start. The error was saved to:"
  echo "  $ERROR_FILE"
  exit 1
fi
rm -f "$TMP_ERROR" "$ERROR_FILE"

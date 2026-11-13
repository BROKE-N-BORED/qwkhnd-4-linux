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

exec .venv/bin/python -m qwkhnd "$@"

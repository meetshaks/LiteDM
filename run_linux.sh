#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi
if ! "$PYTHON" -c "import PySide6.QtCore, PySide6.QtWidgets, requests" 2>/dev/null; then
    printf 'Missing dependencies. Run:\n  python3 -m venv .venv\n  .venv/bin/python -m pip install -r requirements.txt\n' >&2
    exit 1
fi
cd "$ROOT"
exec "$PYTHON" main.py "$@"

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi
if ! "$PYTHON" -c "import PySide6.QtWidgets, requests, yt_dlp, PyInstaller" 2>/dev/null; then
    printf 'Build dependencies are missing. Run:\n  %s -m pip install -r requirements.txt -r requirements-dev.txt\n' "$PYTHON" >&2
    exit 1
fi
cd "$ROOT"
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --name LiteDM \
    --add-data "$ROOT/icons/5.png:icons" \
    --add-data "$ROOT/litedm-browser-extension:litedm-browser-extension" \
    --collect-all yt_dlp \
    --distpath "$ROOT/dist" \
    --workpath "$ROOT/build" \
    --specpath "$ROOT/build" \
    "$ROOT/main.py"
printf 'Built application: %s/dist/LiteDM/LiteDM\n' "$ROOT"

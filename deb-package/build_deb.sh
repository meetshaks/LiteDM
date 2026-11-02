#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$PACKAGE_DIR/.." && pwd)"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

if ! command -v dpkg-deb >/dev/null 2>&1 || ! command -v dpkg >/dev/null 2>&1; then
    printf 'Debian packaging tools are required (dpkg and dpkg-deb).\n' >&2
    exit 1
fi

if ! "$PYTHON" -c "import PySide6.QtWidgets, requests, PyInstaller" 2>/dev/null; then
    printf 'Build dependencies are missing. Run:\n  %s -m pip install -r "%s/requirements.txt" -r "%s/requirements-dev.txt"\n' \
        "$PYTHON" "$PROJECT_ROOT" "$PROJECT_ROOT" >&2
    exit 1
fi

VERSION="$(cd -- "$PROJECT_ROOT" && "$PYTHON" -c "from download_manager import __version__; print(__version__)")"
ARCH="$(dpkg --print-architecture)"
MAINTAINER="${MAINTAINER:-Local package builder <local@localhost>}"
OUTPUT="$PACKAGE_DIR/litedm_${VERSION}_${ARCH}.deb"
WORK_DIR="$(mktemp -d "$PACKAGE_DIR/.build.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --name LiteDM \
    --add-data "$PROJECT_ROOT/icons/5.png:icons" \
    --add-data "$PROJECT_ROOT/litedm-browser-extension:litedm-browser-extension" \
    --collect-all yt_dlp \
    --distpath "$WORK_DIR/dist" \
    --workpath "$WORK_DIR/build" \
    --specpath "$WORK_DIR/spec" \
    "$PROJECT_ROOT/main.py"

STAGE="$WORK_DIR/package-root"
mkdir -p \
    "$STAGE/DEBIAN" \
    "$STAGE/usr/lib/litedm" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/share/pixmaps" \
    "$STAGE/usr/share/applications"
cp -a "$WORK_DIR/dist/LiteDM" "$STAGE/usr/lib/litedm/"
install -m 644 "$PROJECT_ROOT/icons/5.png" "$STAGE/usr/share/pixmaps/litedm.png"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: litedm
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Depends: libc6, libstdc++6, libgcc-s1, libgl1, libegl1, libxcb-cursor0, libxkbcommon-x11-0
Maintainer: ${MAINTAINER}
Description: Lightweight Linux download manager
 A PySide6-based download manager with a persistent queue and resumable transfers.
EOF

cat > "$STAGE/usr/bin/litedm" <<'EOF'
#!/bin/sh
exec /usr/lib/litedm/LiteDM/LiteDM "$@"
EOF
chmod 755 "$STAGE/usr/bin/litedm"

cat > "$STAGE/usr/share/applications/litedm.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=LiteDM
Comment=Lightweight download manager
Exec=litedm
Icon=litedm
Terminal=false
Categories=Network;FileTransfer;
EOF

chmod -R go-w "$STAGE"
dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"
printf 'Built Debian package: %s\n' "$OUTPUT"

#!/usr/bin/env bash
# Installs a per-user launcher + icon (no root needed): ./install.sh [path-to-HomeLabManagement-binary-or-app.py]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin"; apps="$HOME/.local/share/applications"; icons="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$bin" "$apps" "$icons"
if [ -x "$here/HomeLabManagement" ]; then
  ln -sf "$here/HomeLabManagement" "$bin/homelab-management"
else
  [ -d "$here/.venv" ] || { python3 -m venv "$here/.venv"; "$here/.venv/bin/pip" install -q -r "$here/requirements.txt"; }
  printf '#!/bin/sh\nexec "%s/.venv/bin/python" "%s/app.py" "$@"\n' "$here" "$here" > "$bin/homelab-management"
  chmod +x "$bin/homelab-management"
fi
cp "$here/app_icon.svg" "$icons/homelab-management.svg"
# PNGs too: a stale icon-theme.cache (or a launcher that ignores scalable icons) otherwise hides the icon.
PY="$here/.venv/bin/python"; [ -x "$PY" ] || PY=python3
QT_QPA_PLATFORM=offscreen "$PY" - "$here/app_icon.svg" <<'PYEOF' || true
import os, sys
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt
app = QGuiApplication([]); r = QSvgRenderer(sys.argv[1])
for n in (16, 32, 48, 64, 128, 256, 512):
    img = QImage(n, n, QImage.Format_ARGB32); img.fill(Qt.transparent)
    p = QPainter(img); r.render(p); p.end()
    d = os.path.expanduser(f"~/.local/share/icons/hicolor/{n}x{n}/apps"); os.makedirs(d, exist_ok=True)
    img.save(f"{d}/homelab-management.png")
PYEOF
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
sed "s|^Exec=.*|Exec=$bin/homelab-management|" "$here/homelab-management.desktop" > "$apps/homelab-management.desktop"
update-desktop-database "$apps" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true
echo "Installed. Launch 'HomeLab Management' from your app menu."

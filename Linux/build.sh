#!/usr/bin/env bash
# Runs the tests, then builds dist/HomeLabManagement/ (PyInstaller one-folder) and a tar.gz.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
VERSION=$(.venv/bin/python -c "from version import __version__; print(__version__)")
rm -rf build dist
.venv/bin/pyinstaller --noconfirm --windowed --name HomeLabManagement \
  --add-data app_icon.svg:. app.py
cp homelab-management.desktop app_icon.svg dist/HomeLabManagement/
tar -C dist -czf "dist/HomeLabManagement-${VERSION}-linux-x86_64.tar.gz" HomeLabManagement
echo "Built dist/HomeLabManagement-${VERSION}-linux-x86_64.tar.gz"

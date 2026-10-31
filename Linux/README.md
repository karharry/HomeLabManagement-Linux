# HomeLab Management — Linux

A PySide6 (Qt) port of the Windows app ([HomeLabManagement-Windows](https://github.com/karharry/HomeLabManagement-Windows)),
keeping every machine kind and page, plus the **Bazzite / CachyOS** kind. See the [top-level README](../README.md).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                       # run
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests   # tests
./build.sh                                    # tests + PyInstaller tarball
```

Linux-specific modules: `prefs_autostart.py` (XDG autostart), `remote_desktop.py` (Remmina/KRDC/FreeRDP),
`gaming_session.py` + `pages_gaming.py` (Bazzite/CachyOS CPU/GPU/sensors/updates). Everything else is shared with the Windows app.

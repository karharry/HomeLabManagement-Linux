"""Preferences dialog: Open at Login / Start in tray / Start minimized. Mirrors App/SettingsPage.swift."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QCheckBox, QLabel, QMessageBox, QFormLayout,
                                 QSpinBox)

from core import store
import prefs_autostart
from version import __version__


def start_mode() -> str:
    """"tray", "minimized" or "none". Falls back to the legacy openMinimized flag (which hid to tray)."""
    m = store.pref("startMode", None)
    if m in ("tray", "minimized", "none"):
        return m
    return "tray" if store.pref("openMinimized", False) else "none"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(460, 320)
        lay = QVBoxLayout(self)

        self.login_check = QCheckBox("Open at Login")
        self.login_check.setChecked(prefs_autostart.is_enabled())
        self.login_check.toggled.connect(self._toggle_login)
        lay.addWidget(self.login_check)

        mode = start_mode()
        self.tray_check = QCheckBox("Start in tray")
        self.tray_check.setChecked(mode == "tray")
        self.minimized_check = QCheckBox("Start minimized")
        self.minimized_check.setChecked(mode == "minimized")
        # Mutually exclusive: ticking one clears the other.
        self.tray_check.toggled.connect(lambda v: self._set_mode("tray", v))
        self.minimized_check.toggled.connect(lambda v: self._set_mode("minimized", v))
        lay.addWidget(self.tray_check)
        lay.addWidget(self.minimized_check)

        note = QLabel("Start in tray hides the window until you open it from the system tray icon. "
                       "Start minimized opens the window already minimized to the taskbar. Pick one or neither.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid); font-size: 13px;")
        lay.addWidget(note)
        self.notify_check = QCheckBox("Show notifications when a machine goes offline or raises an alert")
        self.notify_check.setChecked(bool(store.pref("notifications", True)))
        self.notify_check.toggled.connect(lambda v: store.set_pref("notifications", v))
        lay.addWidget(self.notify_check)

        form = QFormLayout()
        for key, label, default, lo, hi, suffix in (
                ("alertStoragePct", "Storage alert at", 85, 50, 99, " % full"),
                ("alertMemPct", "Memory alert at", 92, 50, 99, " % used"),
                ("alertOfflineMinutes", "Offline alert after", 0, 0, 120, " min (0 = immediately)")):
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setSuffix(suffix)
            spin.setValue(int(store.pref(key, default)))
            spin.valueChanged.connect(lambda v, k=key: store.set_pref(k, v))
            form.addRow(label, spin)
        lay.addLayout(form)

        lay.addStretch(1)
        lay.addWidget(QLabel(f"HomeLab Management {__version__}"))

    def _set_mode(self, mode: str, on: bool):
        other = self.minimized_check if mode == "tray" else self.tray_check
        if on:
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        store.set_pref("startMode", mode if on else "none")

    def _toggle_login(self, enabled: bool):
        if not prefs_autostart.set_enabled(enabled):
            QMessageBox.warning(self, "Couldn't update Login setting",
                                 "Couldn't write ~/.config/autostart/homelab-management.desktop.")
            self.login_check.blockSignals(True)
            self.login_check.setChecked(prefs_autostart.is_enabled())
            self.login_check.blockSignals(False)

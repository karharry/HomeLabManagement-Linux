"""Open-at-login via an XDG autostart entry (~/.config/autostart) — the Linux equivalent of Swift's
SMAppService.mainApp (App/AppSettings.swift's LoginItem enum)."""
from __future__ import annotations

import os
import shlex
import sys

ENTRY = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                     "autostart", "homelab-management.desktop")


def _exec_command() -> str:
    if getattr(sys, "frozen", False):
        return shlex.quote(sys.executable)
    return f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(sys.argv[0]))}"


def is_enabled() -> bool:
    return os.path.exists(ENTRY)


def set_enabled(enabled: bool) -> bool:
    try:
        if enabled:
            os.makedirs(os.path.dirname(ENTRY), exist_ok=True)
            with open(ENTRY, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\nType=Application\nName=HomeLab Management\n"
                        f"Exec={_exec_command()}\nIcon=homelab-management\n"
                        "X-GNOME-Autostart-enabled=true\nTerminal=false\n")
        elif os.path.exists(ENTRY):
            os.remove(ENTRY)
        return True
    except OSError:
        return False

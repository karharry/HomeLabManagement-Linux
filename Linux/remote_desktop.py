"""RDP / Screen Sharing quick-connect. Mirrors App/RemoteDesktop.swift.

Linux has no single built-in client, so this picks the first installed one: RDP via Remmina, KRDC,
FreeRDP or GNOME Connections; VNC via Remmina, KRDC or whatever handles the vnc:// scheme. Falls back
to xdg-open for the URL scheme. Also works from inside Flatpak/toolbox via flatpak-spawn --host.
"""
from __future__ import annotations

import shutil
import subprocess

from core import Machine, MachineKind


def _first(*names: str):
    for n in names:
        if shutil.which(n):
            return n
    return None


def _spawn(cmd: list[str]):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def command_for(machine: Machine) -> list[str] | None:
    host = machine.host
    if machine.kind == MachineKind.windows:
        if shutil.which("remmina"):
            return ["remmina", "-c", f"rdp://{host}"]
        if shutil.which("krdc"):
            return ["krdc", f"rdp://{host}"]
        exe = _first("xfreerdp3", "xfreerdp", "wlfreerdp")
        if exe:
            return [exe, f"/v:{host}", "/dynamic-resolution", "+clipboard"]
        if shutil.which("gnome-connections"):
            return ["gnome-connections", f"rdp://{host}"]
        return ["xdg-open", f"rdp://{host}"]
    if machine.kind == MachineKind.macos:
        if shutil.which("remmina"):
            return ["remmina", "-c", f"vnc://{host}"]
        if shutil.which("krdc"):
            return ["krdc", f"vnc://{host}"]
        return ["xdg-open", f"vnc://{host}"]
    return None


def connect(machine: Machine):
    cmd = command_for(machine)
    if cmd:
        _spawn(cmd)

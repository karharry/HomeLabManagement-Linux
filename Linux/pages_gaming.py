"""CPU / GPU pages for Bazzite / CachyOS machines: the Windows pages plus the Linux-specific detail
(frequency scaling, boost, governor, temperatures; per-GPU clocks, fans, GTT, PCIe link)."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QHBoxLayout, QWidget

from core import Fmt
from pages_windows import WindowsCPUPage, WindowsGPUPage
from widgets_common import Card


class GamingCPUPage(WindowsCPUPage):
    def __init__(self, session, parent=None):
        super().__init__(session, parent)
        # Extra card row inserted above the per-core grid.
        self.extra_card = Card("Frequency, power & thermals")
        self.extra_labels = QLabel()
        self.extra_card.add(self.extra_labels)
        lay = self.cores_card.parentWidget().layout()
        lay.insertWidget(lay.indexOf(self.cores_card), self.extra_card)
        self._refresh()

    def _refresh(self):
        super()._refresh()
        if not hasattr(self, "extra_labels"):
            return
        i = self.session.cpu_info
        rows = []
        if getattr(i, "curMHz", 0):
            rows.append(("Average clock", f"{Fmt.mhz(i.curMHz)}" + (f" (min {Fmt.mhz(i.minMHz)} / max {Fmt.mhz(i.maxMHz)})" if i.maxMHz else "")))
        if getattr(i, "temp", None) is not None:
            rows.append(("Package temperature", Fmt.temp(i.temp)))
        if self.session.power_watts is not None:
            rows.append(("Package + GPU power", f"{self.session.power_watts:.0f} W"))
        for label, val in (("Governor", getattr(i, "governor", "")), ("Scaling driver", getattr(i, "scaling_driver", "")),
                           ("Energy preference", getattr(i, "epp", "")), ("SMT", getattr(i, "smt", "")),
                           ("Microcode", getattr(i, "microcode", ""))):
            if val:
                rows.append((label, val))
        if getattr(i, "boost", None) is not None:
            rows.append(("Boost / turbo", "Enabled" if i.boost else "Disabled"))
        if getattr(i, "l1KB", 0):
            rows.append(("L1 data cache", Fmt.bytes(i.l1KB * 1024)))
        if getattr(i, "vendor", ""):
            rows.append(("Vendor", f"{i.vendor}" + (f" · {i.sockets} socket(s)" if i.sockets else "")))
        self.extra_labels.setText("\n".join(f"{k}: {v}" for k, v in rows) or "No data yet")


class GamingGPUPage(WindowsGPUPage):
    def _adapter_widget(self, g) -> QWidget:
        w = super()._adapter_widget(g)
        details = getattr(g, "details", None)
        if details:
            card = Card("GPU details")
            if getattr(g, "vendor", ""):
                card.add(QLabel(f"Vendor: {g.vendor}" + (" (integrated)" if getattr(g, "is_integrated", False) else "")))
            for k, v in details:
                card.add(QLabel(f"{k}: {v}"))
            row = QHBoxLayout()
            row.addWidget(card)
            w.layout().addLayout(row)
        return w

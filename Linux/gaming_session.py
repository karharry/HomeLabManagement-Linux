"""Bazzite / CachyOS machines: a LinuxSession with full CPU, GPU and hardware-sensor telemetry.

Everything is read from sysfs (cpufreq, hwmon, DRM) plus lscpu/lspci/nvidia-smi, so it covers
AMD (amdgpu/k10temp/amd_pstate), Intel (i915/xe/coretemp/intel_pstate) and NVIDIA (nvidia-smi)
hardware, including hybrid iGPU+dGPU laptops and handhelds. Bazzite is an immutable rpm-ostree image
and CachyOS is a pacman distro, so updates branch on which one is detected.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from core import Machine, NavItem, sort_nav_items
from linux_session import LinuxSession, UpdateItem, _parse_pacman_updates, GPU_DETAIL_SCRIPT
from windows_session import (WinCPUInfo, CoreLoad, GPUAdapter, GPUHistory, GPUProcess, HWSensor, NVInfo,
                             _parse_nvidia)

VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}


@dataclass
class LinuxCPUInfo(WinCPUInfo):
    vendor: str = ""
    sockets: int = 0
    minMHz: float = 0
    curMHz: float = 0
    governor: str = ""
    scaling_driver: str = ""
    epp: str = ""
    boost: Optional[bool] = None
    smt: str = ""
    microcode: str = ""
    l1KB: float = 0
    temp: Optional[float] = None
    package_watts: Optional[float] = None
    flags: set = field(default_factory=set)


@dataclass
class LinuxGPU(GPUAdapter):
    vendor: str = ""
    slot: str = ""
    card: str = ""
    details: list = field(default_factory=list)  # (label, value) rows shown on the GPU page
    gtt_total: Optional[float] = None
    gtt_used: Optional[float] = None
    is_integrated: bool = False


# ---------------------------------------------------------------------------
# Remote script
# ---------------------------------------------------------------------------

HW_SCRIPT = r"""
echo '##OSREL'
cat /etc/os-release 2>/dev/null
[ -e /run/ostree-booted ] && echo 'OSTREE=1'
echo '##CPUCAP'
lscpu 2>/dev/null
awk -F': ' '/^microcode/{print "microcode: "$2; exit}' /proc/cpuinfo
echo '##CPUFREQ'
for c in /sys/devices/system/cpu/cpu[0-9]*; do
  echo "${c##*/} $(cat $c/cpufreq/scaling_cur_freq 2>/dev/null)"
done
echo '##CPUPOL'
p=/sys/devices/system/cpu/cpu0/cpufreq
echo "governor=$(cat $p/scaling_governor 2>/dev/null)"
echo "driver=$(cat $p/scaling_driver 2>/dev/null)"
echo "epp=$(cat $p/energy_performance_preference 2>/dev/null)"
echo "min=$(cat $p/cpuinfo_min_freq 2>/dev/null)"
echo "max=$(cat $p/cpuinfo_max_freq 2>/dev/null)"
echo "boost=$(cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null)"
echo "no_turbo=$(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null)"
echo "smt=$(cat /sys/devices/system/cpu/smt/control 2>/dev/null)"
echo '##HWMON'
for h in /sys/class/hwmon/hwmon*; do
  name=$(cat $h/name 2>/dev/null)
  dev=$(basename "$(readlink -f $h/device 2>/dev/null)")
  for f in $h/temp*_input $h/fan*_input $h/power*_average $h/power*_input $h/in*_input $h/freq*_input; do
    [ -r "$f" ] || continue
    b=${f##*/}; pre=${b%_*}
    lbl=$(cat $h/${pre}_label 2>/dev/null)
    v=$(cat $f 2>/dev/null) || continue
    echo "$name|$dev|$b|$lbl|$v"
  done
done
echo '##GPU'
for c in /sys/class/drm/card[0-9]*; do
  case "${c##*/}" in *-*) continue;; esac
  d=$c/device
  [ -r $d/vendor ] || continue
  slot=$(basename "$(readlink -f $d)")
  echo "CARD|${c##*/}|$slot|$(cat $d/vendor)|$(cat $d/device)|$(basename "$(readlink -f $d/driver 2>/dev/null)")"
  for k in gpu_busy_percent mem_busy_percent mem_info_vram_used mem_info_vram_total mem_info_gtt_used mem_info_gtt_total \
           current_link_speed current_link_width power_dpm_force_performance_level; do
    [ -r $d/$k ] && echo "ATTR|$k|$(cat $d/$k 2>/dev/null)"
  done
  for k in gt_cur_freq_mhz gt_act_freq_mhz gt_max_freq_mhz gt_min_freq_mhz gt_boost_freq_mhz; do
    [ -r $c/$k ] && echo "ATTR|$k|$(cat $c/$k 2>/dev/null)"
  done
  [ -r $d/tile0/gt0/freq0/cur_freq ] && echo "ATTR|gt_cur_freq_mhz|$(cat $d/tile0/gt0/freq0/cur_freq)"
  [ -r $d/tile0/gt0/freq0/max_freq ] && echo "ATTR|gt_max_freq_mhz|$(cat $d/tile0/gt0/freq0/max_freq)"
  for k in pp_dpm_sclk pp_dpm_mclk; do
    [ -r $d/$k ] && echo "ATTR|$k|$(grep '\*' $d/$k 2>/dev/null | head -1)"
  done
  for hw in $d/hwmon/hwmon*; do
    [ -d "$hw" ] || continue
    for f in $hw/temp*_input $hw/power*_average $hw/power*_input $hw/power*_cap $hw/fan*_input $hw/fan*_max $hw/pwm1 $hw/pwm1_max $hw/freq*_input $hw/in0_input; do
      [ -r "$f" ] || continue
      b=${f##*/}; pre=${b%_*}
      echo "HW|$b|$(cat $hw/${pre}_label 2>/dev/null)|$(cat $f 2>/dev/null)"
    done
  done
  echo "NAME|$(lspci -s "$slot" -vmm 2>/dev/null | awk -F'\t' '/^Device:/{print $2; exit}')|$(lspci -s "$slot" -vmm 2>/dev/null | awk -F'\t' '/^Vendor:/{print $2; exit}')"
  echo "END"
done
echo '##NVIDIA'
command -v nvidia-smi >/dev/null 2>&1 && {
  nvidia-smi --query-gpu=index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr,clocks.max.gr,clocks.mem,clocks.max.mem,driver_version,pstate --format=csv,noheader,nounits 2>/dev/null
  echo '##NVBUS'
  nvidia-smi --query-gpu=index,pci.bus_id --format=csv,noheader 2>/dev/null
}
"""

# Per-process GPU use: DRM fdinfo (AMD/Intel, own processes unless root) and nvidia-smi pmon.
# Only run while the GPU page is open, since walking /proc/*/fdinfo is the costly part.
GPU_PROC_SCRIPT = r"""
echo '##DRMPROC'
grep -s -H -E '^(drm-driver|drm-client-id|drm-memory-vram|drm-total-vram0|drm-total-local0|drm-resident-vram0|drm-engine-gfx|drm-engine-render):' /proc/[0-9]*/fdinfo/* 2>/dev/null
echo '##PS'
ps -eo pid=,comm= 2>/dev/null
echo '##NVPMON'
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi pmon -c 1 -s um 2>/dev/null
"""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _split_sections(text: str) -> dict[str, list[str]]:
    sec: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("##"):
            cur = line[2:].strip()
            sec[cur] = []
        elif cur is not None:
            sec[cur].append(line)
    return sec


def _num(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


_SIZE_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}


def _cache_kb(value: str) -> float:
    """lscpu cache lines: "8 MiB (8 instances)" (total across instances) -> KiB for one instance."""
    m = re.match(r"\s*([\d.]+)\s*([KMG]i?B|B)\b(?:.*?\((\d+) instance)?", value, re.I)
    if not m:
        return 0.0
    total = float(m.group(1)) * _SIZE_UNITS.get(m.group(2).upper(), 1)
    inst = int(m.group(3)) if m.group(3) else 1
    return total / max(inst, 1) / 1024


def parse_lscpu(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def parse_cpu(sections: dict[str, list[str]]) -> tuple[LinuxCPUInfo, dict[str, float]]:
    l = parse_lscpu(sections.get("CPUCAP", []))
    pol = {}
    for line in sections.get("CPUPOL", []):
        if "=" in line:
            k, v = line.split("=", 1)
            pol[k] = v.strip()

    def i(key, default=0):
        try:
            return int(l.get(key, default))
        except ValueError:
            return default

    sockets = i("Socket(s)", 1) or 1
    cores = i("Core(s) per socket", 0) * sockets
    threads_per = i("Thread(s) per core", 1) or 1
    logical = i("CPU(s)", cores * threads_per)
    cores = cores or logical
    max_mhz = _num(l.get("CPU max MHz", "")) or ((_num(pol.get("max", "")) or 0) / 1000)
    min_mhz = _num(l.get("CPU min MHz", "")) or ((_num(pol.get("min", "")) or 0) / 1000)
    virt = None
    if l.get("Virtualization"):
        virt = True
    else:
        flags = set(l.get("Flags", "").split())
        if flags:
            virt = bool(flags & {"vmx", "svm"})
    boost = None
    if pol.get("boost") in ("0", "1"):
        boost = pol["boost"] == "1"
    elif pol.get("no_turbo") in ("0", "1"):
        boost = pol["no_turbo"] == "0"
    info = LinuxCPUInfo(
        name=l.get("Model name", "").strip(), manufacturer=l.get("Vendor ID", ""), vendor=l.get("Vendor ID", ""),
        cores=cores, logical=logical, sockets=sockets, maxMHz=max_mhz, minMHz=min_mhz,
        l1KB=_cache_kb(l.get("L1d cache", "")), l2KB=_cache_kb(l.get("L2 cache", "")),
        l3KB=_cache_kb(l.get("L3 cache", "")), virtualization=virt,
        governor=pol.get("governor", ""), scaling_driver=pol.get("driver", ""), epp=pol.get("epp", ""),
        boost=boost, smt=pol.get("smt", ""), microcode=l.get("microcode", ""),
        flags=set(l.get("Flags", "").split()))
    freqs = {}
    for line in sections.get("CPUFREQ", []):
        f = line.split()
        if len(f) == 2 and f[1].isdigit():
            freqs[f[0]] = int(f[1]) / 1000.0
    if freqs:
        info.curMHz = sum(freqs.values()) / len(freqs)
    return info, freqs


@dataclass
class HwmonReading:
    chip: str
    dev: str
    kind: str   # temp / fan / power / in / freq
    label: str
    value: float
    file: str


def parse_hwmon(lines: list[str]) -> list[HwmonReading]:
    out = []
    for line in lines:
        f = line.split("|")
        if len(f) < 5:
            continue
        chip, dev, fname, label, raw = f[0], f[1], f[2], f[3], "|".join(f[4:])
        v = _num(raw)
        if v is None:
            continue
        kind = re.match(r"[a-z]+", fname).group(0)
        out.append(HwmonReading(chip, dev, kind, label, v, fname))
    return out


def _sensor_from_hwmon(r: HwmonReading) -> Optional[HWSensor]:
    chip = r.chip or "hwmon"
    name = f"{chip} {r.label}" if r.label else f"{chip} {r.file.split('_')[0]}"
    ident = f"/{chip}/{r.dev}/{r.file}"
    if r.kind == "temp":
        if r.value <= -50000 or r.value > 250000:
            return None
        return HWSensor(name, "Temperature", r.value / 1000.0, ident)
    if r.kind == "fan":
        return HWSensor(name, "Fan", r.value, ident)
    if r.kind == "power":
        return HWSensor(name, "Power", r.value / 1_000_000.0, ident)
    if r.kind == "in":
        return HWSensor(name, "Voltage", r.value / 1000.0, ident)
    if r.kind == "freq":
        return HWSensor(name, "Clock", r.value / 1_000_000.0, ident)
    return None


def cpu_temperature(readings: list[HwmonReading]) -> Optional[float]:
    """k10temp Tctl/Tdie (AMD), coretemp Package id 0 (Intel); falls back to the hottest acpitz zone."""
    best = None
    for r in readings:
        if r.kind != "temp":
            continue
        if r.chip == "k10temp" and r.label in ("Tctl", "Tdie"):
            return r.value / 1000.0
        if r.chip == "coretemp" and r.label.startswith("Package"):
            return r.value / 1000.0
        if r.chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz"):
            v = r.value / 1000.0
            best = v if best is None else max(best, v)
    return best


def parse_gpus(lines: list[str], nvidia: list[NVInfo], nv_buses: dict[int, str]) -> list[LinuxGPU]:
    gpus: list[LinuxGPU] = []
    cur: Optional[LinuxGPU] = None
    attrs: dict[str, str] = {}
    hw: list[tuple[str, str, float]] = []
    names = ("", "")

    def finish():
        nonlocal cur, attrs, hw, names
        if cur is None:
            return
        _finish_gpu(cur, attrs, hw, names, nvidia, nv_buses)
        gpus.append(cur)
        cur, attrs, hw, names = None, {}, [], ("", "")

    for line in lines:
        f = line.split("|")
        tag = f[0]
        if tag == "CARD" and len(f) >= 6:
            finish()
            vendor = VENDORS.get(f[3].strip().lower(), f[3].strip())
            cur = LinuxGPU(id=f"{f[1]}|{f[2]}", name="", driver=f[5].strip(), vendor=vendor, slot=f[2], card=f[1],
                           status="")
            cur.luid = None
        elif tag == "ATTR" and len(f) >= 3:
            attrs[f[1]] = "|".join(f[2:]).strip()
        elif tag == "HW" and len(f) >= 4:
            v = _num(f[3])
            if v is not None:
                hw.append((f[1], f[2], v))
        elif tag == "NAME":
            names = (f[1] if len(f) > 1 else "", f[2] if len(f) > 2 else "")
        elif tag == "END":
            finish()
    finish()
    return gpus


def _finish_gpu(g: LinuxGPU, attrs: dict, hw: list, names: tuple, nvidia: list[NVInfo], nv_buses: dict[int, str]):
    dev_name, vendor_name = names
    base = dev_name.strip()
    g.name = base or f"{g.vendor} GPU ({g.card})"
    # lspci's "Device:" for AMD is often a codename like "Navi 33 [Radeon RX 7600/7600 XT]"; prefer the bracket
    m = re.search(r"\[(.+)\]\s*$", g.name)
    if m and g.vendor in ("AMD", "NVIDIA"):
        g.name = (f"{g.vendor} {m.group(1)}" if g.vendor == "AMD" else m.group(1))
    g.processor = dev_name.strip() if m else ""
    g.is_integrated = False

    def a(key) -> Optional[float]:
        return _num(attrs.get(key, ""))

    # --- NVIDIA: nvidia-smi is the authority ---
    if g.vendor == "NVIDIA" and nvidia:
        idx = next((i for i, bus in nv_buses.items() if bus[-7:].lower() == g.slot[-7:].lower()), None)
        info = nvidia[idx] if idx is not None and idx < len(nvidia) else (nvidia[0] if len(nvidia) == 1 else None)
        if info is not None:
            g.nvidia = info
            g.driver = info.driver or g.driver
            g.vram_total, g.vram_used = info.mem_total, info.mem_used
            g.engines = {"Graphics / compute": info.util or 0.0, "Memory controller": info.mem_util or 0.0}
            g.details = [("Driver", f"nvidia {info.driver}"), ("Performance state", info.pstate),
                         ("Core clock", f"{info.clock_gr:.0f} / {info.clock_max_gr:.0f} MHz" if info.clock_gr is not None and info.clock_max_gr is not None else "–"),
                         ("Memory clock", f"{info.clock_mem:.0f} / {info.clock_max_mem:.0f} MHz" if info.clock_mem is not None and info.clock_max_mem is not None else "–"),
                         ("Fan", f"{info.fan:.0f}%" if info.fan is not None else "–"),
                         ("Power limit", f"{info.power_limit:.0f} W" if info.power_limit is not None else "–")]
            _add_pcie(g, attrs)
            return

    # --- AMD / Intel: sysfs ---
    busy = a("gpu_busy_percent")
    if busy is not None:
        g.engines["Graphics"] = busy
    mb = a("mem_busy_percent")
    if mb is not None:
        g.engines["Memory controller"] = mb
    vt, vu = a("mem_info_vram_total"), a("mem_info_vram_used")
    if vt:
        g.vram_total, g.vram_used = vt, vu
    g.gtt_total, g.gtt_used = a("mem_info_gtt_total"), a("mem_info_gtt_used")
    # An APU/iGPU reports a small VRAM carve-out and uses system RAM (GTT) for the rest.
    g.is_integrated = bool(g.vendor == "Intel" or (vt is not None and vt <= 2 * 1024 ** 3 and (g.gtt_total or 0) > vt * 2))
    g.details = [("Driver", g.driver or "–")]
    if g.is_integrated:
        g.details.append(("Type", "Integrated (shares system memory)"))

    for fname, label, v in hw:
        kind = re.match(r"[a-z]+", fname).group(0)
        lbl = label or fname.split("_")[0]
        ident = f"/{g.card}/{fname}"
        if kind == "temp" and -50000 < v < 250000:
            g.sensors.append(HWSensor(f"GPU {lbl}", "Temperature", v / 1000.0, ident))
        elif kind == "power" and "cap" not in fname:
            g.sensors.append(HWSensor(f"GPU {lbl or 'power'}", "Power", v / 1_000_000.0, ident))
        elif kind == "power":
            g.details.append(("Power cap", f"{v / 1_000_000.0:.0f} W"))
        elif kind == "fan" and fname.endswith("_input"):
            g.sensors.append(HWSensor(f"GPU fan", "Fan", v, ident))
            g.details.append(("Fan", f"{v:.0f} RPM"))
        elif kind == "freq":
            g.details.append(({"sclk": "Core clock", "mclk": "Memory clock"}.get(lbl, f"{lbl or 'Clock'} clock"), f"{v / 1_000_000.0:.0f} MHz"))
        elif kind == "in":
            g.details.append(("Core voltage", f"{v / 1000.0:.3f} V"))
    for k, label in (("pp_dpm_sclk", "Core clock"), ("pp_dpm_mclk", "Memory clock")):
        s = attrs.get(k)
        if s and not any(d[0].lower().startswith(label.split()[0].lower()) for d in g.details):
            m2 = re.search(r"(\d+)\s*Mhz", s, re.I)
            if m2:
                g.details.append((label, f"{m2.group(1)} MHz"))
    if "gt_cur_freq_mhz" in attrs or "gt_act_freq_mhz" in attrs:
        cur = a("gt_act_freq_mhz") or a("gt_cur_freq_mhz")
        mx = a("gt_max_freq_mhz")
        g.details.append(("GT clock", f"{cur:.0f} / {mx:.0f} MHz" if cur is not None and mx else (f"{cur:.0f} MHz" if cur is not None else "–")))
        if mx and cur is not None and g.util is None:
            g.engines["GT frequency"] = min(100.0, cur / mx * 100)
    if attrs.get("power_dpm_force_performance_level"):
        g.details.append(("Performance level", attrs["power_dpm_force_performance_level"]))
    if g.gtt_total:
        g.details.append(("GTT (system RAM) memory",
                          f"{(g.gtt_used or 0) / 1024 ** 3:.1f} of {g.gtt_total / 1024 ** 3:.1f} GiB"))
    _add_pcie(g, attrs)


def _add_pcie(g: LinuxGPU, attrs: dict):
    speed, width = attrs.get("current_link_speed"), attrs.get("current_link_width")
    if speed and width:
        g.details.append(("PCIe link", f"{speed} x{width}"))


def parse_nv_buses(lines: list[str]) -> dict[int, str]:
    out = {}
    for line in lines:
        f = line.split(",")
        if len(f) == 2 and f[0].strip().isdigit():
            out[int(f[0])] = f[1].strip()
    return out


def parse_drm_processes(fdinfo: list[str], ps: list[str], prev_ns: dict, dt: float) -> tuple[list[GPUProcess], dict]:
    """Groups fdinfo lines by (pid, drm-client-id), summing VRAM and turning the cumulative engine-time
    counters into a percentage using the previous sample."""
    names = {}
    for line in ps:
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            names[int(parts[0])] = parts[1]
    fds: dict[tuple, dict] = {}
    for line in fdinfo:
        m = re.match(r"/proc/(\d+)/fdinfo/(\d+):(drm-[a-z0-9-]+):\s*(.*)$", line)
        if m:
            fds.setdefault((int(m.group(1)), m.group(2)), {})[m.group(3)] = m.group(4).strip()
    # One DRM client can appear on several fds (dup'd); count each (pid, client-id) once.
    clients: dict[tuple, dict] = {}
    for (pid, fd), d in fds.items():
        clients.setdefault((pid, d.get("drm-client-id", fd)), d)
    per_pid: dict[int, dict] = {}
    cur_ns: dict = {}
    for (pid, cid), d in clients.items():
        if "drm-driver" not in d:
            continue
        vram_kib = 0.0
        for k in ("drm-memory-vram", "drm-total-vram0", "drm-total-local0", "drm-resident-vram0"):
            v = d.get(k)
            if v:
                mm = re.match(r"([\d.]+)\s*(\w*)", v)
                if mm:
                    unit = {"": 1 / 1024, "KiB": 1, "MiB": 1024, "GiB": 1024 ** 2}.get(mm.group(2), 1)
                    vram_kib = max(vram_kib, float(mm.group(1)) * unit)
                break
        ns = 0.0
        for k in ("drm-engine-gfx", "drm-engine-render"):
            v = d.get(k)
            if v:
                mm = re.match(r"(\d+)", v)
                if mm:
                    ns = float(mm.group(1))
                    break
        p = per_pid.setdefault(pid, {"vram": 0.0, "util": 0.0})
        p["vram"] += vram_kib * 1024
        key = (pid, cid)
        cur_ns[key] = ns
        if key in prev_ns and dt > 0.2 and ns >= prev_ns[key]:
            p["util"] += min(100.0, (ns - prev_ns[key]) / (dt * 1e9) * 100)
    procs = [GPUProcess(pid=pid, name=names.get(pid, "?"), util=min(100.0, v["util"]), vram=v["vram"])
             for pid, v in per_pid.items()]
    procs.sort(key=lambda p: (-p.util, -p.vram))
    return procs[:15], cur_ns


def parse_nv_pmon(lines: list[str]) -> list[GPUProcess]:
    header: list[str] = []
    out = []
    for line in lines:
        if line.startswith("#"):
            cols = line.lstrip("# ").split()
            if "pid" in cols:
                header = cols
            continue
        f = line.split()
        if not header or len(f) < len(header):
            continue
        row = dict(zip(header, f))
        try:
            pid = int(row["pid"])
        except (KeyError, ValueError):
            continue

        def n(k):
            try:
                return float(row.get(k, "-"))
            except ValueError:
                return 0.0
        out.append(GPUProcess(pid=pid, name=row.get("command", "?"), util=n("sm"), vram=n("fb") * 1024 * 1024))
    out.sort(key=lambda p: (-p.util, -p.vram))
    return out[:15]


def parse_os_release(lines: list[str]) -> tuple[str, bool]:
    """Returns (id, is_ostree)."""
    osid, ostree, like = "", False, ""
    for line in lines:
        if line.startswith("ID="):
            osid = line[3:].strip().strip('"').lower()
        elif line.startswith("ID_LIKE="):
            like = line[8:].strip().strip('"').lower()
        elif line.startswith("OSTREE=1"):
            ostree = True
    if not osid:
        return "", ostree
    return (osid if not like else f"{osid} {like}"), ostree


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class GamingLinuxSession(LinuxSession):
    def __init__(self, machine: Machine):
        super().__init__(machine)
        self.cpu_info = LinuxCPUInfo()
        self.sensors: list[HWSensor] = []
        self.os_id = ""
        self.is_ostree = False
        self._hw_text_ok = False
        self._prev_drm_ns: dict = {}
        self._prev_drm_time = 0.0
        self._gpu_page_active = False

    @property
    def nav_items(self):
        items = set(super().nav_items)
        items |= {NavItem.cpu, NavItem.gpu, NavItem.sensors}
        return sort_nav_items(items)

    # -- polling --
    def _poll(self) -> bool:
        ok = super()._poll()
        if ok:
            self._collect_hw(with_procs=False)
        return ok

    def _collect_hw(self, with_procs: bool):
        try:
            text = self._runner.sh(HW_SCRIPT + (GPU_PROC_SCRIPT if with_procs else ""), self._ssh())
        except Exception:
            return
        sec = _split_sections(text)
        if "CPUCAP" not in sec:
            return
        self.os_id, self.is_ostree = parse_os_release(sec.get("OSREL", []))
        info, freqs = parse_cpu(sec)
        readings = parse_hwmon(sec.get("HWMON", []))
        info.temp = cpu_temperature(readings)
        info.package_watts = self.power_watts
        self.cpu_info = info
        for c in self.cores:
            if c.name in freqs:
                c.freqMHz = freqs[c.name]
            elif info.curMHz:
                c.freqMHz = info.curMHz

        sensors = [s for s in (_sensor_from_hwmon(r) for r in readings) if s is not None]

        nvidia = _parse_nvidia("\n".join(sec.get("NVIDIA", [])))
        buses = parse_nv_buses(sec.get("NVBUS", []))
        gpus = parse_gpus(sec.get("GPU", []), nvidia, buses)
        # Fallback: nvidia-smi present but DRM sysfs gave nothing for it (e.g. containers / odd setups)
        if nvidia and not any(g.nvidia for g in gpus):
            for i, n in enumerate(nvidia):
                gpus.append(LinuxGPU(id=f"nv{i}|{n.name}", name=n.name, vendor="NVIDIA", driver=n.driver,
                                     nvidia=n, vram_total=n.mem_total, vram_used=n.mem_used,
                                     engines={"Graphics / compute": n.util or 0.0}))
        for g in gpus:
            for s in g.sensors:
                if s.type in ("Temperature", "Power", "Fan") and not any(x.identifier == s.identifier for x in sensors):
                    sensors.append(s)
            if g.nvidia:
                n = g.nvidia
                for nm, ty, v in ((f"{g.name} temperature", "Temperature", n.temp), (f"{g.name} power", "Power", n.power),
                                  (f"{g.name} fan", "Control", n.fan), (f"{g.name} core clock", "Clock", n.clock_gr),
                                  (f"{g.name} load", "Load", n.util)):
                    if v is not None:
                        sensors.append(HWSensor(nm, ty, v, f"/nvidia/{g.id}/{ty}"))
        if info.temp is not None and not any(s.name == "CPU package" for s in sensors):
            sensors.insert(0, HWSensor("CPU package", "Temperature", info.temp, "/cpu/package"))
        self.sensors = sensors
        self.gpus = gpus
        self.gpu_percent = max((g.util for g in gpus if g.util is not None), default=None)
        for g in gpus:
            hist = self.gpu_history.setdefault(g.id, GPUHistory())
            self.push(hist.util, g.util)
            self.push(hist.vram, (g.vram_fraction * 100) if g.vram_fraction is not None else None)

        if with_procs:
            now = time.monotonic()
            procs, self._prev_drm_ns = parse_drm_processes(sec.get("DRMPROC", []), sec.get("PS", []),
                                                           self._prev_drm_ns, now - self._prev_drm_time)
            self._prev_drm_time = now
            nvprocs = parse_nv_pmon(sec.get("NVPMON", []))
            names = {p.pid for p in procs}
            procs += [p for p in nvprocs if p.pid not in names]
            procs.sort(key=lambda p: (-p.util, -p.vram))
            self.gpu_processes = procs[:15]

    def refresh_gpu_detail(self):
        def do():
            self._collect_hw(with_procs=True)
        self.submit(do, "gpu")

    def _sample_power(self):
        super()._sample_power()
        # Add AMD/Intel GPU board power (hwmon); NVIDIA is already included by the base sampler.
        extra = 0.0
        for g in self.gpus:
            if g.nvidia is None:
                p = g.power
                if p is not None:
                    extra += p
        if extra and self.power_watts is not None:
            self.power_watts += extra
        elif extra:
            self.power_watts = extra

    # -- updates: rpm-ostree + flatpak (Bazzite) or pacman + flatpak (CachyOS) --
    def refresh_updates(self):
        def do():
            items: list[UpdateItem] = []
            try:
                if self.is_ostree or "bazzite" in self.os_id:
                    t = self._runner.sh("rpm-ostree upgrade --check 2>&1", self._ssh(), sudo=True, merge=True)
                    if "AvailableUpdate" in t:
                        ver = re.search(r"Version:\s*(\S+)", t)
                        items.append(UpdateItem(id="rpm-ostree", name="Bazzite OS image",
                                                newVersion=ver.group(1) if ver else "new image", isSecurity=False,
                                                source="rpm-ostree"))
                else:
                    t = self._runner.sh("pacman -Qu 2>/dev/null", self._ssh())
                    for it in _parse_pacman_updates(t):
                        it.source = "pacman"
                        items.append(it)
                fp = self._runner.sh("flatpak remote-ls --updates --columns=application,version 2>/dev/null",
                                     self._ssh())
                for line in fp.splitlines():
                    f = line.split("\t")
                    if f and f[0].strip():
                        items.append(UpdateItem(id=f"flatpak-{f[0].strip()}", name=f[0].strip(),
                                                newVersion=(f[1].strip() if len(f) > 1 else ""),
                                                isSecurity=False, source="flatpak"))
            except Exception:
                return
            self.updates = items
            self.updates_checked = True
        self.submit(do, "updates")

    def upgrade_all(self, on_done):
        on_done = self._main_thread(on_done)

        def do():
            if self.is_ostree or "bazzite" in self.os_id:
                cmd = "rpm-ostree upgrade 2>&1; flatpak update -y --noninteractive 2>&1; echo; echo 'Reboot to apply the new OS image.'"
            else:
                cmd = "pacman -Syu --noconfirm 2>&1; flatpak update -y --noninteractive 2>&1"
            try:
                out = self._runner.sh(cmd, self._ssh(), sudo=True, merge=True)
            except Exception as e:
                out = str(e)
            self.refresh_updates()
            on_done(out)
        self.submit(do)

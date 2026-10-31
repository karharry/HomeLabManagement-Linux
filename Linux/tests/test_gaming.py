import gaming_session as gs
from core import MachineKind, Machine, NavItem, store

LSCPU = """Architecture:                         x86_64
Vendor ID:                            AuthenticAMD
Model name:                           AMD Ryzen 7 7800X3D 8-Core Processor
CPU(s):                               16
Thread(s) per core:                   2
Core(s) per socket:                   8
Socket(s):                            1
CPU max MHz:                          5050.0000
CPU min MHz:                          400.0000
Virtualization:                       AMD-V
L1d cache:                            256 KiB (8 instances)
L2 cache:                             8 MiB (8 instances)
L3 cache:                             96 MiB (1 instance)
Flags:                                fpu svm avx2"""

SAMPLE = f"""##OSREL
ID=bazzite
ID_LIKE="fedora"
OSTREE=1
##CPUCAP
{LSCPU}
microcode: 0xa601206
##CPUFREQ
cpu0 4500000
cpu1 3000000
##CPUPOL
governor=powersave
driver=amd-pstate-epp
epp=balance_performance
min=400000
max=5050000
boost=1
no_turbo=
smt=on
##HWMON
k10temp|0000:00:18.3|temp1_input|Tctl|62500
amdgpu|0000:03:00.0|temp1_input|edge|55000
nct6798|nct6798.656|fan1_input||1200
##GPU
CARD|card1|0000:03:00.0|0x1002|0x7480|amdgpu
ATTR|gpu_busy_percent|37
ATTR|mem_info_vram_used|2147483648
ATTR|mem_info_vram_total|8589934592
ATTR|mem_info_gtt_total|16000000000
ATTR|mem_info_gtt_used|100000000
ATTR|current_link_speed|16.0 GT/s PCIe
ATTR|current_link_width|8
ATTR|pp_dpm_sclk|1: 2400Mhz *
HW|temp1_input|edge|55000
HW|temp2_input|junction|70000
HW|power1_average||88000000
HW|power1_cap||160000000
HW|fan1_input||900
NAME|Navi 33 [Radeon RX 7600/7600 XT/7600M XT/PRO W7600]|Advanced Micro Devices, Inc. [AMD/ATI]
END
CARD|card0|0000:01:00.0|0x10de|0x2684|nvidia
NAME|AD102 [GeForce RTX 4090]|NVIDIA Corporation
END
##NVIDIA
0, NVIDIA GeForce RTX 4090, 12, 5, 1024, 24564, 45, 70.5, 450.00, 30, 2100, 2520, 10501, 10501, 560.35, P2
##NVBUS
0, 00000000:01:00.0
"""


def test_parse_everything():
    sec = gs._split_sections(SAMPLE)
    info, freqs = gs.parse_cpu(sec)
    assert info.name.startswith("AMD Ryzen 7 7800X3D") and info.cores == 8 and info.logical == 16
    assert info.maxMHz == 5050 and info.l2KB == 1024 and info.l3KB == 98304 and info.l1KB == 32
    assert info.virtualization is True and info.boost is True and info.governor == "powersave"
    assert freqs == {"cpu0": 4500.0, "cpu1": 3000.0} and info.curMHz == 3750
    readings = gs.parse_hwmon(sec["HWMON"])
    assert gs.cpu_temperature(readings) == 62.5
    sensors = [gs._sensor_from_hwmon(r) for r in readings]
    assert {s.type for s in sensors} == {"Temperature", "Fan"}
    nv = gs._parse_nvidia("\n".join(sec["NVIDIA"]))
    gpus = gs.parse_gpus(sec["GPU"], nv, gs.parse_nv_buses(sec["NVBUS"]))
    amd, nvd = gpus
    assert amd.vendor == "AMD" and amd.name == "AMD Radeon RX 7600/7600 XT/7600M XT/PRO W7600"
    assert amd.util == 37 and amd.vram_total == 8 * 1024 ** 3 and amd.vram_fraction == 0.25
    assert amd.temp in (55.0, 70.0) and amd.power == 88.0 and not amd.is_integrated
    assert ("Core clock", "2400 MHz") in amd.details and ("PCIe link", "16.0 GT/s PCIe x8") in amd.details
    assert nvd.nvidia and nvd.util == 12 and nvd.temp == 45 and nvd.power == 70.5
    assert nvd.vram_total == 24564 * 1048576
    assert gs.parse_os_release(sec["OSREL"]) == ("bazzite fedora", True)


def test_intel_igpu():
    lines = ["CARD|card0|0000:00:02.0|0x8086|0x46a6|i915", "ATTR|gt_act_freq_mhz|450", "ATTR|gt_max_freq_mhz|1450",
             "NAME|AlderLake-P GT2 [Iris Xe Graphics]|Intel Corporation", "END"]
    [g] = gs.parse_gpus(lines, [], {})
    assert g.vendor == "Intel" and g.is_integrated and 30 < g.util < 32


def test_process_parsers():
    fd = ["/proc/10/fdinfo/5:drm-driver:\tamdgpu", "/proc/10/fdinfo/5:drm-client-id:\t7",
          "/proc/10/fdinfo/5:drm-memory-vram:\t2048 KiB", "/proc/10/fdinfo/5:drm-engine-gfx:\t1000000000 ns"]
    ps = [" 10 steam"]
    procs, ns = gs.parse_drm_processes(fd, ps, {}, 1.0)
    assert procs[0].name == "steam" and procs[0].vram == 2048 * 1024
    fd2 = [l.replace("1000000000", "1500000000") for l in fd]
    procs, _ = gs.parse_drm_processes(fd2, ps, ns, 1.0)
    assert round(procs[0].util) == 50
    pm = ["# gpu pid type sm mem enc dec jpg ofa fb ccpm command", "0 99 G 40 10 0 0 0 0 512 0 game"]
    assert gs.parse_nv_pmon(pm)[0].util == 40


def test_kind_registered():
    k = MachineKind.bazzite
    assert k.label == "Bazzite / CachyOS" and k.is_posix_shell
    assert {NavItem.cpu, NavItem.gpu, NavItem.sensors} <= set(k.nav_items)
    from machine_session import make_session
    s = make_session(Machine(kind=k, host="h", user="u"))
    assert isinstance(s, gs.GamingLinuxSession) and NavItem.gpu in s.nav_items


def test_pages_offscreen():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from machine_session import make_session
    from pages_gaming import GamingCPUPage, GamingGPUPage
    from pages_windows import WindowsSensorsPage
    s = make_session(Machine(kind=MachineKind.bazzite, host="h", user="u"))
    sec = gs._split_sections(SAMPLE)
    s.cpu_info, _ = gs.parse_cpu(sec)
    nv = gs._parse_nvidia("\n".join(sec["NVIDIA"]))
    s.gpus = gs.parse_gpus(sec["GPU"], nv, gs.parse_nv_buses(sec["NVBUS"]))
    s.sensors = [x for x in (gs._sensor_from_hwmon(r) for r in gs.parse_hwmon(sec["HWMON"])) if x]
    for page in (GamingCPUPage(s), GamingGPUPage(s), WindowsSensorsPage(s)):
        page._refresh()
        page.deleteLater()


def test_start_mode_exclusive():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from settings_dialog import SettingsDialog, start_mode
    d = SettingsDialog()
    d.tray_check.setChecked(True)
    assert start_mode() == "tray"
    d.minimized_check.setChecked(True)
    assert start_mode() == "minimized" and not d.tray_check.isChecked()
    d.minimized_check.setChecked(False)
    assert start_mode() == "none"


def test_tray_menu_has_actions_without_machines():
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    from app_model import AppModel
    from tray import TrayIcon
    t = TrayIcon(AppModel(), QWidget())
    titles = [a.text() for a in t.contextMenu().actions() if a.text()]
    assert {"Show Window", "Preferences…", "Quit HomeLab Management"} <= set(titles)

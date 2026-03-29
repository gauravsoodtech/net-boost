<div align="center">

# ⚡ NetBoost

### Gaming Network Optimizer for Windows

**Eliminate ping spikes · Maximize FPS · Auto-tune your system for competitive gaming**

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt5](https://img.shields.io/badge/PyQt5-5.15.11-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt5/)
[![Windows](https://img.shields.io/badge/Windows_11-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Built with Claude](https://img.shields.io/badge/Built%20with-Claude%20AI-D97706?style=for-the-badge&logo=anthropic&logoColor=white)](https://claude.ai)

![NetBoost Dashboard](https://i.imgur.com/placeholder.png)

</div>

---

## The Problem

Playing Valorant or CS2 on a gaming laptop over Wi-Fi? You've probably seen this:

- 🔴 **200–500ms ping spikes** out of nowhere (Intel Wi-Fi power saving kicking in)
- 🔴 **FPS drops and stutters** mid-game (Windows timer resolution, E-core scheduling)
- 🔴 **Background apps eating bandwidth** (Windows Update downloading mid-match)
- 🔴 **GPU clocks dropping** between frames (dynamic P-states on laptop GPUs)

NetBoost fixes all of it with one click.

---

## Features

### 📶 Wi-Fi Optimizer — Kills Ping Spikes
The Intel AX211 aggressively power-saves and background-scans by default, causing random 200–500ms spikes. NetBoost disables this at the driver registry level:

| Tweak | Effect |
|-------|--------|
| Disable Power Saving (`PowerSavingMode=0`) | Eliminates random ping spikes |
| Minimize Roaming Aggressiveness | Stops mid-game AP scanning |
| Prefer 6 GHz Band | Less congestion, lower latency |
| Max TX Power | Stronger signal, fewer retransmits |
| Disable Background BSS Scanning | No more scan-induced lag |

### 🎯 FPS Booster
| Tweak | Effect |
|-------|--------|
| P-Core Affinity (i7-13650HX: 0x0FFF) | Games run on performance cores only |
| 0.5ms Timer Resolution | Smoother frame delivery (default: 15.6ms) |
| Ultimate Performance Power Plan | No CPU/GPU throttling |
| Disable Xbox Game DVR | Frees GPU from background recording |
| NVIDIA Ultra Low Latency Mode | Sub-frame GPU queue |
| Disable Dynamic P-States | Stable GPU clocks between frames |

### 🌐 Network Optimizer
- **Nagle's Algorithm off** (`TCPNoDelay=1`) — reduces latency for small packets
- **TCP Ack Frequency=1** — no delayed acknowledgements
- **DNS switch** to Cloudflare (1.1.1.1), Google (8.8.8.8), or Quad9 (9.9.9.9)
- **DSCP QoS marking** — marks game traffic as Expedited Forwarding (DSCP 46)

### 🔇 Background Killer
- Pauses **Windows Update**, **OneDrive**, **BITS** on game launch
- Suspends **SearchIndexer**, deprioritizes browsers
- Everything **auto-restored** when game exits

### 📊 Live Monitor
- Real-time ping/jitter/packet loss graph (PyQtGraph, 60s rolling window)
- Dashboard badges update live every ~500ms — shows "--" when offline instead of a false 0.0
- Free RAM badge refreshes every 5 seconds; game processes highlighted green in Bandwidth tab
- Wi-Fi **Test Latency** button runs async (no UI freeze) and shows Before → After ms
- Auto game detection — activates in **<1.5 seconds** of game launch
- System tray: grey (idle) → yellow (game detected) → green (optimized)

### 🗺️ Route Analyzer
Diagnoses which network hop is causing mid-match ping spikes — without needing a VPN:

| Feature | Detail |
|---------|--------|
| **Auto server detection** | Reads live connections of the game process to find its server IP |
| **Ping re-targeting** | Once game server IP is found, the Dashboard ping monitor switches from 1.1.1.1 to the actual game server — showing real in-game latency |
| **Live hop table** | Populates row-by-row as `tracert` streams output |
| **Bottleneck highlighting** | Hops with >15ms jump from previous amber; timeouts red |
| **Summary line** | Reports exact hop number and latency delta for each bottleneck |
| **Manual IP fallback** | Enter any target IP if auto-detection doesn't find the server |

### 🩺 Settings Health Monitor
NetBoost actively watches for signs that your applied settings are causing problems:

| What it detects | How |
|----------------|-----|
| **Random disconnects** | Packet loss ≥8% while `Minimize Roaming Aggressiveness` or `Prefer 6 GHz` is on → amber toast + alert |
| **Jitter spikes** | 3 consecutive readings >30ms jitter → amber toast warning background traffic or Wi-Fi interference |
| **FPS drops after 10 min** | GPU temp ≥85°C while `NVIDIA Maximum Performance` is on → warns about thermal throttling |
| **Pre-apply risk warning** | Before applying HIGH/MEDIUM risk settings, a modal lists the risk and advice |
| **Health Diagnostics panel** | Monitor tab shows every active setting with a color-coded risk badge (🟢/🟡/🔴) and a live alert log |
| **Quick-disable** | Alert rows include a `[Disable <setting>]` button — one click unchecks the culprit without leaving the Monitor tab |
| **LSO apply failure** | If the Intel Wi-Fi adapter key can't be found, a warning toast fires instead of silently showing ✓ Applied |

### 🛡️ Crash-Safe
All changes tracked in an atomic state file. If NetBoost crashes mid-session, it **automatically restores your original settings** on next launch.

### ✨ Visual Feedback
- Apply buttons flash **green ✓** on success and **red ✗** on error, then revert — no silent failures
- Floating toast notifications appear top-right for every apply action (success / error / info / **warning**)
- Polished dark theme: gradient buttons, tab underline indicator, focus glows on inputs, thin rounded scrollbars

---

## Screenshots

<div align="center">

| Dashboard | Wi-Fi Optimizer |
|-----------|----------------|
| ![Dashboard](https://i.imgur.com/placeholder1.png) | ![WiFi](https://i.imgur.com/placeholder2.png) |

| FPS Boost | Live Monitor |
|-----------|-------------|
| ![FPS](https://i.imgur.com/placeholder3.png) | ![Monitor](https://i.imgur.com/placeholder4.png) |

</div>

---

## Getting Started

### Requirements
- Windows 10/11 (64-bit)
- Python 3.13+
- Administrator privileges (required for registry and service access)

### Install & Run

```bash
git clone https://github.com/gauravsoodtech/netboost.git
cd netboost
pip install -r requirements.txt
python main.py
```

A UAC prompt will appear — click **Yes**. NetBoost requires admin to modify network and system settings.

### Build Standalone `.exe`

```bash
pyinstaller --onefile --windowed --uac-admin \
  --icon=netboost.ico \
  --add-data "config;config" \
  --add-data "resources;resources" \
  --hidden-import=win32timezone \
  main.py
```

Output: `dist/main.exe` → rename to `NetBoost.exe`

---

## Usage Guide

1. **Wi-Fi tab first** — enable all toggles, click Apply All → instant ping improvement
2. **FPS Boost tab** — enable all, click Apply FPS Boost
3. **Optimizer tab** — TCP tweaks + switch DNS to Cloudflare + pause background services
4. **Dashboard** — toggle Game Mode ON
5. **Profiles tab** — save as "Gaming" profile for 1-click activation next time
6. **Settings tab** — enable "Start with Windows" + "Auto-enable Game Mode"

After setup, just launch your game. NetBoost handles everything automatically.

---

## Project Structure

```
netboost/
├── main.py                    # Entry point: admin check, crash recovery, Qt bootstrap
├── requirements.txt
├── config/
│   └── games_default.json     # Pre-configured game list (Valorant, CS2, Apex, etc.)
├── core/
│   ├── admin.py               # UAC elevation
│   ├── state_guard.py         # Crash-safe atomic state file
│   ├── process_watcher.py     # QThread: game detection via psutil
│   ├── ping_monitor.py        # QThread: ICMP ping monitor
│   ├── wifi_optimizer.py      # Intel AX211 registry tweaks
│   ├── network_optimizer.py   # TCP registry per-interface
│   ├── dns_switcher.py        # netsh DNS management
│   ├── fps_booster.py         # Power plan, P-core affinity, timer
│   ├── nvidia_optimizer.py    # RTX registry + nvidia-smi
│   ├── background_killer.py   # Service/process management
│   ├── bandwidth_manager.py   # QoS DSCP + priority
│   ├── ram_optimizer.py       # Working set + file cache flush
│   ├── profile_manager.py     # JSON profile CRUD
│   ├── route_analyzer.py      # tracert parser + game server discovery
│   └── settings_risk.py       # Risk metadata registry (27 settings, 3 levels)
├── ui/
│   ├── main_window.py         # QMainWindow + signal wiring
│   ├── tray_icon.py           # System tray
│   ├── tab_dashboard.py       # Game Mode + ping stats
│   ├── tab_monitor.py         # Live PyQtGraph display
│   ├── tab_wifi.py            # Wi-Fi optimizer controls
│   ├── tab_fps.py             # FPS boost controls
│   ├── tab_optimizer.py       # TCP/DNS/service controls
│   ├── tab_bandwidth.py       # Process priority table
│   ├── tab_profiles.py        # Profile management
│   ├── tab_settings.py        # App settings + game list
│   ├── tab_route.py           # Route Analyzer (tracert + server discovery)
│   └── widgets/
│       ├── ping_graph.py          # PyQtGraph rolling graph
│       ├── toggle_switch.py       # Animated iOS-style toggle
│       ├── status_led.py          # Green/yellow/red LED
│       ├── status_toast.py        # Floating fade-in/out toast (success/error/info/warning)
│       └── risk_warning_dialog.py # Pre-apply risk warning modal
├── resources/styles/
│   └── dark_theme.qss         # Dark gaming UI theme
└── tests/
    ├── conftest.py
    ├── test_profile_manager.py
    ├── test_ping_monitor.py
    ├── test_dns_switcher.py
    ├── test_state_guard.py
    ├── test_settings_risk.py  # Risk registry: ordering, filtering, field validation
    └── integration_check.py   # Live system validation script
```

---

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| **Python 3.13** | Core language |
| **PyQt5** | GUI framework |
| **PyQtGraph** | Real-time ping/jitter graphs |
| **psutil** | Process monitoring + network adapter info |
| **pywin32** | Windows service control, process priority |
| **ctypes** | Direct Windows API calls (timer resolution, affinity) |
| **winreg** | Registry read/write for all optimizations |
| **PyInstaller** | Package to standalone `.exe` |

---

## How It Works

### The Wi-Fi Spike Fix (Most Important)
Intel's AX211 driver uses aggressive power saving by default — it parks the radio between packets to save battery. This causes 200–500ms spikes whenever a packet arrives after a brief idle period. NetBoost writes directly to the driver's registry key under `HKLM\SYSTEM\CurrentControlSet\Control\Class\{4D36E972-...}` to disable this behavior permanently while the app is running.

### P-Core Affinity
The i7-13650HX has 6 Performance cores (threads 0–11) and 8 Efficiency cores (threads 12–19). Windows sometimes schedules game threads on E-cores, causing stutters. NetBoost uses `SetProcessAffinityMask` to pin the game process to P-cores only (`0x0FFF`).

### Timer Resolution
Windows default timer fires every 15.6ms, causing uneven frame delivery. NetBoost calls `NtSetTimerResolution(5000)` to force 0.5ms resolution — the same technique used by CS2 and other competitive titles internally.

### Crash Recovery
Before every destructive operation, the original value is written to `%APPDATA%\NetBoost\state.json` via atomic write (`os.replace`). On startup, if a state file exists with a dead PID, all settings are auto-restored.

---

## Safety

- **No kernel drivers** — all tweaks use documented Windows APIs (registry, netsh, win32service)
- **Anti-cheat safe** — only uses `SetPriorityClass` and `SetProcessAffinityMask`, no process injection
- **Auto-restore on exit** — every change is reversed cleanly when the app closes
- **Crash recovery** — atomic state file ensures nothing stays modified after a crash

---

## Running Tests

```bash
# Unit tests (no admin needed)
python -m pytest tests/ -v

# Live integration check (run as admin)
python tests/integration_check.py
```

---

## Target Hardware

Built and tested on:
- **CPU:** Intel Core i7-13650HX (6P + 8E cores)
- **GPU:** NVIDIA GeForce RTX 4060 Laptop
- **Wi-Fi:** Intel Wi-Fi 6E AX211
- **RAM:** 16GB DDR5
- **OS:** Windows 11 Build 26200

Works on any Windows 10/11 system. Wi-Fi optimizations require an Intel Wi-Fi adapter; other features work universally.

---

## Built with Generative AI

This project was designed and built with **[Claude](https://claude.ai) (Anthropic)** as an AI pair programmer, using **[Claude Code](https://claude.ai/code)** — Anthropic's agentic coding CLI.

### How AI was used

| What | How Claude helped |
|------|------------------|
| **Architecture design** | Designed the full module structure, threading model, and signal flow before writing a single line |
| **Core implementation** | Wrote all 13 core optimizer modules — registry tweaks, service control, ICMP monitor, crash-safe state guard |
| **UI layer** | Built the entire PyQt5 interface — 9 tabs, animated toggle switches, PyQtGraph live graphs, system tray |
| **Windows internals** | Identified the exact Intel AX211 registry keys, P-core affinity masks, NtSetTimerResolution API calls |
| **Test suite** | Generated 4 unit test files + integration check script with mocked subprocess/registry |
| **Documentation** | Wrote this README and the CLAUDE.md developer guide |

### Workflow

The entire codebase (~9,500 lines across 45 files) was generated in a single session using Claude Code's agentic mode — Claude autonomously wrote files, ran parallel agents for different layers, and self-corrected import mismatches without manual intervention.

> **My role:** Defined the problem (Wi-Fi ping spikes on my gaming laptop), specified the target hardware (i7-13650HX, RTX 4060, Intel AX211), described the desired UX, and reviewed the output. Claude handled research, implementation, and wiring.

This is an example of **vibe coding** at scale — using AI to implement a technically deep, Windows-specific tool that would have taken weeks to build manually.

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/new-optimizer`)
3. Add your optimizer in `core/`, wire it in `main_window.py`, add tests
4. Run `python -m pytest tests/ -v`
5. Open a pull request

See `CLAUDE.md` for detailed architecture notes and contribution guidelines.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Built for gamers who are tired of blaming their ISP when it's actually Windows Update downloading in the background.

**⭐ Star this repo if NetBoost helped your ping**

</div>

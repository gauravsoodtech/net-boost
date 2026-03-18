# CLAUDE.md — NetBoost Developer Guide

This file provides guidance to Claude Code when working with the NetBoost codebase.

## Project Overview

NetBoost is a Windows gaming network optimizer built with Python 3.13 + PyQt5. It reduces ping spikes, improves FPS consistency, and automates system tweaks for competitive gaming. Requires **administrator privileges** at runtime.

**Target hardware:** Intel i7-13650HX · NVIDIA RTX 4060 Laptop · Intel Wi-Fi 6E AX211 · Windows 11

---

## Architecture

```
main.py                     # Entry: admin check → crash heal → Qt bootstrap → threads
core/                       # All business logic, no Qt widgets
ui/                         # All PyQt5 widgets, no direct registry/subprocess calls
config/                     # Static JSON (game list)
resources/styles/           # QSS dark theme
tests/                      # pytest unit tests + integration check script
```

**Threading model:**
- Main thread: Qt event loop + all UI updates
- `QThread`: `PingMonitor` → emits `reading(host, ms, timed_out)`
- `QThread`: `ProcessWatcher` → emits `game_launched(str)` / `game_exited(str)`
- `QThreadPool`: slow service stop/start operations

**Signal flow:** Core threads → Qt signals → `MainWindow` slots → UI tab methods. Never call UI methods directly from background threads.

---

## Core Modules

| Module | Responsibility | Key class |
|--------|---------------|-----------|
| `core/admin.py` | UAC elevation via `ShellExecuteW` | `is_admin()`, `elevate()` |
| `core/state_guard.py` | Crash-safe atomic state (`.tmp` → `os.replace`) | `StateGuard` |
| `core/profile_manager.py` | JSON profiles in `%APPDATA%\NetBoost\profiles\` | `ProfileManager` |
| `core/ping_monitor.py` | Raw ICMP socket, fallback to `ping.exe` | `PingMonitor(QThread)` |
| `core/process_watcher.py` | psutil polling every 1.5s | `ProcessWatcher(QThread)` |
| `core/wifi_optimizer.py` | Intel AX211 registry tweaks | `WifiOptimizer` |
| `core/network_optimizer.py` | TCP registry per interface GUID | `NetworkOptimizer` |
| `core/dns_switcher.py` | netsh DNS switch/restore | `DnsSwitcher` |
| `core/fps_booster.py` | Power plan, P-core affinity, timer res | `FpsBooster` |
| `core/nvidia_optimizer.py` | RTX 4060 registry + nvidia-smi | `NvidiaOptimizer` |
| `core/background_killer.py` | Suspend services/processes on game launch | `BackgroundKiller` |
| `core/bandwidth_manager.py` | DSCP QoS registry + SetPriorityClass | `BandwidthManager` |
| `core/ram_optimizer.py` | EmptyWorkingSet + file cache flush | `RamOptimizer` |

---

## Critical Design Rules

### StateGuard — always record before destructive operations
Before every registry write, service stop, or process suspend:
```python
state_guard.record_dns_backup(backup)
state_guard.add_paused_service("wuauserv")
state_guard.add_suspended_pid(pid)
```
`restore_all()` is called automatically on clean exit AND on crash recovery (checks if previous PID is dead via `psutil.pid_exists()`).

### Crash recovery flow
1. `StateGuard.check_and_heal()` runs on every startup
2. If `state.json` exists and its PID is dead → `restore_all()` → `clear()`
3. All restore operations are individually `try/except` guarded (best-effort)

### Wi-Fi optimizer — most impactful change
The Intel AX211 registry key ID varies per install. Always enumerate:
```python
HKLM\SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}\<0000..000N>
```
Match by `DriverDesc` containing `"Intel"` + `("Wi-Fi" or "AX" or "Wireless")`.

### P-core affinity — i7-13650HX specific
- P-cores: threads 0–11 → affinity mask `0x0FFF`
- E-cores: threads 12–19
- Detect 13th gen via `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0` → `ProcessorNameString` containing `"13"`
- Fall back to all-cores mask (`0xFFFFFFFF`) if detection fails

### Timer resolution
- Set: `NtSetTimerResolution(5000, True, byref(c_ulong()))` (0.5ms = 5000 × 100ns)
- Restore: `NtSetTimerResolution(156250, True, ...)` (15.625ms default)
- Check current with `NtQueryTimerResolution` before setting

---

## Adding a New Optimizer

1. Create `core/my_optimizer.py` with `apply(settings) -> dict` and `restore(backup)`
2. Add backup recording in `StateGuard` if it modifies persistent state
3. Create a UI toggle in the relevant tab (or add a new tab in `ui/tab_*.py`)
4. Wire the signal in `MainWindow._connect_signals()`
5. Add a unit test in `tests/test_my_optimizer.py`

---

## Testing

```bash
# Unit tests (no admin needed)
python -m pytest tests/ -v

# Integration check (run as admin)
python tests/integration_check.py
```

Test files mock subprocess and registry calls — never require real hardware.

---

## Dependencies

```
PyQt5==5.15.11       # GUI framework
PyQtGraph==0.13.7    # Real-time ping graphs
psutil==6.1.0        # Process/network info
pywin32==308         # Windows APIs (win32service, win32process, etc.)
pyinstaller==6.11.0  # Package to .exe
```

Install: `pip install -r requirements.txt`

---

## Packaging

```bash
pyinstaller --onefile --windowed --uac-admin \
  --icon=netboost.ico \
  --add-data "config;config" \
  --add-data "resources;resources" \
  --hidden-import=win32timezone \
  main.py
```

Rename `dist/main.exe` → `NetBoost.exe`.

---

## UI Feedback Pattern — Apply Button State Machine

Every tab with an "Apply" button implements a three-state visual cycle:

```python
# In each tab (tab_optimizer.py, tab_wifi.py, tab_fps.py):
def show_apply_success(self):
    self._apply_btn.setObjectName("successButton")
    self._apply_btn.setText("✓ Applied!")
    self._apply_btn.style().unpolish(self._apply_btn)
    self._apply_btn.style().polish(self._apply_btn)
    QTimer.singleShot(2500, self._reset_apply_btn)

def show_apply_error(self):
    self._apply_btn.setObjectName("dangerButton")
    # ... same pattern, reverts after 2500ms
```

- `unpolish` + `polish` is **required** — Qt caches resolved QSS per widget; changing `objectName` at runtime does not invalidate the cache without this pair
- `_on_*_apply()` handlers in `MainWindow` wrap `_apply_*()` in try/except and call the appropriate tab method
- `_apply_wifi()` and `_apply_fps()` re-raise after logging so the handler knows to show error state
- `_apply_optimizer()` raises `RuntimeError` if its `errors` list is non-empty

## StatusToast Widget

`ui/widgets/status_toast.py` — floating top-right overlay for apply feedback.

Key implementation notes:
- Uses `QGraphicsOpacityEffect` + `QPropertyAnimation` for fade — **not** `windowOpacity` (only works on top-level windows, has no effect on child widgets)
- Two separate animation objects (`_in_anim`, `_out_anim`) so `finished.connect(self.hide)` is wired exactly once — prevents accumulating connections if `show_message()` is called while a toast is active
- `MainWindow.resizeEvent` calls `self._toast._reposition()` to keep it anchored top-right when the window is resized

## Common Pitfalls

- `wuauserv` on Windows 11 often doesn't support PAUSE → `BackgroundKiller` falls back to Stop
- ICMP raw socket requires admin (satisfied) but may be blocked by some AV → falls back to `ping.exe`
- DSCP marking is ignored by most home routers — the service suspension is the actual bandwidth win
- PyQt5 5.15.11 is the last version with Python 3.13 wheels — do not upgrade to PyQt6 without testing all signals
- Never call UI methods directly from `PingMonitor` or `ProcessWatcher` threads — always use Qt signals
- Changing a widget's `objectName` at runtime requires `unpolish(widget)` + `polish(widget)` to force QSS re-evaluation
- `QPropertyAnimation(widget, b"windowOpacity")` only works for top-level windows — use `QGraphicsOpacityEffect` for child widget opacity animation

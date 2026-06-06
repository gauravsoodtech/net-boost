# CLAUDE.md — NetBoost Developer Guide

This file provides guidance to Claude Code when working with the NetBoost codebase.

## Project Overview

NetBoost is a Windows gaming network optimizer built with Python 3.13 + PyQt5. It reduces ping spikes, improves FPS consistency, and automates system tweaks for competitive gaming. Requires **administrator privileges** at runtime.

**Target hardware:** Intel i7-13650HX · NVIDIA RTX 4060 Laptop · Intel Wi-Fi 6E AX211 · Windows 11

---

## Version 2 / 2.1 Notes

- **UI theme:** Neo-Dark Glassmorphism QSS — `#00E5FF` cyans, `#05050A` backgrounds, 12px border radii.
- **Animations:** Use `QGraphicsOpacityEffect` + `QPropertyAnimation` for Tabs/Toasts. Never use instant transitions for new UI components.
- **Bug fixes:** false 100% ICMP loss fixed via rapid `ping.exe` fallback when raw socket blocks (`core/ping_monitor.py`); `cp1252` charset bug patched. Maintain coverage threshold.

## Version 2.1 Adaptive Advisor

Adaptive Mode is now **Adaptive Advisor**. It detects loss, ping spikes, and background contention, then queues recommendations in the Monitor tab instead of mutating Windows settings automatically. Any accepted recommendation must route through the existing `MainWindow._apply_wifi`, `_apply_optimizer`, or `_apply_fps` methods so `StateGuard`, transactions, applied badges, diagnostics, and restore paths stay consistent.

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
- `QThreadPool`: slow operations — Wi-Fi latency test (`_LatencyWorker`), RAM poll (`_RamPollWorker`), RAM optimize (`_RamOptimizeWorker`), service stop/start, route trace (`_TraceRouteWorker`), server discovery (`_DiscoverWorker`)

**Signal flow:** Core threads → Qt signals → `MainWindow` slots → UI tab methods. Never call UI methods directly from background threads.

---

## Core Modules

| Module | Responsibility | Key class |
|--------|---------------|-----------|
| `core/admin.py` | UAC elevation via `ShellExecuteW` | `is_admin()`, `elevate()` |
| `core/state_guard.py` | Crash-safe atomic state (`.tmp` → `os.replace`) | `StateGuard` |
| `core/profile_manager.py` | JSON profiles in `%APPDATA%\NetBoost\profiles\` | `ProfileManager` |
| `core/ping_monitor.py` | Raw ICMP socket, fallback to `ping.exe` | `PingMonitor(QThread)` |
| `core/process_watcher.py` | psutil polling every 1.5s; `set_poll_interval(ms)` for runtime adjustment | `ProcessWatcher(QThread)` |
| `core/wifi_optimizer.py` | Intel AX211 registry tweaks | `WifiOptimizer` |
| `core/network_optimizer.py` | TCP registry per interface GUID | `NetworkOptimizer` |
| `core/dns_switcher.py` | netsh DNS switch/restore | `DnsSwitcher` |
| `core/fps_booster.py` | Power plan, P-core affinity, timer res | `FpsBooster` |
| `core/nvidia_optimizer.py` | RTX 4060 registry + nvidia-smi | `NvidiaOptimizer` |
| `core/background_killer.py` | Suspend services/processes on game launch | `BackgroundKiller` |
| `core/bandwidth_manager.py` | DSCP QoS registry + SetPriorityClass | `BandwidthManager` |
| `core/ram_optimizer.py` | EmptyWorkingSet + file cache flush | `RamOptimizer` |
| `core/route_analyzer.py` | tracert parser, bottleneck detection, game server discovery | `_TraceRouteWorker`, `_DiscoverWorker`, `mark_bottlenecks()` |
| `core/network_diagnostics.py` | Honest leg-by-leg ping diagnostic (router / edge / game server) + plain-English verdict; pure logic, no Qt | `ping_target()`, `get_default_gateway()`, `find_active_server_ip()`, `build_verdict()` |
| `core/system_tweaks.py` | Force MSI Mode (GPU + Wi-Fi NIC), disable NDU service, disable NetworkThrottlingIndex | `apply_msi_mode_all`, `disable_ndu_service`, `disable_network_throttling` (+ matching `restore_*`) |
| `core/settings_risk.py` | Risk metadata for every toggle key (pure Python, no Qt) | `get_risk()`, `filter_by_level()` |
| `core/adaptive_engine.py` | Converts telemetry windows into advisor recommendations; no system mutation | `AdaptiveEngine`, `AdaptiveRecommendation` |
| `core/adaptive_advisor.py` | Session-local recommendation queue and settings merge helpers | `RecommendationQueue`, `merge_settings_patch()` |

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
6. If the optimizer writes the registry, **verify by read-back**: after each write,
   read the value back and record the outcome in a `core/apply_report.py` report
   stored under the backup's `_verify` key (Windows can accept a write that never
   persists — a silent no-op). See `wifi_optimizer`, `nvidia_optimizer`,
   `network_optimizer`. Surface failures with `apply_report.summarize(report, label)`
   in the `_on_*_apply` handler (mirrors the GPU/Wi-Fi warning toasts). `_verify`
   is `_`-prefixed so `restore()` loops skip it automatically.

---

## Testing

```bash
# Unit tests (no admin needed)
python -m pytest tests/ -v

# Integration check (run as admin)
python tests/integration_check.py
```

### Coverage gate

`pytest.ini` enforces `--cov=core --cov-fail-under=55` on every run. Before
claiming any task complete, confirm the gate is green:

```powershell
python -m pytest tests/ --cov=core --cov-report=term-missing
```

Target 75%+ before merging large changes; 95%+ for any new core module. Mock
`subprocess`, `winreg`, `psutil`, `win32service`, and `ctypes.windll.kernel32`
— never require real hardware. The `tests/conftest.py:qt_app` session fixture
provides a shared `QApplication` for tests that touch Qt widgets.

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

## Applied Status Badges

Each `_ToggleRow` in all three optimizer tabs has a hidden `● Active` green badge (QLabel) that appears after a successful Apply:

```python
# On each _ToggleRow:
def set_applied(self, applied: bool) -> None:
    self._status_badge.setVisible(applied)

# On each tab:
def mark_applied(self, settings: dict) -> None:
    for key, row in self._toggle_rows.items():
        row.set_applied(bool(settings.get(key)))

def clear_applied(self) -> None:
    for row in self._toggle_rows.values():
        row.set_applied(False)
```

- `mark_applied(settings)` is called in `MainWindow` after every successful apply
- `clear_applied()` is called after Restore Defaults

## Restore Defaults

All three optimizer tabs (Wi-Fi, FPS Boost, Optimizer) have a "Restore Defaults" button that:
1. Emits `settings_restored` signal → `MainWindow` calls the core restore method
2. Calls `clear_applied()` to remove Active badges
3. Resets all toggles back to ON (ready to apply again)

Key: Restore resets toggles to ON, not OFF — "restore" means undo system changes, not disable the UI.

**Per-tab restore scope** — each tab's restore is intentionally narrow; it only undoes its own backups and never touches other tabs' state:
- `_on_wifi_restore()` → reads `wifi_backup` from state → calls `WifiOptimizer.restore()`
- `_on_fps_restore()` → reads `fps_backup` AND `nvidia_backup` from state → calls `FpsBooster.restore()` then `NvidiaOptimizer.restore()` (both must be restored together because FPS apply writes both)
- `_on_optimizer_restore()` → reads `dns_backup`, `tcp_backup`, `paused_services`, `suspended_pids` from state → calls targeted restores on `DnsSwitcher`, `NetworkOptimizer`, `resume_service`, `resume_process` — does **not** call `restore_all()` (which would also wipe Wi-Fi/FPS backups and delete state.json)

## Game Mode

Game Mode (Dashboard toggle) applies all tab settings automatically when enabled:
- `_activate_game_mode()` calls `_apply_wifi`, `_apply_fps`, `_apply_optimizer` with current tab settings
- Sets `_game_mode_applied = True` flag
- **Toggle/badge sync:** each applied section calls `tab.set_settings(X)` **before** `tab.mark_applied(X)` (mirrors the manual `_on_*_apply` order) so the switch reflects the applied policy — otherwise the "● Active" badge lights up while the switch stays in its old position (badge on / switch off). `set_settings` works because `cs2_wifi_settings()`/`stable_ping_wifi_settings()` return a full 9-key dict (enabled `True`, rest `False`), so every toggle is set
- **Pre-game snapshot:** `_activate_game_mode` records `_pre_game_mode_settings = {wifi/fps/optimizer: tab.get_settings()}` once (guarded on `is None`) right after the `if not plan` guard, before overwriting the toggles
- `_deactivate_game_mode()` only calls `restore_all()` if `_game_mode_applied` is True — **does not touch manually applied settings**. When it does restore, it then puts the toggles back to `_pre_game_mode_settings`, calls `clear_applied()` on all three tabs, clears `_applied_settings`, and resets `_pre_game_mode_settings = None` — so closing the game returns switches to the user's selection and removes the now-stale badges. The snapshot is `None` when Game Mode never applied, so this block is skipped on the early-out path
- Toggle is debounced with a 300ms `QTimer` (`_game_mode_debounce`) to collapse rapid clicks
- **Tray icon toggle**: `TrayIcon._toggle_game_mode` calls `tab_dashboard.set_game_mode()` (visual only, blocks signals) **then** `main_window._on_game_mode_toggled()` directly — this two-step is required because `set_game_mode` uses `blockSignals(True)` to prevent recursive signal emission
- **Auto Game Mode**: `MainWindow._auto_game_mode` mirrors the Settings tab checkbox; `on_game_launched` auto-activates Game Mode when a game is detected if this flag is True

## DNS Provider Mapping

`tab_optimizer.py` combo box items use display names (`"Cloudflare 1.1.1.1"`) but `dns_switcher.apply()` expects short keys (`"cloudflare"`). Translation happens in `MainWindow._apply_optimizer()`:

```python
_dns_name_map = {
    "OpenDNS 208.67.222.222": "opendns",
    "Cloudflare 1.1.1.1":     "cloudflare",
    "Google 8.8.8.8":         "google",
    "Quad9 9.9.9.9":          "quad9",
    "Custom":                 "custom",
}
provider_key = _dns_name_map.get(settings["dns_provider"], settings["dns_provider"].lower())
```

Custom DNS fields are passed as `dns_primary` / `dns_secondary` (not `custom_dns_primary/secondary`).

## Tab Key Name Mapping (FPS Booster)

UI toggle keys in `tab_fps.py` are routed to **two** core modules by `MainWindow._apply_fps()`:

**CPU/Windows rows → `core/fps_booster.apply()`:**

| UI key (`_toggle_rows`) | `fps_booster.apply()` key |
|---|---|
| `power_plan` | `power_plan` |
| `pcores_affinity` | `pcores_affinity` |
| `timer_resolution` | `timer_resolution` |
| `game_dvr_off` | `game_dvr_off` |
| `sysmain_off` | `sysmain_off` |
| `visual_effects_off` | `visual_effects_off` |
| `fullscreen_opt_off` | `fullscreen_opt_off` |

**GPU rows → `core/nvidia_optimizer.apply()` (key translation happens in `_apply_fps()`):**

| UI key (`_toggle_rows`) | `nvidia_optimizer.apply()` key |
|---|---|
| `nvidia_max_perf` | `max_power` |
| `nvidia_ull` | `ull_mode` |
| `disable_hags` | `disable_hags` |

`disable_hags` sets `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\HwSchMode = 1`. **Requires a reboot to take effect.**

## Tab Key Name Mapping (Optimizer)

`tab_optimizer.py` key → what `MainWindow._apply_optimizer()` checks:
- `tcp_no_delay`, `tcp_ack_freq`, `tcp_window_scale` → triggers `NetworkOptimizer`
- `tcp_window_scale` is translated to `window_scaling` before passing to `NetworkOptimizer`
- `switch_dns` → triggers `DnsSwitcher`
- `pause_windows_update`, `pause_onedrive`, `pause_bits` → triggers `BackgroundKiller`
- `force_msi_mode` → triggers `system_tweaks.apply_msi_mode_all()` — backup recorded under `msi_backup`
- `disable_ndu` → triggers `system_tweaks.disable_ndu_service()` (`sc.exe config Ndu start=disabled`) — backup under `ndu_backup`
- `disable_network_throttling` → triggers `system_tweaks.disable_network_throttling()` — backup under `throttling_backup`

## StatusToast Widget

`ui/widgets/status_toast.py` — floating top-right overlay for apply feedback.

Key implementation notes:
- Uses `QGraphicsOpacityEffect` + `QPropertyAnimation` for fade — **not** `windowOpacity` (only works on top-level windows, has no effect on child widgets)
- Two separate animation objects (`_in_anim`, `_out_anim`) so `finished.connect(self.hide)` is wired exactly once — prevents accumulating connections if `show_message()` is called while a toast is active
- `MainWindow.resizeEvent` calls `self._toast._reposition()` to keep it anchored top-right when the window is resized
- Supports four styles: `"success"`, `"error"`, `"info"`, `"warning"` (amber ⚠)

## Settings Health Monitor

Three cooperating components implement the health monitoring system:

### `core/settings_risk.py` — Risk Registry
Pure Python, no Qt. Maps every UI toggle key → `level` (HIGH/MEDIUM/LOW), `tab`, `display`, `cause`, `advice`.

```python
from core.settings_risk import get_risk, filter_by_level

get_risk("minimize_roaming")      # → {"level": "HIGH", "tab": "wifi", ...}
get_risk("__unknown__")           # → None

filter_by_level(enabled_keys, min_level="MEDIUM")
# → [(key, entry), ...] sorted HIGH → MEDIUM, LOW excluded
```

- 27 entries covering all Wi-Fi, FPS, and Optimizer toggles
- `filter_by_level` is used by the pre-apply gate in all three `_on_*_apply` handlers

### `ui/widgets/risk_warning_dialog.py` — Pre-Apply Modal
`RiskWarningDialog(risky, parent)` — shown before applying when any MEDIUM/HIGH settings are enabled.
- "Apply Anyway" → `accept()` — apply proceeds
- "Review Settings" → `reject()` — apply aborts (slot returns early)
- **Not** shown in `_activate_game_mode()` (intentional — user explicitly triggered Game Mode)

### `DiagnosticPanel` in `ui/tab_monitor.py`
Collapsible `QFrame` appended below the stats bar in the Monitor tab.

- `update_applied_settings(applied: dict[str, dict])` — rebuilds rows; called after every successful apply/restore and after Game Mode activation
- `add_alert(message, culprit_key)` — prepends timestamped alert row; if `culprit_key` is given, adds a `[Disable <key>]` button that emits `disable_setting_requested`
- `TabMonitor.disable_setting_requested` signal is forwarded to `MainWindow._on_disable_setting(key)`
- `set_recommendations(recommendations)` updates the Pending Recommendations list; rows emit `recommendation_action_requested(id, action)` with `apply` or `dismiss`

### Adaptive Advisor in `MainWindow`

- `_on_adaptive_recommendation(recommendation)` stores session-local recommendations in `RecommendationQueue`, logs them, refreshes the Monitor tab, and shows a warning toast.
- `_on_recommendation_action(id, "apply")` merges the recommendation patch with the relevant tab settings and calls the existing apply path for that tab.
- `_on_recommendation_action(id, "dismiss")` removes the row, marks it handled in `AdaptiveEngine`, and leaves Windows settings untouched.
- Disabling `adaptive_mode` clears the pending recommendation queue and deactivates the engine.

### Health Monitoring in `MainWindow`

**Connectivity health** — called from `on_ping_reading` on every ping:
- If packet loss ≥15% and `minimize_roaming` or `prefer_6ghz` is in `_applied_settings["wifi"]` → amber warning toast + panel alert
- 60s cooldown (`_health_alert_timer`) between repeat alerts for the same condition

**GPU temperature** — `_gpu_temp_timer` (5s interval, `nvidia-smi`):
- Starts in `_on_fps_apply` success path when `nvidia_max_perf` or `nvidia_ull` is enabled
- Also started in `_activate_game_mode` if those settings are active
- Stops in `_on_fps_restore`
- Fires amber toast + panel alert when temp ≥85°C; resets alert flag when temp drops below 80°C

**Quick-disable** — `_on_disable_setting(key)`:
- Looks up `tab` from risk registry
- Calls `tab.set_settings({key: False})` to uncheck the toggle
- Removes key from `_applied_settings` and refreshes the panel
- Shows info toast: "unchecked — click Apply in its tab to take effect"

**Applied settings tracking** — `_applied_settings: dict[str, dict]`:
- Updated after every successful `_on_wifi_apply`, `_on_fps_apply`, `_on_optimizer_apply`
- Cleared per-tab on each restore (`_on_*_restore`)
- Populated for all three tabs in `_activate_game_mode`

## Tray Icon

`TrayIcon` in `ui/tray_icon.py` holds a `main_window` reference. `main.py` sets `window.tray = tray` after construction so `MainWindow` can call `tray.set_game_detected()`.

- Grey = idle, Green = Game Mode on, Yellow = game detected (mode off)
- `_on_game_mode_changed` is the tray's listener for `tab_dashboard.game_mode_toggled` — keeps checkmark in sync when game mode changes from the window
- `update_profiles(profiles, active)` must be called by `MainWindow` after any profile list change (create/delete/import) to keep the tray submenu current

## Bandwidth Tab — Suspend/Resume

`TabBandwidth._suspended_pids: set[int]` drives button labels ("Suspend"/"Resume") and row background color (dark red for suspended). When `MainWindow._on_process_suspend/resume` handles a click it must:
1. Call `tab_bandwidth.set_suspended(pid, True/False)` to update the set
2. Call `_on_bandwidth_refresh()` to re-render the table with the new state

## Profiles Tab — Duplicate vs New

`TabProfiles` exposes two distinct signals:
- `profile_new_requested()` — "New" button; `MainWindow._on_profile_new` creates a blank copy of "Default"
- `profile_duplicate_requested(str)` — "Duplicate" button; `MainWindow._on_profile_duplicate(source_name)` asks for a name then copies the **selected** profile

Do not emit `profile_new_requested` from `_on_duplicate` — it will always duplicate Default.

## Canonical Key Names

**Single source of truth: `core/setting_keys.py`.** It declares the canonical key
tuples (`WIFI_KEYS`, `FPS_KEYS`/`FPS_CPU_KEYS`/`FPS_GPU_KEYS`, `OPTIMIZER_KEYS` and
its `TCP_KEYS`/`DNS_KEYS`/`BACKGROUND_KILLER_KEYS`/`SYSTEM_TWEAK_KEYS` sub-groups),
plus `ALL_KEYS`, `TAB_BY_KEY`, and `PROFILE_SECTION_KEYS`. `core/stable_ping_policy.py`
re-exports these as its `*_SETTING_KEYS` tuples.

The keys originate from the UI toggle rows (`_toggle_rows` dicts in each tab). Every
backend module and profile JSON **must** use these exact strings — mismatches cause
silent no-ops. `tests/test_setting_keys.py` is the guard: it asserts the tabs,
`settings_risk.RISK_REGISTRY`, `stable_ping_policy`, and the profile schema all agree
with `setting_keys`, so any drift fails loudly instead of silently no-opping. When you
add or remove a toggle, update the tab row, the `settings_risk` entry, the profile
field, and `core/setting_keys.py` together (the partition-size tripwire test will remind
you).

The per-category lists below mirror `core/setting_keys.py` and show each key's backend route.

**Wi-Fi (`tab_wifi.py` → `core/wifi_optimizer.py`):**
`disable_lso`, `disable_interrupt_mod`, `disable_power_saving`, `minimize_roaming`, `max_tx_power`, `disable_bss_scan`, `prefer_6ghz`, `throughput_booster`, `disable_mimo_power_save`

**TCP (`tab_optimizer.py` → `core/network_optimizer.py`):**
`tcp_no_delay`, `tcp_ack_freq`, `tcp_window_scale` (translated to `window_scaling` before passing to backend)

**Background Killer (`tab_optimizer.py` → `core/background_killer.py`):**
`pause_windows_update`, `pause_onedrive`, `pause_bits`, `pause_telemetry`

**DNS (`tab_optimizer.py` → `core/dns_switcher.py`):**
`switch_dns`, `dns_provider` (display name), `dns_primary`, `dns_secondary`

**System Tweaks (`tab_optimizer.py` → `core/system_tweaks.py`):**
`force_msi_mode`, `disable_ndu`, `disable_network_throttling`

**FPS Booster CPU rows (`tab_fps.py` → `core/fps_booster.py`):**
`power_plan`, `pcores_affinity`, `timer_resolution`, `game_dvr_off`, `sysmain_off`, `visual_effects_off`, `fullscreen_opt_off`

**FPS Booster GPU rows (`tab_fps.py` → `core/nvidia_optimizer.py` via key translation):**
`nvidia_max_perf` → `max_power`, `nvidia_ull` → `ull_mode`, `disable_hags` → `disable_hags`

## Profile JSON Schema

All profile fields and their canonical keys (as of current schema):

```json
{
  "name": "Gaming",
  "dns": {"switch_dns": true, "dns_provider": "OpenDNS 208.67.222.222", "dns_primary": "208.67.222.222", "dns_secondary": "208.67.220.220"},
  "tcp_optimizer": {"tcp_no_delay": true, "tcp_ack_freq": true, "tcp_window_scale": true, "enabled": true},
  "bandwidth": {"game_priority": true, "enabled": true},
  "background_killer": {"pause_windows_update": true, "pause_onedrive": true, "pause_bits": true, "enabled": true},
  "fps_boost": {"power_plan": true, "pcores_affinity": true, "timer_resolution": true, "game_dvr_off": true,
                "nvidia_max_perf": true, "nvidia_ull": false, "disable_hags": false,
                "fullscreen_opt_off": true, "sysmain_off": true, "visual_effects_off": true, "enabled": true},
  "ping_monitor": {"host": "1.1.1.1", "interval_ms": 500},
  "game_list": [],
  "wifi_optimizer": {"disable_power_saving": true, "minimize_roaming": true, "prefer_6ghz": true,
                     "max_tx_power": true, "disable_bss_scan": true,
                     "throughput_booster": true, "disable_mimo_power_save": true, "enabled": true},
  "nvidia_optimizer": {"dynamic_pstate_off": true, "ull_mode": true, "max_power": true, "enabled": true},
  "system_tweaks": {"force_msi_mode": false, "disable_ndu": false, "disable_network_throttling": false, "enabled": false}
}
```

`_apply_profile()` in `MainWindow` maps profile sections to tabs: `wifi_optimizer` → `tab_wifi`, `fps_boost` → `tab_fps`, merge of `tcp_optimizer`+`dns`+`background_killer`+`system_tweaks` → `tab_optimizer`.

## Common Pitfalls

- `BackgroundKiller.apply()` checks `pause_windows_update` (not `pause_wupdate`) — always use the full key name
- `NvidiaOptimizer` is called from `_apply_fps()`, not `_apply_optimizer()` — GPU rows live in the FPS tab but route to `nvidia_optimizer`
- `disable_hags` writes to `GraphicsDrivers\HwSchMode` and requires a reboot — the registry write succeeds immediately but HAGS stays active until restart
- Timer resolution restore value is `156250` (15.625ms × 100ns) — **not** 156001 or 15600
- `wuauserv` on Windows 11 often doesn't support PAUSE → `BackgroundKiller` falls back to Stop
- ICMP raw socket requires admin (satisfied) but may be blocked by some AV → falls back to `ping.exe`
- DSCP marking is ignored by most home routers — the service suspension is the actual bandwidth win
- PyQt5 5.15.11 is the last version with Python 3.13 wheels — do not upgrade to PyQt6 without testing all signals
- Never call UI methods directly from `PingMonitor` or `ProcessWatcher` threads — always use Qt signals
- Changing a widget's `objectName` at runtime requires `unpolish(widget)` + `polish(widget)` to force QSS re-evaluation
- `QPropertyAnimation(widget, b"windowOpacity")` only works for top-level windows — use `QGraphicsOpacityEffect` for child widget opacity animation
- `ToggleSwitch.mouseReleaseEvent` must call only `super().mouseReleaseEvent(event)` — do NOT manually call `setChecked()` before super, or the toggle double-fires and cancels itself
- `_deactivate_game_mode()` must guard on `_game_mode_applied` flag — calling `restore_all()` unconditionally wipes manually applied settings
- `TabDashboard.set_game_mode()` uses `blockSignals(True)` — calling it alone does NOT activate Game Mode logic; must also call `MainWindow._on_game_mode_toggled()` directly (as the tray does)
- `OneDrive.exe` must NOT be in `PROCESSES_TO_SUSPEND` — it is handled conditionally inside the `pause_onedrive` block; listing it in both places would suspend it unconditionally and twice
- `_on_optimizer_restore()` must NOT call `state_guard.restore_all()` — that function restores all tabs and deletes state.json, destroying Wi-Fi and FPS backups. Use targeted restores on DNS/TCP/services only
- `_on_fps_restore()` must restore **both** `fps_backup` (via `FpsBooster`) and `nvidia_backup` (via `NvidiaOptimizer`) — `_apply_fps()` writes to both; restoring only one leaves NVIDIA registry changes live
- `background_killer.py` has no `SERVICES_TO_PAUSE` constant — services (wuauserv, BITS, OneSyncSvc) are handled by explicit `settings.get()` blocks inside `apply()`, not by iterating a shared list
- `bandwidth_manager.get_running_processes()` does NOT set `is_game` — `_on_bandwidth_refresh()` in `MainWindow` adds `proc["is_game"]` by checking `process_watcher._watch_set`; do not expect `is_game` to come from the backend
- `proc_poll_interval_ms` from `tab_settings` is applied via `process_watcher.set_poll_interval(ms)` in `_on_settings_changed` — `ProcessWatcher` stores it in `_poll_interval_ms` and picks it up on the next sleep cycle
- `PingMonitor._history` stores `(latency_ms, timed_out)` tuples — never plain floats; `get_jitter()` and `get_loss_pct()` both unpack the tuple
- `on_ping_reading` in `MainWindow` passes `latency_ms` directly to `add_reading` regardless of `timed_out`; the `timed_out` flag is passed separately — do not substitute `None` for `latency_ms`
- Dashboard `update_ping_stats(ping, jitter, loss)` accepts `None` for `ping`/`jitter` when offline — shows "--" badge instead of 0.0; always pass `None` when `_ping_history` is empty
- `_check_gpu_temp` was removed — GPU temp polling is now fully async via `_GpuTempPollWorker` (QRunnable) spawned by `_poll_gpu_temp`; `_on_gpu_temp(temp)` gets the result on the main thread via signal. Never run `nvidia-smi` on the Qt main thread — it blocks 100–300ms and flutters the ping display
- Monitor graph `add_reading()` on timeout must NOT plot `0.0` — use the running average (`self._sum_ping / self._count`) so timeouts render as a flat line rather than a downward spike to zero
- `_apply_fps()` game PID lookup (psutil loop) is wrapped in its own inner `try/except` separate from the outer FPS apply block — a transient `AccessDenied` from psutil must not prevent FPS settings from being applied
- `MsMpEng.exe` (Windows Defender) must NOT be in `PROCESSES_TO_SUSPEND` — suspending it degrades Windows Network Inspection Service and causes Windows health-check interference that manifests as in-game latency spikes
- `disable_lso` writes `*LsoV2IPv4=0` and `*LsoV2IPv6=0` to the Intel adapter key — primary fix for 20–200 ms in-game ping bursts from NIC packet batching (Large Send Offload)
- `disable_interrupt_mod` writes `InterruptModeration=0` to the Intel adapter key — forces per-packet CPU interrupts, reducing jitter; slightly increases CPU utilisation
- **Wi-Fi advanced params only go live after a miniport reset.** Intel reads `*LsoV2IPv4/6`, `InterruptModeration`, `PowerSavingMode`, `TxPowerLevel`, `MIMOPowerSaveMode`, etc. at driver init — a raw registry write persists and read-back-verifies but the running driver keeps old values until the adapter power-cycles, silently no-opping the anti-jitter tweaks. `wifi_optimizer.apply()` flags `_requires_restart` (set only when a verified write *changed* the value: old `backup[value_name]` ≠ target) and captures `_driver_desc`. `MainWindow._maybe_restart_wifi_adapter(backup)` spawns `_WifiRestartWorker` (async, off Qt thread) → `wifi_optimizer.restart_adapter(driver_desc)` runs `Restart-NetAdapter -InterfaceDescription <desc> -Confirm:$false` (regex-match fallback when no desc), dropping Wi-Fi ~5-10 s. Called from **every** real Wi-Fi apply path: `_on_wifi_apply`, `_activate_game_mode`, `_apply_recommendation`, `_on_disable_setting`. Change-detection skips the restart on identical re-applies and post-reboot (driver already read registry at boot) — no needless disconnect. `_on_wifi_restart_done(ok, error)` toasts success / "disable-enable in Device Manager or reboot" on failure
- `restart_adapter` never raises — timeout/launch failure returns `{"ok": False, "error": ...}` so a failed power-cycle degrades to a manual-action toast instead of crashing the apply
- `pause_telemetry` stops/pauses `DiagTrack` (Connected User Experiences and Telemetry) — it sends large telemetry bundles during gaming and competes for bandwidth; `_apply_optimizer` trigger condition must include `pause_telemetry` (same BackgroundKiller path as `pause_windows_update`)
- `Tcp1323Opts` is set to `1` (window scaling only) — **not** `3`; value `3` enables RFC 1323 timestamps which add 12 bytes per packet overhead with no benefit when `GlobalMaxTcpWindowSize` is 65535
- `TabMonitor` jitter uses consecutive-difference (`|current − prev_latency|`), not deviation from running average — `_prev_latency` must be updated on every non-timeout reading and reset in `_reset_stats()`
- `update_ping_stats()` in `TabDashboard` must call `self._badge_loss.set_value(loss)` to actually display the loss percentage — the colour update alone does not set the badge text
- `DiagnosticPanel.update_applied_settings()` clear loop must guard `item.widget() is not self._no_settings_lbl` before `deleteLater()` — the placeholder label is reused; deleting it causes use-after-free next call (same pattern `clear_alerts()` uses for `_no_alerts_lbl`)
- Auto game mode activation (`elif self._auto_game_mode:` in `on_game_launched`) calls `tab_dashboard.set_game_mode(True)` with signals blocked — must also call `tray._on_game_mode_changed(True)` directly, else the tray icon stays grey/yellow and the "Enable Game Mode" checkmark stays unchecked
- `tray.update_profiles(profiles, active)` must be called by `MainWindow` after every profile list change (`_on_profile_load`, `_on_profile_delete`, `_on_profile_new`, `_on_profile_duplicate`, `_on_profile_import`) — and once on startup in `main.py` after the tray is created — the tray profile submenu is never auto-synced
- `_ping_raw` timeout does NOT fall through to `_ping_subprocess` — subprocess fallback triggers only on `PermissionError`/`OSError` during socket creation, not on recv timeout. Vanguard's kernel driver (vgk.sys) allows raw ICMP socket creation but intercepts echo replies at driver level → 100% loss on `_ping_raw` while `ping.exe` works. Fix: track `_raw_consecutive_timeouts`; after 5 consecutive raw timeouts, skip raw and use subprocess permanently for the session
- `_set_fullscreen_opt` in `fps_booster.py` must check `flag not in existing` before appending `DISABLEDXMAXIMIZEDWINDOWEDMODE` — else every Apply/Game Mode appends a duplicate, accumulating 10+ copies in the registry key
- `wifi_optimizer.apply()` returns `backup["_adapter_found"] = False` when the Intel AX211 key enumeration fails — `_on_wifi_apply` in `MainWindow` must check this flag and show a warning toast; a missing adapter key means LSO was never disabled and spikes will persist silently
- `PingMonitor.host` property exposes `self._host` read-only — use it in `_on_game_server_found` to snapshot the current host before switching, so `on_game_exited` can restore it exactly
- `_check_connectivity_health` packet-loss threshold is **8%** (not 15%) — 15% is too high for Valorant where even 5% loss is noticeable; the lower threshold catches micro-drops from 6GHz band reconnects and AP handoffs before they accumulate
- `psutil.Process(pid).net_connections()` returns 0 for Vanguard-protected Valorant — its kernel driver hides the game's UDP connections from user-mode; use `netstat -n` or `Get-NetTCPConnection` system-wide to find server IPs. `_DiscoverWorker` silently gets an empty list and exhausts retries — expected when Vanguard runs
- `TabRoute.server_found` is a `pyqtSignal(str)` on `TabRoute` itself (not on `_DiscoverWorkerSignals`) — `MainWindow` connects `tab_route.server_found` → `_on_game_server_found(ip)` to re-target the ping monitor; `TabRoute._on_server_found` emits it after storing the IP and before starting the trace
- `force_msi_mode` writes `MSISupported=1` under each matched PCI device's `Device Parameters\Interrupt Management\MessageSignaledInterruptProperties` subkey — **requires reboot**. May fail with `PermissionError` on hardened systems (Enum subtree wants SYSTEM access); `apply_msi_mode_all()` then sets `backup["_access_denied"] = True` and `_apply_optimizer` surfaces it as a separate amber toast
- `disable_ndu` runs `sc.exe config Ndu start=disabled` and reads the prior `Start` DWORD into backup so restore returns the real prior value (not a hard-coded default) — **requires reboot** to unload the kernel driver; Task Manager → App History → Network usage shows zeros until restored
- MSI / NDU / throttling backups live under `msi_backup`, `ndu_backup`, `throttling_backup` in `state.json` and are picked up by `_BACKUP_DICT_KEYS` in `state_guard.py`. `_restore_entry` dispatches each to the matching `system_tweaks.restore_*` function, mirroring the wifi / nvidia / fps restore blocks above it
- Stable-ping Game Mode (`core/stable_ping_policy.py`) is **Wi-Fi-only for both games**. `build_game_mode_plan` returns only a `wifi` section — Valorant and CS2 both get the same conservative 4-key subset (`CS2_WIFI_ENABLED_KEYS == VALORANT_WIFI_ENABLED_KEYS`); `disable_mimo_power_save` and `disable_bss_scan` are manual-only toggles, not part of either auto plan. FPS Booster, Optimizer (background killer / TCP / DNS / `system_tweaks`), and per-app DSCP QoS are **never** auto-applied for stable-ping games — they caused stutter/thermal-throttle/confusion and stay manual (tabs + profiles). MainWindow DSCP plumbing (`_apply_game_mode_dscp`, `_game_mode_dscp_policy`, deactivate teardown) stays as defensive cleanup but is no longer reached by the plan. The `CS2 Stable Ping` seed profile in `profile_manager.py` is likewise Wi-Fi-only

## Route Analyzer Tab

`TabRoute` in `ui/tab_route.py` + `core/route_analyzer.py`.

**Public API called by MainWindow:**
- `on_game_detected(exe: str, pid: int)` — updates status LED/label, schedules server discovery after 3s delay
- `on_game_exited()` — resets status bar; table kept readable

**Server discovery flow:**
1. `on_game_detected` fires `QTimer.singleShot(3000, _try_discover_server)` — gives game time to connect
2. `_DiscoverWorker` calls `discover_game_server(pid)` → `psutil.Process(pid).net_connections(kind='inet')` → first public non-private remote IP
3. On `found`: pre-fills `_manual_ip_input`, emits `TabRoute.server_found(ip)` signal → `MainWindow._on_game_server_found(ip)` switches `PingMonitor` to game server IP + updates Dashboard ping label; auto-starts trace
4. On `not_found`: retries once after 5s (`_MAX_DISCOVER_RETRIES = 2`), then shows "Enter IP manually"

**Tracert parsing (`_parse_tracert_line`):**
- Regex: `^\s*(?P<hop>\d+)\s+(?P<r1>[<\d]+\s*ms|\*)\s+(?P<r2>...)\s+(?P<r3>...)\s+(?P<rest>.+?)\s*$`
- `<1 ms` → 0.5 (so bottleneck math works); `*` → None
- `is_timeout = True` only when ALL three probes are `*`
- IP extracted from `rest` field only when not timeout

**Bottleneck detection (`mark_bottlenecks`):**
- Threshold: 15ms jump from previous **responsive** hop
- Timeout hops do NOT advance `prev_ms` — a run of timeouts won't mask a real bottleneck at the next responsive hop
- First responsive hop is never a bottleneck (no baseline)

**Row colors (programmatic — QSS cannot target QTableWidgetItem):**
- Timeout: bg `#2a0a0a`, fg `#f44336`
- Bottleneck: bg `#2a2200`, fg `#ff9800`; status cell text → "Bottleneck"
- OK: fg `#4caf50`

**`_TraceRouteWorker` cancel pattern:**
- `cancel()` sets `self._cancelled = True` and calls `self._proc.terminate()`
- After loop, checks `if self._cancelled: return` — `finished` signal is NOT emitted on cancel
- `_on_trace_clicked` cancels any in-progress worker before starting a new one

**Diagnose Ping (honest leg-by-leg diagnostic):**
The "Diagnose Ping" button answers "why is my in-game ping bad when 1.1.1.1 is fine?"
by measuring each leg of the path separately and printing a plain-English verdict —
because NetBoost's Wi-Fi registry tweaks can only affect the *local link*, never the
route to the game server.
- `core/network_diagnostics.py` (pure, no Qt): `get_default_gateway()` (parses
  `route print -4`, lowest-metric default route), `ping_target(host, count)` (parses
  `ping.exe` → `{avg/min/max/jitter/loss, reachable}`), `find_active_server_ip(pid)`
  (tries `route_analyzer.discover_game_server` then falls back to a system-wide
  `netstat -n` ESTABLISHED-TCP scan — still returns `None` for Vanguard-protected UDP
  games, which the verdict handles), `build_verdict(gateway, edge, server, hops)`
  (classifies which leg is at fault).
- `_DiagnoseWorker` (QRunnable in `ui/tab_route.py`) runs the sequence off the Qt
  thread: gateway ping → edge ping (`EDGE_HOST = 1.1.1.1`) → server discovery/ping →
  `route_analyzer.trace_route` → `build_verdict`. Emits `progress(str)` per step and
  `finished(dict)`. **Lives in `tab_route.py`, NOT `network_diagnostics.py`** — keeps
  the core module Qt-free and avoids a circular import (`network_diagnostics` imports
  `route_analyzer`).
- Verdict branches: bad gateway → local Wi-Fi (the one case the Wi-Fi tab can help);
  good gateway + bad edge → ISP first mile; good gateway/edge + bad server/bottleneck →
  route to the game server (server region / ISP peering — not fixable locally); server
  unmeasurable → ask for manual IP; all healthy → likely transient bufferbloat from
  background apps. The verdict explicitly states when NetBoost cannot fix it.
- `find_active_server_ip` reuses the PID `TabRoute` already stores from
  `on_game_detected` — no MainWindow change needed.

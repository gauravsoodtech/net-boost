"""
NetBoost Main Window
QMainWindow with QTabWidget, wires all signals between core and UI
"""
import logging
import os
from collections import deque

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QStatusBar, QLabel, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QCloseEvent

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, state_guard=None, profile_manager=None, parent=None):
        super().__init__(parent)
        self.state_guard = state_guard
        self.profile_manager = profile_manager
        self.ping_monitor = None   # set by main.py after creation
        self.process_watcher = None

        # Rolling stats
        self._ping_history = deque(maxlen=120)
        self._loss_count = 0
        self._total_count = 0
        self._current_game = None
        self._game_mode_active = False
        self._game_mode_applied = False   # True only if Game Mode itself applied changes
        self._game_mode_pending = False   # latest value for debounce
        self._auto_game_mode = False      # mirrors tab_settings auto_game_mode checkbox
        self._ram_freed_mb = 0
        self.tray = None                  # set by main.py after TrayIcon is created

        # Optimizer instances (lazy-created when needed)
        self._wifi_optimizer = None
        self._nvidia_optimizer = None
        self._fps_booster = None
        self._ram_optimizer = None
        self._dns_switcher = None
        self._network_optimizer = None
        self._background_killer = None
        self._bandwidth_manager = None

        self._setup_ui()
        self._connect_signals()
        self._check_battery()
        self._init_toast()

        # Battery check timer
        self._battery_timer = QTimer(self)
        self._battery_timer.timeout.connect(self._check_battery)
        self._battery_timer.start(30000)  # every 30s

        # Debounce timer for Game Mode toggle — collapses rapid clicks into one action
        self._game_mode_debounce = QTimer(self)
        self._game_mode_debounce.setSingleShot(True)
        self._game_mode_debounce.setInterval(300)
        self._game_mode_debounce.timeout.connect(self._apply_game_mode_toggle)

        # Applied-settings tracking for health diagnostics
        self._applied_settings: dict[str, dict] = {}

        # Health alert cooldown (60s between repeat alerts for the same condition)
        self._health_alert_cooldown = False
        self._health_alert_timer = QTimer(self)
        self._health_alert_timer.setSingleShot(True)
        self._health_alert_timer.setInterval(60_000)
        self._health_alert_timer.timeout.connect(
            lambda: setattr(self, "_health_alert_cooldown", False)
        )

        # GPU temperature polling (5s; only while nvidia settings are applied)
        self._gpu_temp_timer = QTimer(self)
        self._gpu_temp_timer.setInterval(5000)
        self._gpu_temp_timer.timeout.connect(self._check_gpu_temp)
        self._gpu_throttle_alerted = False

    # ------------------------------------------------------------------ UI setup

    def _setup_ui(self):
        self.setWindowTitle("NetBoost — Gaming Network Optimizer")
        self.setMinimumSize(900, 650)
        self.resize(1050, 720)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        layout.addWidget(self.tabs)

        self._init_tabs()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status_label = QLabel("Ready")
        self.status_bar.addWidget(self._status_label)

        self._version_label = QLabel("NetBoost v1.0.0")
        self._version_label.setObjectName("dimLabel")
        self.status_bar.addPermanentWidget(self._version_label)

    def _init_tabs(self):
        """Lazily import and create all tab widgets."""
        from ui.tab_dashboard import TabDashboard
        from ui.tab_monitor import TabMonitor
        from ui.tab_wifi import TabWifi
        from ui.tab_fps import TabFps
        from ui.tab_optimizer import TabOptimizer
        from ui.tab_bandwidth import TabBandwidth
        from ui.tab_profiles import TabProfiles
        from ui.tab_settings import TabSettings

        self.tab_dashboard = TabDashboard()
        self.tab_monitor = TabMonitor()
        self.tab_wifi = TabWifi()
        self.tab_fps = TabFps()
        self.tab_optimizer = TabOptimizer()
        self.tab_bandwidth = TabBandwidth()
        self.tab_profiles = TabProfiles()
        self.tab_settings = TabSettings()

        self.tabs.addTab(self.tab_dashboard, "Dashboard")
        self.tabs.addTab(self.tab_monitor, "Monitor")
        self.tabs.addTab(self.tab_wifi, "Wi-Fi")
        self.tabs.addTab(self.tab_fps, "FPS Boost")
        self.tabs.addTab(self.tab_optimizer, "Optimizer")
        self.tabs.addTab(self.tab_bandwidth, "Bandwidth")
        self.tabs.addTab(self.tab_profiles, "Profiles")
        self.tabs.addTab(self.tab_settings, "Settings")

        # Populate profiles if available
        if self.profile_manager:
            profiles = self.profile_manager.list_profiles()
            active = self.profile_manager.get_active().get("name", "Default") if profiles else "Default"
            self.tab_profiles.set_profiles(profiles, active)
            self.tab_dashboard.set_active_profile(active)

    def _init_toast(self):
        from ui.widgets.status_toast import StatusToast
        self._toast = StatusToast(self)

    def _connect_signals(self):
        """Wire UI signals to handler methods."""
        self.tab_dashboard.game_mode_toggled.connect(self._on_game_mode_toggled)
        self.tab_monitor.host_changed.connect(self._on_host_changed)
        self.tab_wifi.settings_applied.connect(self._on_wifi_apply)
        self.tab_wifi.settings_restored.connect(self._on_wifi_restore)
        self.tab_fps.settings_applied.connect(self._on_fps_apply)
        self.tab_fps.settings_restored.connect(self._on_fps_restore)
        self.tab_optimizer.settings_applied.connect(self._on_optimizer_apply)
        self.tab_optimizer.settings_restored.connect(self._on_optimizer_restore)
        self.tab_optimizer.ram_optimize_requested.connect(self._on_ram_optimize)
        self.tab_bandwidth.refresh_requested.connect(self._on_bandwidth_refresh)
        self.tab_bandwidth.priority_change_requested.connect(self._on_priority_change)
        self.tab_bandwidth.suspend_requested.connect(self._on_process_suspend)
        self.tab_bandwidth.resume_requested.connect(self._on_process_resume)
        self.tab_profiles.profile_load_requested.connect(self._on_profile_load)
        self.tab_profiles.profile_delete_requested.connect(self._on_profile_delete)
        self.tab_profiles.profile_new_requested.connect(self._on_profile_new)
        self.tab_profiles.profile_duplicate_requested.connect(self._on_profile_duplicate)
        self.tab_profiles.profile_import_requested.connect(self._on_profile_import)
        self.tab_profiles.profile_export_requested.connect(self._on_profile_export)
        self.tab_settings.settings_changed.connect(self._on_settings_changed)
        self.tab_settings.game_list_changed.connect(self._on_game_list_changed)
        self.tab_monitor.disable_setting_requested.connect(self._on_disable_setting)

    # ------------------------------------------------------------------ Ping signals

    @pyqtSlot(str, float, bool)
    def on_ping_reading(self, host: str, latency_ms: float, timed_out: bool):
        """Called from PingMonitor thread via Qt signal (thread-safe)."""
        self._total_count += 1
        if timed_out:
            self._loss_count += 1
            latency_ms = 0.0
        else:
            self._ping_history.append(latency_ms)

        # Compute stats
        recent = list(self._ping_history)[-20:] if self._ping_history else [0]
        avg_ping = sum(recent) / len(recent) if recent else 0
        jitter = self._compute_jitter(recent)
        loss_pct = (self._loss_count / self._total_count * 100) if self._total_count > 0 else 0

        self.tab_dashboard.update_ping_stats(avg_ping, jitter, loss_pct)
        self.tab_monitor.add_reading(host, latency_ms if not timed_out else None, timed_out)
        self._check_connectivity_health(loss_pct)

    def _compute_jitter(self, readings: list) -> float:
        if len(readings) < 2:
            return 0.0
        diffs = [abs(readings[i] - readings[i-1]) for i in range(1, len(readings))]
        return sum(diffs) / len(diffs)

    # ------------------------------------------------------------------ Game detection

    @pyqtSlot(str)
    def on_game_launched(self, exe_name: str):
        logger.info(f"Game launched: {exe_name}")
        self._current_game = exe_name
        self.tab_dashboard.set_game_detected(exe_name)
        if self.tray:
            self.tray.set_game_detected(exe_name)
        self._set_status(f"Game detected: {exe_name}")

        if self._game_mode_active:
            self._activate_game_mode(exe_name)
        elif self._auto_game_mode:
            # Auto-enable Game Mode when a game is detected
            self._game_mode_active = True
            self.tab_dashboard.set_game_mode(True)
            self._activate_game_mode(exe_name)

    @pyqtSlot(str)
    def on_game_exited(self, exe_name: str):
        logger.info(f"Game exited: {exe_name}")
        self._current_game = None
        self.tab_dashboard.set_game_detected(None)
        if self.tray:
            self.tray.set_game_detected(None)
        self._set_status("No game detected")

        if self._game_mode_active:
            self._deactivate_game_mode()

    # ------------------------------------------------------------------ Game Mode

    @pyqtSlot(bool)
    def _on_game_mode_toggled(self, enabled: bool):
        # Store latest value and (re)start the debounce timer — rapid clicks collapse into one
        self._game_mode_pending = enabled
        self._game_mode_debounce.start()

    def _apply_game_mode_toggle(self):
        """Called once after the debounce timer fires."""
        enabled = self._game_mode_pending
        self._game_mode_active = enabled
        if enabled:
            self._set_status("Game Mode activated")
            self._activate_game_mode(self._current_game)
        else:
            self._set_status("Game Mode deactivated")
            self._deactivate_game_mode()

    def _activate_game_mode(self, exe_name: str):
        """Apply all tab settings when Game Mode is enabled."""
        logger.info(f"Activating game mode" + (f" for {exe_name}" if exe_name else ""))
        try:
            self._apply_wifi(self.tab_wifi.get_settings())
        except Exception as e:
            logger.warning(f"Wi-Fi game mode apply failed: {e}")
        try:
            self._apply_fps(self.tab_fps.get_settings())
        except Exception as e:
            logger.warning(f"FPS game mode apply failed: {e}")
        try:
            self._apply_optimizer(self.tab_optimizer.get_settings())
        except Exception as e:
            logger.warning(f"Optimizer game mode apply failed: {e}")
        self._game_mode_applied = True
        self._applied_settings["wifi"] = self.tab_wifi.get_settings()
        self._applied_settings["fps"] = self.tab_fps.get_settings()
        self._applied_settings["optimizer"] = self.tab_optimizer.get_settings()
        self.tab_monitor.update_applied_settings(self._applied_settings)
        # Start GPU temp polling if nvidia settings are on
        fps = self._applied_settings.get("fps", {})
        if fps.get("nvidia_max_perf") or fps.get("nvidia_ull"):
            self._gpu_temp_timer.start()
        self._toast.show_message("Game Mode: all optimizations applied", "success")

    def _deactivate_game_mode(self):
        """Restore settings only if Game Mode was the one that applied them."""
        if not self._game_mode_applied:
            logger.info("Game Mode deactivated — no Game Mode changes to restore")
            return
        logger.info("Deactivating game mode, restoring settings")
        if self.state_guard:
            try:
                self.state_guard.restore_all()
                self._game_mode_applied = False
            except Exception as e:
                logger.error(f"restore_all failed: {e}")
        self._toast.show_message("Game Mode: settings restored", "info")

    # ------------------------------------------------------------------ Wi-Fi

    @pyqtSlot(dict)
    def _on_wifi_apply(self, settings: dict):
        from core.settings_risk import filter_by_level
        from ui.widgets.risk_warning_dialog import RiskWarningDialog
        from PyQt5.QtWidgets import QDialog
        enabled_keys = [k for k, v in settings.items() if v]
        risky = filter_by_level(enabled_keys, min_level="MEDIUM")
        if risky:
            dlg = RiskWarningDialog(risky, parent=self)
            if dlg.exec_() == QDialog.Rejected:
                return
        try:
            self._apply_wifi(settings)
            self.tab_wifi.set_settings(settings)
            self.tab_wifi.mark_applied(settings)
            self.tab_wifi.show_apply_success()
            self._toast.show_message("Wi-Fi optimizations applied", "success")
            self._applied_settings["wifi"] = settings
            self.tab_monitor.update_applied_settings(self._applied_settings)
        except Exception:
            self.tab_wifi.show_apply_error()
            self._toast.show_message("Wi-Fi apply failed", "error")

    def _apply_wifi(self, settings: dict):
        try:
            from core.wifi_optimizer import WifiOptimizer
            if self._wifi_optimizer is None:
                self._wifi_optimizer = WifiOptimizer()
            backup = self._wifi_optimizer.apply(settings)
            if self.state_guard:
                self.state_guard.record_wifi_backup(backup)
            self._set_status("Wi-Fi optimizations applied")
        except Exception as e:
            logger.error(f"Wi-Fi apply error: {e}")
            self._set_status(f"Wi-Fi error: {e}")
            raise

    @pyqtSlot()
    def _on_wifi_restore(self):
        self.tab_wifi.clear_applied()
        self._applied_settings.pop("wifi", None)
        self.tab_monitor.update_applied_settings(self._applied_settings)
        try:
            if self._wifi_optimizer and self.state_guard:
                state = self.state_guard.get_state()
                backup = state.get("wifi_backup", {})
                if backup:
                    self._wifi_optimizer.restore(backup)
                    self._set_status("Wi-Fi settings restored")
        except Exception as e:
            logger.error(f"Wi-Fi restore error: {e}")

    # ------------------------------------------------------------------ FPS

    @pyqtSlot(dict)
    def _on_fps_apply(self, settings: dict):
        from core.settings_risk import filter_by_level
        from ui.widgets.risk_warning_dialog import RiskWarningDialog
        from PyQt5.QtWidgets import QDialog
        enabled_keys = [k for k, v in settings.items() if v]
        risky = filter_by_level(enabled_keys, min_level="MEDIUM")
        if risky:
            dlg = RiskWarningDialog(risky, parent=self)
            if dlg.exec_() == QDialog.Rejected:
                return
        try:
            self._apply_fps(settings)
            self.tab_fps.set_settings(settings)
            self.tab_fps.mark_applied(settings)
            self.tab_fps.show_apply_success()
            self._toast.show_message("FPS optimizations applied", "success")
            self._applied_settings["fps"] = settings
            self.tab_monitor.update_applied_settings(self._applied_settings)
            if settings.get("nvidia_max_perf") or settings.get("nvidia_ull"):
                self._gpu_temp_timer.start()
        except Exception:
            self.tab_fps.show_apply_error()
            self._toast.show_message("FPS apply failed", "error")

    def _apply_fps(self, settings: dict):
        try:
            from core.fps_booster import FpsBooster
            if self._fps_booster is None:
                self._fps_booster = FpsBooster()

            # Find game PID if running
            game_pid = None
            if self._current_game:
                import psutil
                for proc in psutil.process_iter(["name", "pid"]):
                    if proc.info["name"] and proc.info["name"].lower() == self._current_game.lower():
                        game_pid = proc.info["pid"]
                        break

            backup = self._fps_booster.apply(settings, game_pid=game_pid)
            if self.state_guard:
                self.state_guard.record_fps_backup(backup)

            # Apply GPU settings via nvidia_optimizer (FPS tab GPU rows)
            if settings.get("nvidia_max_perf") or settings.get("nvidia_ull") or settings.get("disable_hags"):
                try:
                    from core.nvidia_optimizer import NvidiaOptimizer
                    if self._nvidia_optimizer is None:
                        self._nvidia_optimizer = NvidiaOptimizer()
                    nvidia_settings = {
                        "max_power":          settings.get("nvidia_max_perf", False),
                        "ull_mode":           settings.get("nvidia_ull", False),
                        "disable_hags":       settings.get("disable_hags", False),
                    }
                    nvidia_backup = self._nvidia_optimizer.apply(nvidia_settings)
                    if self.state_guard:
                        self.state_guard.record_nvidia_backup(nvidia_backup)
                except Exception as e:
                    logger.warning(f"NVIDIA optimizer apply failed: {e}")

            self._set_status("FPS optimizations applied")
        except Exception as e:
            logger.error(f"FPS apply error: {e}")
            self._set_status(f"FPS error: {e}")
            raise

    @pyqtSlot()
    def _on_fps_restore(self):
        self.tab_fps.clear_applied()
        self._applied_settings.pop("fps", None)
        self.tab_monitor.update_applied_settings(self._applied_settings)
        self._gpu_temp_timer.stop()
        self._gpu_throttle_alerted = False
        try:
            if self._fps_booster and self.state_guard:
                state = self.state_guard.get_state()
                backup = state.get("fps_backup", {})
                if backup:
                    self._fps_booster.restore(backup)
                    self._set_status("FPS settings restored")
        except Exception as e:
            logger.error(f"FPS restore error: {e}")

    # ------------------------------------------------------------------ Optimizer (TCP/DNS/Services)

    @pyqtSlot(dict)
    def _on_optimizer_apply(self, settings: dict):
        from core.settings_risk import filter_by_level
        from ui.widgets.risk_warning_dialog import RiskWarningDialog
        from PyQt5.QtWidgets import QDialog
        enabled_keys = [k for k, v in settings.items() if v]
        risky = filter_by_level(enabled_keys, min_level="MEDIUM")
        if risky:
            dlg = RiskWarningDialog(risky, parent=self)
            if dlg.exec_() == QDialog.Rejected:
                return
        try:
            self._apply_optimizer(settings)
            self.tab_optimizer.set_settings(settings)
            self.tab_optimizer.mark_applied(settings)
            self.tab_optimizer.show_apply_success()
            self._toast.show_message("Network optimizations applied", "success")
            self._applied_settings["optimizer"] = settings
            self.tab_monitor.update_applied_settings(self._applied_settings)
        except Exception:
            self.tab_optimizer.show_apply_error()
            self._toast.show_message("Optimizer apply failed", "error")

    def _apply_optimizer(self, settings: dict):
        errors = []

        # TCP
        if settings.get("tcp_no_delay") or settings.get("tcp_ack_freq") or settings.get("tcp_window_scale"):
            try:
                from core.network_optimizer import NetworkOptimizer
                if self._network_optimizer is None:
                    self._network_optimizer = NetworkOptimizer()
                net_settings = dict(settings)
                net_settings["window_scaling"] = settings.get("tcp_window_scale")
                backup = self._network_optimizer.apply(net_settings)
                if self.state_guard:
                    self.state_guard.record_tcp_backup(backup)
            except Exception as e:
                logger.error(f"TCP apply error: {e}")
                errors.append("TCP")

        # DNS
        if settings.get("switch_dns") and settings.get("dns_provider"):
            try:
                from core.dns_switcher import DnsSwitcher
                if self._dns_switcher is None:
                    self._dns_switcher = DnsSwitcher()
                _dns_name_map = {
                    "Cloudflare 1.1.1.1": "cloudflare",
                    "Google 8.8.8.8":     "google",
                    "Quad9 9.9.9.9":      "quad9",
                    "Custom":             "custom",
                }
                provider_key = _dns_name_map.get(settings["dns_provider"],
                                                  settings["dns_provider"].lower())
                backup = self._dns_switcher.apply(
                    provider_key,
                    custom_primary=settings.get("dns_primary"),
                    custom_secondary=settings.get("dns_secondary"),
                )
                if self.state_guard:
                    self.state_guard.record_dns_backup(backup)
            except Exception as e:
                logger.error(f"DNS apply error: {e}")
                errors.append("DNS")

        # Background killer
        if settings.get("pause_windows_update") or settings.get("pause_onedrive") or settings.get("pause_bits"):
            try:
                from core.background_killer import BackgroundKiller
                if self._background_killer is None:
                    self._background_killer = BackgroundKiller()
                backup = self._background_killer.apply(settings)
                if self.state_guard:
                    for svc in backup.get("services_backup", []):
                        self.state_guard.add_paused_service(svc["name"])
                    for pid in backup.get("suspended_pids", []):
                        self.state_guard.add_suspended_pid(pid)
            except Exception as e:
                logger.error(f"Background killer apply error: {e}")
                errors.append("Services")

        if errors:
            self._set_status(f"Applied with errors: {', '.join(errors)}")
            raise RuntimeError(f"Optimizer errors: {', '.join(errors)}")
        else:
            self._set_status("All network optimizations applied")

    @pyqtSlot()
    def _on_optimizer_restore(self):
        self.tab_optimizer.clear_applied()
        self._applied_settings.pop("optimizer", None)
        self.tab_monitor.update_applied_settings(self._applied_settings)
        try:
            if self.state_guard:
                self.state_guard.restore_all()
                self._set_status("Network settings restored")
                self._toast.show_message("Network settings restored", "success")
        except Exception as e:
            logger.error(f"Optimizer restore error: {e}")

    # ------------------------------------------------------------------ RAM

    @pyqtSlot()
    def _on_ram_optimize(self):
        try:
            from core.ram_optimizer import RamOptimizer
            if self._ram_optimizer is None:
                self._ram_optimizer = RamOptimizer()
            result = self._ram_optimizer.optimize()
            freed = result.get("freed_mb", 0)
            self._ram_freed_mb = freed
            self.tab_optimizer.set_ram_freed(freed)
            self.tab_dashboard.set_ram_freed(freed)
            self._set_status(f"RAM freed: {freed} MB")
        except Exception as e:
            logger.error(f"RAM optimizer error: {e}")
            self._set_status(f"RAM optimizer error: {e}")

    # ------------------------------------------------------------------ Bandwidth

    @pyqtSlot()
    def _on_bandwidth_refresh(self):
        try:
            from core.bandwidth_manager import BandwidthManager
            if self._bandwidth_manager is None:
                self._bandwidth_manager = BandwidthManager()
            processes = self._bandwidth_manager.get_running_processes()
            self.tab_bandwidth.refresh_processes(processes)
        except Exception as e:
            logger.error(f"Bandwidth refresh error: {e}")

    @pyqtSlot(int, int)
    def _on_priority_change(self, pid: int, priority: int):
        try:
            from core.bandwidth_manager import BandwidthManager
            if self._bandwidth_manager is None:
                self._bandwidth_manager = BandwidthManager()
            self._bandwidth_manager.set_process_priority(pid, priority)
        except Exception as e:
            logger.warning(f"Priority change failed for PID {pid}: {e}")

    @pyqtSlot(int)
    def _on_process_suspend(self, pid: int):
        try:
            from core.background_killer import BackgroundKiller
            if self._background_killer is None:
                self._background_killer = BackgroundKiller()
            self._background_killer.suspend_process(pid)
            self.tab_bandwidth.set_suspended(pid, True)
            self._on_bandwidth_refresh()
        except Exception as e:
            logger.warning(f"Suspend failed for PID {pid}: {e}")

    @pyqtSlot(int)
    def _on_process_resume(self, pid: int):
        try:
            from core.background_killer import BackgroundKiller
            if self._background_killer is None:
                self._background_killer = BackgroundKiller()
            self._background_killer.resume_process(pid)
            self.tab_bandwidth.set_suspended(pid, False)
            self._on_bandwidth_refresh()
        except Exception as e:
            logger.warning(f"Resume failed for PID {pid}: {e}")

    # ------------------------------------------------------------------ Profiles

    @pyqtSlot(str)
    def _on_profile_load(self, name: str):
        if not self.profile_manager:
            return
        try:
            profile = self.profile_manager.load_profile(name)
            self.profile_manager.set_active(name)
            self._apply_profile(profile)
            self.tab_dashboard.set_active_profile(name)
            profiles = self.profile_manager.list_profiles()
            self.tab_profiles.set_profiles(profiles, name)
            self._set_status(f"Profile '{name}' loaded")
        except Exception as e:
            logger.error(f"Profile load error: {e}")

    def _apply_profile(self, profile: dict):
        """Apply all settings from a loaded profile to the UI tabs."""
        try:
            self.tab_wifi.set_settings(profile.get("wifi_optimizer", {}))
            self.tab_fps.set_settings(profile.get("fps_boost", {}))
            self.tab_optimizer.set_settings({
                **profile.get("tcp_optimizer", {}),
                **profile.get("dns", {}),
                **profile.get("background_killer", {}),
            })
            game_list = profile.get("game_list", [])
            if game_list:
                self.tab_settings.set_game_list(game_list)
        except Exception as e:
            logger.warning(f"Profile apply UI error: {e}")

    @pyqtSlot(str)
    def _on_profile_delete(self, name: str):
        if not self.profile_manager:
            return
        try:
            self.profile_manager.delete_profile(name)
            profiles = self.profile_manager.list_profiles()
            active = self.profile_manager.get_active().get("name", "")
            self.tab_profiles.set_profiles(profiles, active)
        except Exception as e:
            logger.error(f"Profile delete error: {e}")

    @pyqtSlot()
    def _on_profile_new(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name.strip():
            if not self.profile_manager:
                return
            try:
                default = self.profile_manager.load_profile("Default")
                default["name"] = name.strip()
                self.profile_manager.save_profile(name.strip(), default)
                profiles = self.profile_manager.list_profiles()
                active = self.profile_manager.get_active().get("name", "")
                self.tab_profiles.set_profiles(profiles, active)
            except Exception as e:
                logger.error(f"Profile create error: {e}")

    @pyqtSlot(str)
    def _on_profile_duplicate(self, source_name: str):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Duplicate Profile", "New profile name:")
        if ok and name.strip():
            if not self.profile_manager:
                return
            try:
                source = self.profile_manager.load_profile(source_name)
                source["name"] = name.strip()
                self.profile_manager.save_profile(name.strip(), source)
                profiles = self.profile_manager.list_profiles()
                active = self.profile_manager.get_active().get("name", "")
                self.tab_profiles.set_profiles(profiles, active)
            except Exception as e:
                logger.error(f"Profile duplicate error: {e}")

    @pyqtSlot()
    def _on_profile_import(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON Files (*.json)")
        if path and self.profile_manager:
            try:
                name = self.profile_manager.import_profile(path)
                profiles = self.profile_manager.list_profiles()
                active = self.profile_manager.get_active().get("name", "")
                self.tab_profiles.set_profiles(profiles, active)
                self._set_status(f"Imported profile: {name}")
            except Exception as e:
                QMessageBox.warning(self, "Import Failed", str(e))

    @pyqtSlot(str)
    def _on_profile_export(self, name: str):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{name}.json", "JSON Files (*.json)")
        if path and self.profile_manager:
            try:
                self.profile_manager.export_profile(name, path)
                self._set_status(f"Exported profile: {name}")
            except Exception as e:
                QMessageBox.warning(self, "Export Failed", str(e))

    # ------------------------------------------------------------------ Settings

    @pyqtSlot(dict)
    def _on_settings_changed(self, settings: dict):
        if self.ping_monitor:
            interval = settings.get("ping_interval_ms", 500)
            self.ping_monitor.set_interval(interval)
        self._auto_game_mode = settings.get("auto_game_mode", False)

    @pyqtSlot(list)
    def _on_game_list_changed(self, game_list: list):
        if self.process_watcher:
            self.process_watcher.set_game_list(game_list)

    @pyqtSlot(str)
    def _on_host_changed(self, host: str):
        if self.ping_monitor:
            self.ping_monitor.set_host(host)
            # Reset stats
            self._ping_history.clear()
            self._loss_count = 0
            self._total_count = 0

    # ------------------------------------------------------------------ Battery

    def _check_battery(self):
        try:
            import ctypes
            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", ctypes.c_byte),
                    ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte),
                    ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong),
                ]
            sps = SYSTEM_POWER_STATUS()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps))
            on_battery = sps.ACLineStatus == 0
            self.tab_dashboard.set_battery_warning(on_battery)
        except Exception:
            pass

    # ------------------------------------------------------------------ Health monitoring

    def _check_connectivity_health(self, loss_pct: float) -> None:
        """Called every ping reading. Fires a warning toast if packet loss is high."""
        if self._health_alert_cooldown or loss_pct < 15.0:
            return
        wifi = self._applied_settings.get("wifi", {})
        if wifi.get("minimize_roaming"):
            msg = (
                "High packet loss detected — 'Minimize Roaming Aggressiveness' "
                "may be causing brief disconnects during AP handoffs."
            )
            culprit = "minimize_roaming"
        elif wifi.get("prefer_6ghz"):
            msg = "High packet loss — 'Prefer 6 GHz Band' may be causing reconnects."
            culprit = "prefer_6ghz"
        else:
            return
        self._toast.show_message(msg, "warning", duration_ms=6000)
        self.tab_monitor.add_health_alert(msg, culprit_key=culprit)
        self._health_alert_cooldown = True
        self._health_alert_timer.start()

    def _check_gpu_temp(self) -> None:
        """Poll GPU temperature via nvidia-smi every 5 s."""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
            temp = int(result.stdout.strip())
        except Exception:
            return
        if temp >= 85 and not self._gpu_throttle_alerted:
            msg = (
                f"GPU {temp}\u00b0C — thermal throttling may be causing FPS drops. "
                "Consider disabling 'NVIDIA Maximum Performance Mode'."
            )
            self._toast.show_message(msg, "warning", duration_ms=8000)
            self.tab_monitor.add_health_alert(msg, culprit_key="nvidia_max_perf")
            self._gpu_throttle_alerted = True
        elif temp < 80:
            self._gpu_throttle_alerted = False

    @pyqtSlot(str)
    def _on_disable_setting(self, key: str) -> None:
        """Quick-disable a setting from the DiagnosticPanel [Disable] button."""
        from core.settings_risk import get_risk
        risk = get_risk(key)
        tab_name = risk.get("tab") if risk else None
        tab_map = {
            "wifi": self.tab_wifi,
            "fps": self.tab_fps,
            "optimizer": self.tab_optimizer,
        }
        tab = tab_map.get(tab_name)
        if tab:
            tab.set_settings({key: False})
            self._applied_settings.get(tab_name, {}).pop(key, None)
            self.tab_monitor.update_applied_settings(self._applied_settings)
        self._toast.show_message(
            f"'{key}' unchecked — click Apply in its tab to take effect.", "info"
        )

    # ------------------------------------------------------------------ Misc

    def _set_status(self, msg: str):
        self._status_label.setText(msg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_toast"):
            self._toast._reposition()

    def closeEvent(self, event: QCloseEvent):
        """Hide to tray instead of closing."""
        event.ignore()
        self.hide()

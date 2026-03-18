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
        self._ram_freed_mb = 0

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
        self.tab_optimizer.settings_applied.connect(self._on_optimizer_apply)
        self.tab_optimizer.ram_optimize_requested.connect(self._on_ram_optimize)
        self.tab_bandwidth.refresh_requested.connect(self._on_bandwidth_refresh)
        self.tab_bandwidth.priority_change_requested.connect(self._on_priority_change)
        self.tab_bandwidth.suspend_requested.connect(self._on_process_suspend)
        self.tab_bandwidth.resume_requested.connect(self._on_process_resume)
        self.tab_profiles.profile_load_requested.connect(self._on_profile_load)
        self.tab_profiles.profile_delete_requested.connect(self._on_profile_delete)
        self.tab_profiles.profile_new_requested.connect(self._on_profile_new)
        self.tab_profiles.profile_import_requested.connect(self._on_profile_import)
        self.tab_profiles.profile_export_requested.connect(self._on_profile_export)
        self.tab_settings.settings_changed.connect(self._on_settings_changed)
        self.tab_settings.game_list_changed.connect(self._on_game_list_changed)

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
        self._set_status(f"Game detected: {exe_name}")

        if self._game_mode_active:
            self._activate_game_mode(exe_name)

    @pyqtSlot(str)
    def on_game_exited(self, exe_name: str):
        logger.info(f"Game exited: {exe_name}")
        self._current_game = None
        self.tab_dashboard.set_game_detected(None)
        self._set_status("No game detected")

        if self._game_mode_active:
            self._deactivate_game_mode()

    # ------------------------------------------------------------------ Game Mode

    @pyqtSlot(bool)
    def _on_game_mode_toggled(self, enabled: bool):
        self._game_mode_active = enabled
        if enabled:
            self._set_status("Game Mode activated")
            if self._current_game:
                self._activate_game_mode(self._current_game)
        else:
            self._set_status("Game Mode deactivated")
            self._deactivate_game_mode()

    def _activate_game_mode(self, exe_name: str):
        """Apply all enabled optimizations for the detected game."""
        logger.info(f"Activating game mode for {exe_name}")
        # Wi-Fi
        try:
            wifi_settings = self.tab_wifi.get_settings()
            if wifi_settings.get("enabled"):
                self._apply_wifi(wifi_settings)
        except Exception as e:
            logger.warning(f"Wi-Fi game mode apply failed: {e}")
        # FPS
        try:
            fps_settings = self.tab_fps.get_settings()
            if fps_settings.get("enabled"):
                self._apply_fps(fps_settings)
        except Exception as e:
            logger.warning(f"FPS game mode apply failed: {e}")
        # Network/DNS
        try:
            net_settings = self.tab_optimizer.get_settings()
            if net_settings.get("enabled"):
                self._apply_optimizer(net_settings)
        except Exception as e:
            logger.warning(f"Optimizer game mode apply failed: {e}")

    def _deactivate_game_mode(self):
        """Restore all settings when game exits."""
        logger.info("Deactivating game mode, restoring settings")
        if self.state_guard:
            try:
                self.state_guard.restore_all()
            except Exception as e:
                logger.error(f"restore_all failed: {e}")

    # ------------------------------------------------------------------ Wi-Fi

    @pyqtSlot(dict)
    def _on_wifi_apply(self, settings: dict):
        try:
            self._apply_wifi(settings)
            self.tab_wifi.show_apply_success()
            self._toast.show_message("Wi-Fi optimizations applied", "success")
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
        try:
            self._apply_fps(settings)
            self.tab_fps.show_apply_success()
            self._toast.show_message("FPS optimizations applied", "success")
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
            self._set_status("FPS optimizations applied")
        except Exception as e:
            logger.error(f"FPS apply error: {e}")
            self._set_status(f"FPS error: {e}")
            raise

    # ------------------------------------------------------------------ Optimizer (TCP/DNS/Services)

    @pyqtSlot(dict)
    def _on_optimizer_apply(self, settings: dict):
        try:
            self._apply_optimizer(settings)
            self.tab_optimizer.show_apply_success()
            self._toast.show_message("Network optimizations applied", "success")
        except Exception:
            self.tab_optimizer.show_apply_error()
            self._toast.show_message("Optimizer apply failed", "error")

    def _apply_optimizer(self, settings: dict):
        errors = []

        # TCP
        if settings.get("nagle_off") or settings.get("tcp_nodelay") or settings.get("window_scaling"):
            try:
                from core.network_optimizer import NetworkOptimizer
                if self._network_optimizer is None:
                    self._network_optimizer = NetworkOptimizer()
                backup = self._network_optimizer.apply(settings)
                if self.state_guard:
                    self.state_guard.record_tcp_backup(backup)
            except Exception as e:
                logger.error(f"TCP apply error: {e}")
                errors.append("TCP")

        # DNS
        if settings.get("dns_enabled") and settings.get("dns_provider"):
            try:
                from core.dns_switcher import DnsSwitcher
                if self._dns_switcher is None:
                    self._dns_switcher = DnsSwitcher()
                backup = self._dns_switcher.apply(
                    settings["dns_provider"],
                    custom_primary=settings.get("custom_dns_primary"),
                    custom_secondary=settings.get("custom_dns_secondary"),
                )
                if self.state_guard:
                    self.state_guard.record_dns_backup(backup)
            except Exception as e:
                logger.error(f"DNS apply error: {e}")
                errors.append("DNS")

        # Background killer
        if settings.get("pause_wupdate") or settings.get("pause_onedrive") or settings.get("pause_bits"):
            try:
                from core.background_killer import BackgroundKiller
                if self._background_killer is None:
                    self._background_killer = BackgroundKiller()
                backup = self._background_killer.apply(settings)
                if self.state_guard:
                    state = self.state_guard.get_state()
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
        except Exception as e:
            logger.warning(f"Suspend failed for PID {pid}: {e}")

    @pyqtSlot(int)
    def _on_process_resume(self, pid: int):
        try:
            from core.background_killer import BackgroundKiller
            if self._background_killer is None:
                self._background_killer = BackgroundKiller()
            self._background_killer.resume_process(pid)
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

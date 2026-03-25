"""
NetBoost — Gaming Network Optimizer
Entry point: admin check, crash recovery, Qt bootstrap
"""
import sys
import os
import logging
import traceback

# Set up logging before anything else
log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NetBoost", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "netboost.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("netboost")


def main():
    # Step 1: Admin check
    from core.admin import is_admin, elevate
    if not is_admin():
        logger.info("Not running as admin — requesting elevation via UAC")
        try:
            elevate()
        except Exception as e:
            logger.error(f"Failed to elevate: {e}")
            # Show a message box if PyQt5 is available
            try:
                from PyQt5.QtWidgets import QApplication, QMessageBox
                app = QApplication(sys.argv)
                QMessageBox.critical(
                    None,
                    "NetBoost — Admin Required",
                    "NetBoost requires administrator privileges to optimize your network and system settings.\n\n"
                    "Please right-click NetBoost.exe and select 'Run as administrator'.",
                )
            except Exception:
                pass
            sys.exit(1)
        return  # elevate() calls sys.exit(), but return for clarity

    logger.info("Running as administrator")

    # Step 2: Crash recovery
    try:
        from core.state_guard import StateGuard
        guard = StateGuard()
        healed = guard.check_and_heal()
        if healed:
            logger.info("StateGuard: restored settings from previous crash")
    except Exception as e:
        logger.warning(f"StateGuard init failed: {e}")
        guard = None

    # Step 3: Load profiles
    try:
        from core.profile_manager import ProfileManager
        profile_manager = ProfileManager()
        profile_manager.load_all()
        logger.info(f"Loaded {len(profile_manager.list_profiles())} profiles")
    except Exception as e:
        logger.error(f"ProfileManager init failed: {e}")
        profile_manager = None

    # Step 4: Create Qt application
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon

    app = QApplication(sys.argv)
    app.setApplicationName("NetBoost")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("NetBoost")
    app.setQuitOnLastWindowClosed(False)  # Keep running in system tray

    # Apply dark theme
    try:
        qss_path = os.path.join(os.path.dirname(__file__), "resources", "styles", "dark_theme.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            logger.info("Dark theme applied")
    except Exception as e:
        logger.warning(f"Failed to load dark theme: {e}")

    # Set app icon
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "netboost.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass

    # Step 5: Create main window and tray icon
    from ui.main_window import MainWindow
    from ui.tray_icon import TrayIcon

    window = MainWindow(state_guard=guard, profile_manager=profile_manager)
    tray = TrayIcon(window, app)
    window.tray = tray  # allow MainWindow to call tray.set_game_detected()

    # Populate tray profile submenu now that both window and tray exist
    if profile_manager:
        try:
            _profiles = profile_manager.list_profiles()
            _active = profile_manager.get_active().get("name", "Default") if _profiles else "Default"
            tray.update_profiles(_profiles, _active)
        except Exception as e:
            logger.warning(f"Failed to populate tray profile submenu: {e}")

    window.show()

    # Step 6: Start background threads
    from core.ping_monitor import PingMonitor
    from core.process_watcher import ProcessWatcher

    # Load game list from active profile or default
    game_list = []
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "config", "games_default.json")
        if os.path.exists(cfg_path):
            import json
            with open(cfg_path, "r") as f:
                games_data = json.load(f)
            game_list = [g["exe"] for g in games_data]
    except Exception as e:
        logger.warning(f"Failed to load game list: {e}")

    ping_monitor = PingMonitor(host="1.1.1.1", interval_ms=500)
    process_watcher = ProcessWatcher(game_list=game_list, poll_interval_ms=1500)

    # Wire signals
    ping_monitor.reading.connect(window.on_ping_reading)
    process_watcher.game_launched.connect(window.on_game_launched)
    process_watcher.game_exited.connect(window.on_game_exited)

    # Expose to window for dynamic reconfiguration
    window.ping_monitor = ping_monitor
    window.process_watcher = process_watcher

    ping_monitor.start()
    process_watcher.start()

    logger.info("NetBoost started successfully")

    # Step 7: Run event loop
    def excepthook(exc_type, exc_value, exc_tb):
        logger.critical(
            "Unhandled exception:\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )

    sys.excepthook = excepthook

    exit_code = app.exec_()

    # Step 8: Cleanup on exit
    logger.info("Shutting down...")
    ping_monitor.stop()
    process_watcher.stop()
    ping_monitor.wait(3000)
    process_watcher.wait(3000)

    if guard:
        try:
            guard.restore_all()
            guard.clear()
            logger.info("StateGuard: restored all settings on clean exit")
        except Exception as e:
            logger.error(f"StateGuard cleanup failed: {e}")

    logger.info("NetBoost exited cleanly")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

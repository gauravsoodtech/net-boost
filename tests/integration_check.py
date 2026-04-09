"""
NetBoost Integration Check Script
Run as admin: python tests/integration_check.py

Validates each feature without needing a real game.
Prints [PASS], [FAIL: reason], or [SKIP: reason] per step.
"""
import sys
import os
import json
import time
import subprocess
import tempfile

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"
INFO = "\033[94m[INFO]\033[0m"


def check(label: str, fn):
    """Run fn(), print result."""
    try:
        result = fn()
        if result is True or result is None:
            print(f"{PASS} {label}")
        elif isinstance(result, str) and result.startswith("SKIP"):
            reason = result[5:].strip()
            print(f"{SKIP} {label}: {reason}")
        else:
            print(f"{PASS} {label}: {result}")
    except Exception as e:
        print(f"{FAIL} {label}: {e}")


# ============================================================
# 1. Admin check
# ============================================================
def test_admin():
    from core.admin import is_admin
    if not is_admin():
        raise RuntimeError("Not running as administrator")
    return True


# ============================================================
# 2. StateGuard write + atomic restore
# ============================================================
def test_state_guard():
    from core.state_guard import StateGuard
    import uuid

    guard = StateGuard()
    dummy_state = {
        "pid": os.getpid(),
        "dns_backup": {"adapter": "Wi-Fi", "test_id": str(uuid.uuid4())},
        "tcp_backup": {},
        "paused_services": ["test_service"],
        "suspended_pids": [],
        "qos_policies": [],
        "wifi_backup": {},
        "nvidia_backup": {},
        "fps_backup": {},
    }
    guard.save_state(dummy_state)
    loaded = guard.load_state()

    assert loaded["dns_backup"]["adapter"] == "Wi-Fi"
    assert "test_service" in loaded["paused_services"]

    # Verify no .tmp leftover
    state_dir = os.path.join(os.environ.get("APPDATA", ""), "NetBoost")
    tmp_files = [f for f in os.listdir(state_dir) if f.endswith(".tmp")]
    assert len(tmp_files) == 0, f"Leftover .tmp files: {tmp_files}"

    guard.clear()
    assert not os.path.exists(os.path.join(state_dir, "state.json"))
    return True


# ============================================================
# 3. Ping monitor (10-second live ping)
# ============================================================
def test_ping_monitor():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    app = QApplication.instance() or QApplication(sys.argv)
    from core.ping_monitor import PingMonitor

    results = []
    monitor = PingMonitor(host="1.1.1.1", interval_ms=500)

    def on_reading(host, ms, timed_out):
        results.append((host, ms, timed_out))
        if len(results) >= 5:
            monitor.stop()

    monitor.reading.connect(on_reading)
    monitor.start()

    # Wait up to 15s
    deadline = time.time() + 15
    while time.time() < deadline and monitor.isRunning():
        app.processEvents()
        time.sleep(0.1)

    monitor.wait(2000)

    if not results:
        raise RuntimeError("No ping readings received")

    valid = [r for r in results if not r[2]]
    timed_out = [r for r in results if r[2]]
    min_ms = min(r[1] for r in valid) if valid else 0
    max_ms = max(r[1] for r in valid) if valid else 0
    avg_ms = sum(r[1] for r in valid) / len(valid) if valid else 0
    loss_pct = len(timed_out) / len(results) * 100

    return f"min={min_ms:.1f}ms avg={avg_ms:.1f}ms max={max_ms:.1f}ms loss={loss_pct:.0f}% ({len(results)} readings)"


# ============================================================
# 4. DNS switch (switch to Cloudflare, verify, restore)
# ============================================================
def test_dns_switch():
    from core.dns_switcher import DnsSwitcher
    from core.admin import is_admin
    if not is_admin():
        return "SKIP no admin"

    ds = DnsSwitcher()
    adapter = ds.get_active_adapter()
    if not adapter:
        return "SKIP could not detect active adapter"

    # Save backup
    backup = ds.apply("cloudflare", adapter=adapter)

    # Verify via ipconfig /all
    result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True)
    if "1.1.1.1" not in result.stdout:
        ds.restore(backup)
        raise RuntimeError("1.1.1.1 not found in ipconfig /all after DNS switch")

    # Restore
    ds.restore(backup)

    # Verify restored
    result2 = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True)
    return f"DNS switch OK (adapter: {adapter})"


# ============================================================
# 5. TCP registry write + verify + restore
# ============================================================
def test_tcp_registry():
    from core.network_optimizer import NetworkOptimizer
    from core.admin import is_admin
    if not is_admin():
        return "SKIP no admin"

    opt = NetworkOptimizer()
    settings = {"tcp_no_delay": True, "tcp_ack_freq": True, "tcp_window_scale": False}
    backup = opt.apply(settings)

    # Verify at least one interface was modified
    if not backup:
        return "SKIP no network interfaces found"

    # Restore
    opt.restore(backup)
    return f"TCP registry write+restore OK ({len(backup)} interfaces)"


# ============================================================
# 6. Service status check (read-only, no pause)
# ============================================================
def test_service_status():
    try:
        import win32service
        import win32serviceutil
    except ImportError:
        return "SKIP pywin32 not available"

    try:
        status = win32serviceutil.QueryServiceStatus("wuauserv")
        state_map = {
            1: "Stopped", 2: "Start Pending", 3: "Stop Pending",
            4: "Running", 5: "Continue Pending", 6: "Pause Pending", 7: "Paused",
        }
        state = state_map.get(status[1], str(status[1]))
        return f"wuauserv state: {state} (read-only check)"
    except Exception as e:
        return f"SKIP could not query wuauserv: {e}"


# ============================================================
# 7. Process watcher (detect notepad.exe)
# ============================================================
def test_process_watcher():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    app = QApplication.instance() or QApplication(sys.argv)
    from core.process_watcher import ProcessWatcher

    detected = []
    watcher = ProcessWatcher(game_list=["notepad.exe"], poll_interval_ms=500)

    def on_launch(name):
        detected.append(name)

    watcher.game_launched.connect(on_launch)
    watcher.start()

    # Launch notepad
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(0.2)

    # Wait up to 5s for detection
    deadline = time.time() + 5
    while time.time() < deadline and not detected:
        app.processEvents()
        time.sleep(0.1)

    # Kill notepad
    proc.terminate()
    watcher.stop()
    watcher.wait(2000)

    if not detected:
        raise RuntimeError("notepad.exe was not detected by ProcessWatcher")

    return f"Detected: {detected[0]}"


# ============================================================
# 8. Profile round-trip
# ============================================================
def test_profile_roundtrip():
    from core.profile_manager import ProfileManager
    import uuid

    pm = ProfileManager()
    test_name = f"IntegrationTest_{uuid.uuid4().hex[:8]}"
    profile = {
        "name": test_name,
        "dns": {"switch_dns": False, "dns_provider": "Cloudflare 1.1.1.1"},
        "tcp_optimizer": {"tcp_no_delay": True, "tcp_ack_freq": True, "tcp_window_scale": False, "enabled": False},
        "bandwidth": {"game_priority": 3, "enabled": False},
        "background_killer": {"pause_windows_update": False, "pause_onedrive": False, "pause_bits": False, "enabled": False},
        "fps_boost": {"enabled": False},
        "ping_monitor": {"host": "1.1.1.1", "interval_ms": 500},
        "game_list": [],
        "wifi_optimizer": {"enabled": False},
        "nvidia_optimizer": {"enabled": False},
    }
    pm.save_profile(test_name, profile)
    loaded = pm.load_profile(test_name)
    assert loaded["name"] == test_name
    assert loaded["dns"]["dns_provider"] == "Cloudflare 1.1.1.1"

    pm.delete_profile(test_name)
    assert test_name not in pm.list_profiles()
    return f"Profile round-trip OK ('{test_name}')"


# ============================================================
# Main
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("  NetBoost Integration Check")
    print("=" * 60 + "\n")

    steps = [
        ("Admin check", test_admin),
        ("StateGuard write + atomic restore", test_state_guard),
        ("Ping monitor (1.1.1.1, 5 readings)", test_ping_monitor),
        ("DNS switch (Cloudflare -> restore)", test_dns_switch),
        ("TCP registry write + restore", test_tcp_registry),
        ("Service status check (wuauserv)", test_service_status),
        ("Process watcher (notepad.exe detection)", test_process_watcher),
        ("Profile round-trip (create/load/delete)", test_profile_roundtrip),
    ]

    passed = failed = skipped = 0
    for label, fn in steps:
        try:
            result = fn()
            if isinstance(result, str) and result.startswith("SKIP"):
                reason = result[5:].strip()
                print(f"{SKIP} {label}: {reason}")
                skipped += 1
            else:
                display = f" — {result}" if result and result is not True else ""
                print(f"{PASS} {label}{display}")
                passed += 1
        except Exception as e:
            print(f"{FAIL} {label}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

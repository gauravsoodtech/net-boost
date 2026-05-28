"""
Tests for StateGuard: crash simulation, atomic writes, restore_all() on dead PID.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock, call


class TestStateGuard:

    @pytest.fixture
    def tmp_appdata(self, tmp_path):
        """Redirect APPDATA to temp dir."""
        nb_dir = tmp_path / "NetBoost"
        nb_dir.mkdir()
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            yield tmp_path

    @pytest.fixture
    def guard(self, tmp_appdata):
        from core.state_guard import StateGuard
        return StateGuard()

    @pytest.fixture
    def clean_guard(self):
        """
        StateGuard that wipes %APPDATA%\\NetBoost\\state.json before AND after
        the test so backup_history assertions are not polluted by prior runs.
        """
        from core.state_guard import StateGuard, _STATE_DIR, _STATE_FILE
        os.makedirs(_STATE_DIR, exist_ok=True)
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)
        g = StateGuard()
        yield g
        try:
            os.remove(_STATE_FILE)
        except FileNotFoundError:
            pass

    def test_initial_state_empty(self, guard):
        """Fresh StateGuard has empty state."""
        state = guard.get_state()
        assert isinstance(state, dict)
        assert state.get("dns_backup") in (None, {})
        assert state.get("paused_services") in (None, [])

    def test_save_and_load_state(self, guard):
        """State written to disk can be read back."""
        state = {
            "pid": os.getpid(),
            "dns_backup": {"adapter": "Wi-Fi", "primary": "8.8.8.8"},
            "tcp_backup": {"TcpAckFrequency": {"old": 0}},
            "paused_services": ["wuauserv"],
            "suspended_pids": [1234],
            "qos_policies": [],
            "wifi_backup": {},
            "nvidia_backup": {},
            "fps_backup": {},
        }
        guard.save_state(state)
        loaded = guard.load_state()
        assert loaded["pid"] == os.getpid()
        assert loaded["dns_backup"]["adapter"] == "Wi-Fi"
        assert "wuauserv" in loaded["paused_services"]

    def test_atomic_write_uses_tmp_file(self, guard, tmp_appdata):
        """save_state() should use atomic write (no leftover .tmp file)."""
        import pathlib
        from core.state_guard import _STATE_DIR, _STATE_FILE

        state = {"pid": os.getpid()}
        guard.save_state(state)

        # _STATE_DIR/_STATE_FILE are resolved at module import time, so check those paths.
        state_dir = pathlib.Path(_STATE_DIR)
        files = list(state_dir.glob("*.tmp"))
        assert len(files) == 0, "Temporary .tmp files should be cleaned up"

        state_file = pathlib.Path(_STATE_FILE)
        assert state_file.exists()

        # cleanup — don't leave test state in real APPDATA
        try:
            state_file.unlink()
        except FileNotFoundError:
            pass

    def test_clear_removes_state_file(self, guard, tmp_appdata):
        """clear() removes state.json from disk."""
        guard.save_state({"pid": os.getpid()})
        guard.clear()

        state_file = tmp_appdata / "NetBoost" / "state.json"
        assert not state_file.exists()

    def test_check_and_heal_dead_pid(self, guard):
        """check_and_heal() calls restore_all() if previous PID is dead."""
        # Save state with a definitely-dead PID (use a very large PID unlikely to exist)
        fake_pid = 999999
        state = {
            "pid": fake_pid,
            "dns_backup": {},
            "tcp_backup": {},
            "paused_services": [],
            "suspended_pids": [],
            "qos_policies": [],
            "wifi_backup": {},
            "nvidia_backup": {},
            "fps_backup": {},
        }
        guard.save_state(state)

        with patch("psutil.pid_exists", return_value=False):
            # Patch the module-level restore_all — that's what check_and_heal() calls directly.
            with patch("core.state_guard.restore_all") as mock_restore:
                healed = guard.check_and_heal()

        assert healed is True
        mock_restore.assert_called_once()

    def test_check_and_heal_alive_pid(self, guard):
        """check_and_heal() does NOT restore if previous PID is alive (e.g., multiple instances)."""
        state = {
            "pid": os.getpid(),  # current PID — "alive"
            "dns_backup": {},
        }
        guard.save_state(state)

        with patch("psutil.pid_exists", return_value=True):
            with patch.object(guard, "restore_all") as mock_restore:
                healed = guard.check_and_heal()

        assert healed is False
        mock_restore.assert_not_called()

    def test_check_and_heal_no_state_file(self, guard):
        """check_and_heal() returns False if no state file exists."""
        guard.clear()  # make sure it doesn't exist
        healed = guard.check_and_heal()
        assert healed is False

    def test_record_dns_backup(self, guard):
        """record_dns_backup() persists DNS backup into state."""
        backup = {"adapter": "Wi-Fi", "original_dns": {"primary": "8.8.8.8", "is_dhcp": False}}
        guard.record_dns_backup(backup)
        state = guard.get_state()
        assert state["dns_backup"]["adapter"] == "Wi-Fi"

    def test_record_tcp_backup(self, guard):
        """record_tcp_backup() persists TCP backup into state."""
        backup = {"interface_guid": "abc123", "values": {"TcpAckFrequency": 2}}
        guard.record_tcp_backup(backup)
        state = guard.get_state()
        assert state["tcp_backup"]["interface_guid"] == "abc123"

    def test_add_and_remove_paused_service(self, guard):
        """add/remove paused service tracks list correctly."""
        guard.add_paused_service("wuauserv")
        guard.add_paused_service("BITS")
        state = guard.get_state()
        assert "wuauserv" in state["paused_services"]
        assert "BITS" in state["paused_services"]

        guard.remove_paused_service("wuauserv")
        state = guard.get_state()
        assert "wuauserv" not in state["paused_services"]
        assert "BITS" in state["paused_services"]

    def test_add_and_remove_suspended_pid(self, guard):
        """add/remove suspended PID tracks list correctly."""
        guard.add_suspended_pid(1234)
        guard.add_suspended_pid(5678)
        state = guard.get_state()
        assert 1234 in state["suspended_pids"]

        guard.remove_suspended_pid(1234)
        state = guard.get_state()
        assert 1234 not in state["suspended_pids"]
        assert 5678 in state["suspended_pids"]

    def test_state_survives_corrupt_file(self, guard, tmp_appdata):
        """If state.json is corrupt, check_and_heal() handles it gracefully."""
        state_path = tmp_appdata / "NetBoost" / "state.json"
        state_path.write_text("{ broken json {{{{ ")

        healed = guard.check_and_heal()
        assert isinstance(healed, bool)  # Should not raise

    def test_restore_all_is_best_effort(self, guard):
        """restore_all() should not raise even if individual restores fail."""
        guard.record_dns_backup({"adapter": "Wi-Fi", "original_dns": {"is_dhcp": True}})
        guard.add_paused_service("wuauserv")

        # Mock the dns_switcher to raise
        with patch("core.dns_switcher.DnsSwitcher") as MockDns:
            MockDns.return_value.restore.side_effect = Exception("DNS restore failed")
            try:
                guard.restore_all()
            except Exception as e:
                pytest.fail(f"restore_all() raised unexpectedly: {e}")

    # --- backup_history (Phase D) ---
    #
    # The clean_guard fixture deletes %APPDATA%\NetBoost\state.json before AND
    # after each test so leakage between runs cannot pollute history asserts.

    def test_branching_apply_records_two_history_entries(self, clean_guard):
        """A second non-equal record_*_backup under the same PID branches history."""
        clean_guard.record_dns_backup({"adapter": "Wi-Fi", "primary": "8.8.8.8"})
        clean_guard.record_dns_backup({"adapter": "Wi-Fi", "primary": "1.1.1.1"})

        history = clean_guard.get_state()["backup_history"]
        assert len(history) == 2
        assert history[0]["dns_backup"]["primary"] == "8.8.8.8"
        assert history[1]["dns_backup"]["primary"] == "1.1.1.1"

    def test_repeated_identical_record_does_not_duplicate_history(self, clean_guard):
        """Recording the same backup twice should overwrite latest, not branch."""
        backup = {"adapter": "Wi-Fi", "primary": "8.8.8.8"}
        clean_guard.record_dns_backup(backup)
        clean_guard.record_dns_backup(backup)

        assert len(clean_guard.get_state()["backup_history"]) == 1

    def test_history_caps_at_five(self, clean_guard):
        """Append more than 5 distinct entries — oldest must be dropped."""
        for i in range(7):
            clean_guard.record_dns_backup({"primary": f"10.0.0.{i}"})

        history = clean_guard.get_state()["backup_history"]
        assert len(history) == 5
        # Oldest two (10.0.0.0, 10.0.0.1) dropped — newest five remain.
        primaries = [e["dns_backup"]["primary"] for e in history]
        assert primaries == [f"10.0.0.{i}" for i in range(2, 7)]

    def test_restore_all_walks_history_newest_to_oldest(self, clean_guard):
        """restore_all should call dns_optimizer.restore once per history entry."""
        clean_guard.record_dns_backup({"primary": "a"})
        clean_guard.record_dns_backup({"primary": "b"})
        clean_guard.record_dns_backup({"primary": "c"})

        with patch("core.dns_optimizer.restore") as mock_restore:
            clean_guard.restore_all()

        called = [c.args[0]["primary"] for c in mock_restore.call_args_list]
        assert called == ["c", "b", "a"]  # newest first

    def test_restore_all_clears_state_after_success(self, clean_guard):
        """restore_all must remove state.json once the walk finishes."""
        import pathlib
        from core.state_guard import _STATE_FILE
        state_path = pathlib.Path(_STATE_FILE)

        clean_guard.record_dns_backup({"primary": "8.8.8.8"})
        assert state_path.exists()

        with patch("core.dns_optimizer.restore"):
            clean_guard.restore_all()

        assert not state_path.exists()

    def test_legacy_state_file_migrates_into_history(self, clean_guard):
        """A pre-Phase-D state.json (no backup_history) should heal correctly."""
        import pathlib
        from core.state_guard import _STATE_FILE, _STATE_DIR
        pathlib.Path(_STATE_DIR).mkdir(parents=True, exist_ok=True)
        state_path = pathlib.Path(_STATE_FILE)

        legacy = {
            "pid": os.getpid(),
            "dns_backup": {"adapter": "Wi-Fi", "primary": "8.8.8.8"},
            "tcp_backup": {},
            "paused_services": ["wuauserv"],
            "suspended_pids": [],
            "qos_policies": [],
            "wifi_backup": {},
            "nvidia_backup": {},
            "fps_backup": {},
            # NOTE: no "backup_history" — legacy format
        }
        state_path.write_text(json.dumps(legacy))

        loaded = clean_guard.load_state()

        assert len(loaded["backup_history"]) == 1
        entry = loaded["backup_history"][0]
        assert entry["dns_backup"]["primary"] == "8.8.8.8"
        assert entry["paused_services"] == ["wuauserv"]
        assert loaded["dns_backup"]["primary"] == "8.8.8.8"

    def test_add_paused_service_mirrored_into_latest_history_entry(self, clean_guard):
        """List-mutators must keep the latest history entry in sync."""
        clean_guard.record_dns_backup({"primary": "8.8.8.8"})
        clean_guard.add_paused_service("wuauserv")
        clean_guard.add_paused_service("BITS")

        history = clean_guard.get_state()["backup_history"]
        assert "wuauserv" in history[-1]["paused_services"]
        assert "BITS" in history[-1]["paused_services"]

    # --- system_tweaks backups (MSI / NDU / NetworkThrottlingIndex) ---

    def test_record_msi_backup(self, guard):
        """record_msi_backup persists the per-device MSI prior values."""
        backup = {
            "values": {"subkey-a": 0, "subkey-b": -1},
            "_targets_found": 2,
            "_writes_succeeded": 2,
            "_access_denied": False,
        }
        guard.record_msi_backup(backup)
        state = guard.get_state()
        assert state["msi_backup"]["values"]["subkey-a"] == 0
        assert state["msi_backup"]["values"]["subkey-b"] == -1

    def test_record_ndu_backup(self, guard):
        """record_ndu_backup persists the prior Start DWORD."""
        guard.record_ndu_backup({"start": 2, "_ok": True, "_error": ""})
        state = guard.get_state()
        assert state["ndu_backup"]["start"] == 2

    def test_record_throttling_backup(self, guard):
        """record_throttling_backup persists the prior NetworkThrottlingIndex value."""
        guard.record_throttling_backup({"prev_value": 10, "_ok": True})
        state = guard.get_state()
        assert state["throttling_backup"]["prev_value"] == 10

    def test_restore_all_dispatches_system_tweaks_restores(self, clean_guard):
        """restore_all walks history and calls each system_tweaks restore once."""
        clean_guard.record_msi_backup({"values": {"sub-a": 0}})
        clean_guard.record_ndu_backup({"start": 2, "_ok": True})
        clean_guard.record_throttling_backup({"prev_value": 10, "_ok": True})

        with patch("core.system_tweaks.restore_msi_mode") as mock_msi, \
             patch("core.system_tweaks.restore_ndu_service") as mock_ndu, \
             patch("core.system_tweaks.restore_network_throttling") as mock_throttle:
            clean_guard.restore_all()

        # Each restore_* must fire at least once across the replayed history.
        assert mock_msi.called
        assert mock_ndu.called
        assert mock_throttle.called

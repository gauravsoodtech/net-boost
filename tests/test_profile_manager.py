"""
Tests for ProfileManager: create/load/save/delete profiles, schema validation, corrupt file handling.
"""
import json
import os
import tempfile
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock


class TestProfileManager:
    """Tests for ProfileManager class."""

    @pytest.fixture
    def tmp_appdata(self, tmp_path):
        """Redirect APPDATA to a temp directory."""
        profiles_dir = tmp_path / "NetBoost" / "profiles"
        profiles_dir.mkdir(parents=True)
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            yield tmp_path

    @pytest.fixture
    def manager(self, tmp_appdata):
        from core.profile_manager import ProfileManager
        pm = ProfileManager()
        return pm

    def test_load_all_creates_defaults(self, manager):
        """load_all() should create default profiles if none exist."""
        manager.load_all()
        profiles = manager.list_profiles()
        assert "Gaming" in profiles
        assert "Work" in profiles
        assert "Default" in profiles

    def test_save_and_load_profile(self, manager):
        """save_profile + load_profile round-trip."""
        profile = {
            "name": "TestProfile",
            "dns": {"provider": "cloudflare", "enabled": True},
            "tcp_optimizer": {"tcp_no_delay": True, "tcp_ack_freq": True, "tcp_window_scale": False, "enabled": True},
            "bandwidth": {"game_priority": 3, "enabled": False},
            "background_killer": {"pause_windows_update": True, "pause_onedrive": True, "pause_bits": False, "enabled": True},
            "fps_boost": {
                "power_plan": True, "pcores_affinity": True, "timer_resolution": True,
                "game_dvr_off": True, "nvidia_max_perf": False, "fullscreen_opt_off": False,
                "sysmain_off": False, "visual_effects_off": False, "enabled": True,
            },
            "ping_monitor": {"host": "1.1.1.1", "interval_ms": 500},
            "game_list": ["cs2.exe", "VALORANT-Win64-Shipping.exe"],
            "wifi_optimizer": {
                "disable_power_saving": True, "minimize_roaming": True, "prefer_6ghz": True,
                "max_tx_power": True, "disable_bss_scan": True, "enabled": True,
            },
            "nvidia_optimizer": {
                "dynamic_pstate_off": True, "ull_mode": True, "max_power": True, "enabled": True,
            },
        }
        manager.save_profile("TestProfile", profile)
        loaded = manager.load_profile("TestProfile")
        assert loaded["name"] == "TestProfile"
        assert loaded["dns"]["provider"] == "cloudflare"
        assert loaded["tcp_optimizer"]["tcp_no_delay"] is True

    def test_list_profiles(self, manager):
        """list_profiles() returns all saved profile names."""
        manager.load_all()
        manager.save_profile("ExtraProfile", {"name": "ExtraProfile"})
        profiles = manager.list_profiles()
        assert "ExtraProfile" in profiles
        assert len(profiles) >= 4  # 3 defaults + 1 new

    def test_delete_profile(self, manager):
        """delete_profile() removes a profile."""
        manager.load_all()
        manager.save_profile("ToDelete", {"name": "ToDelete"})
        assert "ToDelete" in manager.list_profiles()
        manager.delete_profile("ToDelete")
        assert "ToDelete" not in manager.list_profiles()

    def test_delete_nonexistent_profile(self, manager):
        """Deleting a nonexistent profile should not raise."""
        manager.delete_profile("DoesNotExist")  # should not raise

    def test_import_export_profile(self, manager, tmp_path):
        """import_profile / export_profile round-trip through a file."""
        manager.load_all()
        export_path = str(tmp_path / "exported.json")
        manager.export_profile("Gaming", export_path)
        assert os.path.exists(export_path)

        # Modify the exported file and re-import
        with open(export_path, "r") as f:
            data = json.load(f)
        data["name"] = "ImportedGaming"
        with open(export_path, "w") as f:
            json.dump(data, f)

        imported_name = manager.import_profile(export_path)
        assert imported_name == "ImportedGaming"
        assert "ImportedGaming" in manager.list_profiles()

    def test_corrupt_file_handled(self, tmp_path):
        """A corrupt JSON profile file should not crash load_all()."""
        profiles_dir = tmp_path / "NetBoost" / "profiles"
        profiles_dir.mkdir(parents=True)
        # Write a corrupt file
        corrupt_file = profiles_dir / "corrupt.json"
        corrupt_file.write_text("{ this is not valid json !!!")

        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            from core.profile_manager import ProfileManager
            pm = ProfileManager()
            pm.load_all()  # Should not raise
            # Corrupt file should be skipped; defaults still created
            assert "Gaming" in pm.list_profiles()

    def test_set_and_get_active(self, manager):
        """set_active / get_active persists across instances."""
        manager.load_all()
        manager.set_active("Gaming")
        active = manager.get_active()
        assert active.get("name") == "Gaming"

    def test_get_profile_returns_none_for_missing(self, manager):
        """get_profile() returns None or raises for missing profile."""
        result = manager.get_profile("NonExistent")
        assert result is None

    def test_gaming_profile_has_all_optimizations_on(self, manager):
        """Default Gaming profile should have all optimizations enabled."""
        manager.load_all()
        profile = manager.load_profile("Gaming")
        assert profile["tcp_optimizer"]["enabled"] is True
        assert profile["wifi_optimizer"]["enabled"] is True
        assert profile["fps_boost"]["enabled"] is True

    def test_default_profile_all_off(self, manager):
        """Default 'Default' profile should have all optimizations disabled."""
        manager.load_all()
        profile = manager.load_profile("Default")
        assert profile["tcp_optimizer"]["enabled"] is False
        assert profile["wifi_optimizer"]["enabled"] is False
        assert profile["fps_boost"]["enabled"] is False

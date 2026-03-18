"""
Tests for DnsSwitcher: correct netsh commands, restore command correctness (mocked subprocess).
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, call, MagicMock


class TestDnsSwitcher:

    @pytest.fixture
    def switcher(self):
        from core.dns_switcher import DnsSwitcher
        return DnsSwitcher()

    def test_providers_list(self, switcher):
        """get_providers() returns expected providers."""
        providers = switcher.get_providers()
        assert "cloudflare" in providers
        assert "google" in providers
        assert "quad9" in providers
        assert "custom" in providers

    def test_cloudflare_dns_values(self, switcher):
        """Cloudflare DNS uses 1.1.1.1 / 1.0.0.1."""
        cfg = switcher.DNS_PROVIDERS["cloudflare"]
        assert cfg["primary"] == "1.1.1.1"
        assert cfg["secondary"] == "1.0.0.1"

    def test_google_dns_values(self, switcher):
        cfg = switcher.DNS_PROVIDERS["google"]
        assert cfg["primary"] == "8.8.8.8"
        assert cfg["secondary"] == "8.8.4.4"

    def test_quad9_dns_values(self, switcher):
        cfg = switcher.DNS_PROVIDERS["quad9"]
        assert cfg["primary"] == "9.9.9.9"
        assert cfg["secondary"] == "149.112.112.112"

    @patch("subprocess.run")
    def test_set_dns_runs_correct_netsh_commands(self, mock_run, switcher):
        """set_dns() runs correct netsh commands for primary and secondary."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        switcher.set_dns("Wi-Fi", "1.1.1.1", "1.0.0.1")

        calls = mock_run.call_args_list
        args_list = [c[0][0] for c in calls]  # each call's first positional arg (the command list)

        # Should run at least 2 netsh commands
        assert len(calls) >= 2

        # First command sets primary DNS
        primary_cmd = args_list[0]
        assert "netsh" in primary_cmd
        assert "1.1.1.1" in primary_cmd
        # Should specify the adapter name
        assert "Wi-Fi" in " ".join(primary_cmd)

        # Second command sets secondary/alternate DNS
        secondary_cmd = args_list[1]
        assert "1.0.0.1" in secondary_cmd or "1.0.0.1" in " ".join(secondary_cmd)

    @patch("subprocess.run")
    def test_set_dhcp_dns_runs_correct_command(self, mock_run, switcher):
        """set_dhcp_dns() runs netsh to switch back to DHCP."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        switcher.set_dhcp_dns("Wi-Fi")

        calls = mock_run.call_args_list
        assert len(calls) >= 1
        cmd = " ".join(calls[0][0][0])
        assert "netsh" in cmd
        assert "dhcp" in cmd.lower()
        assert "Wi-Fi" in cmd

    @patch("subprocess.run")
    def test_apply_cloudflare_saves_backup(self, mock_run, switcher):
        """apply() with cloudflare returns a backup dict."""
        mock_run.return_value = MagicMock(returncode=0, stdout="DNS servers: 8.8.8.8\n", stderr="")

        # Mock get_active_adapter to avoid network calls
        switcher.get_active_adapter = MagicMock(return_value="Wi-Fi")
        switcher.get_current_dns = MagicMock(return_value={
            "primary": "8.8.8.8",
            "secondary": "8.8.4.4",
            "is_dhcp": False,
        })

        backup = switcher.apply("cloudflare", adapter="Wi-Fi")
        assert "adapter" in backup
        assert "original_dns" in backup
        assert backup["adapter"] == "Wi-Fi"

    @patch("subprocess.run")
    def test_restore_static_dns(self, mock_run, switcher):
        """restore() with static backup runs correct netsh command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        backup = {
            "adapter": "Wi-Fi",
            "original_dns": {"primary": "192.168.1.1", "secondary": "", "is_dhcp": False},
        }
        switcher.restore(backup)

        calls = mock_run.call_args_list
        assert len(calls) >= 1
        cmd = " ".join(calls[0][0][0])
        assert "192.168.1.1" in cmd

    @patch("subprocess.run")
    def test_restore_dhcp_dns(self, mock_run, switcher):
        """restore() with DHCP backup runs dhcp netsh command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        backup = {
            "adapter": "Wi-Fi",
            "original_dns": {"primary": "", "secondary": "", "is_dhcp": True},
        }
        switcher.restore(backup)

        calls = mock_run.call_args_list
        assert len(calls) >= 1
        cmd = " ".join(calls[0][0][0])
        assert "dhcp" in cmd.lower()

    @patch("subprocess.run")
    def test_custom_dns_apply(self, mock_run, switcher):
        """apply() with 'custom' provider uses provided IP addresses."""
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        switcher.get_active_adapter = MagicMock(return_value="Wi-Fi")
        switcher.get_current_dns = MagicMock(return_value={"primary": "", "secondary": "", "is_dhcp": True})

        backup = switcher.apply(
            "custom",
            adapter="Wi-Fi",
            custom_primary="10.0.0.1",
            custom_secondary="10.0.0.2",
        )

        calls = mock_run.call_args_list
        all_cmds = " ".join([" ".join(c[0][0]) for c in calls])
        assert "10.0.0.1" in all_cmds

    def test_get_current_dns_parses_output(self, switcher):
        """get_current_dns() parses netsh output correctly."""
        sample_output = (
            "Configuration for interface \"Wi-Fi\"\n"
            "    DNS servers configured through DHCP:  1.1.1.1\n"
            "                                         1.0.0.1\n"
            "    Register with which suffix:          Primary only\n"
        )
        with patch.object(switcher, "_run_netsh", return_value=sample_output):
            result = switcher.get_current_dns("Wi-Fi")
        assert result["primary"] == "1.1.1.1"

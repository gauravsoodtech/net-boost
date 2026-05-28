"""
Unit tests for core/system_tweaks.py.

Mock winreg / subprocess shims (the same idea as test_wifi_optimizer.py).
"""

from unittest.mock import MagicMock

import pytest

from core import system_tweaks


# ---------------------------------------------------------------------------
# Common monkeypatch helpers
# ---------------------------------------------------------------------------

class _FakeRegistry:
    """Tracks a flat {(subkey, value_name): value} map for read/write/delete."""

    def __init__(self, initial=None):
        self.data: dict[tuple[str, str], int | None] = dict(initial or {})
        self.writes: list[tuple[str, str, int]] = []
        self.deletes: list[tuple[str, str]] = []

    def read(self, subkey, value_name):
        return self.data.get((subkey, value_name))

    def write(self, subkey, value_name, value):
        self.data[(subkey, value_name)] = value
        self.writes.append((subkey, value_name, value))

    def delete(self, subkey, value_name):
        self.data.pop((subkey, value_name), None)
        self.deletes.append((subkey, value_name))


def _install_fake_registry(monkeypatch, fake):
    monkeypatch.setattr(system_tweaks, "_read_reg", fake.read)
    monkeypatch.setattr(system_tweaks, "_write_reg_dword", fake.write)
    monkeypatch.setattr(system_tweaks, "_delete_reg_value", fake.delete)


# ---------------------------------------------------------------------------
# MSI Mode
# ---------------------------------------------------------------------------

def _seed_pci_tree(monkeypatch, fake, *, include_nvidia=True, include_intel_wifi=True,
                    include_eth=False, nvidia_prev=None, intel_prev=None):
    """Pretend HKLM\\SYSTEM\\CurrentControlSet\\Enum\\PCI has a mocked layout."""
    nvidia_vendev = "VEN_10DE&DEV_28A0&SUBSYS_xxxx&REV_xx"
    intel_vendev  = "VEN_8086&DEV_7AF0&SUBSYS_xxxx&REV_xx"
    eth_vendev    = "VEN_8086&DEV_15F2&SUBSYS_xxxx&REV_xx"

    children = {
        system_tweaks.PCI_ENUM_BASE: [],
        f"{system_tweaks.PCI_ENUM_BASE}\\{nvidia_vendev}": ["4&abc&0&00E8"],
        f"{system_tweaks.PCI_ENUM_BASE}\\{intel_vendev}":  ["3&def&0&14E0"],
        f"{system_tweaks.PCI_ENUM_BASE}\\{eth_vendev}":    ["2&ghi&0&FEE0"],
    }
    if include_nvidia:
        children[system_tweaks.PCI_ENUM_BASE].append(nvidia_vendev)
    if include_intel_wifi:
        children[system_tweaks.PCI_ENUM_BASE].append(intel_vendev)
    if include_eth:
        children[system_tweaks.PCI_ENUM_BASE].append(eth_vendev)

    def fake_enum(subkey):
        return list(children.get(subkey, []))
    monkeypatch.setattr(system_tweaks, "_enum_subkeys", fake_enum)

    # Seed Service / ClassGUID values for each instance.
    if include_nvidia:
        inst = f"{system_tweaks.PCI_ENUM_BASE}\\{nvidia_vendev}\\4&abc&0&00E8"
        fake.data[(inst, "Service")] = "nvlddmkm"
        fake.data[(inst, "ClassGUID")] = "{4D36E968-E325-11CE-BFC1-08002BE10318}"
        msi_path = f"{inst}\\{system_tweaks.MSI_SUBPATH}"
        if nvidia_prev is not None:
            fake.data[(msi_path, system_tweaks.MSI_VALUE_NAME)] = nvidia_prev

    if include_intel_wifi:
        inst = f"{system_tweaks.PCI_ENUM_BASE}\\{intel_vendev}\\3&def&0&14E0"
        fake.data[(inst, "Service")] = "Netwtw14"
        fake.data[(inst, "ClassGUID")] = "{4D36E972-E325-11CE-BFC1-08002BE10318}"
        msi_path = f"{inst}\\{system_tweaks.MSI_SUBPATH}"
        if intel_prev is not None:
            fake.data[(msi_path, system_tweaks.MSI_VALUE_NAME)] = intel_prev

    if include_eth:
        # Intel Ethernet — Net class, but driver does NOT match Wi-Fi prefix.
        inst = f"{system_tweaks.PCI_ENUM_BASE}\\{eth_vendev}\\2&ghi&0&FEE0"
        fake.data[(inst, "Service")] = "e2fexpress"
        fake.data[(inst, "ClassGUID")] = "{4D36E972-E325-11CE-BFC1-08002BE10318}"

    return nvidia_vendev, intel_vendev, eth_vendev


def test_apply_msi_writes_value_for_nvidia_gpu_and_intel_wifi(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)
    _seed_pci_tree(monkeypatch, fake, nvidia_prev=0, intel_prev=0)

    backup = system_tweaks.apply_msi_mode_all()

    assert backup["_targets_found"] == 2
    assert backup["_writes_succeeded"] == 2
    assert backup["_access_denied"] is False
    written = {(s, n, v) for s, n, v in fake.writes}
    msi_writes = [w for w in written if w[1] == system_tweaks.MSI_VALUE_NAME and w[2] == 1]
    assert len(msi_writes) == 2
    # Both prior values were 0; restore must remember that.
    assert all(v == 0 for v in backup["values"].values())


def test_apply_msi_records_absent_sentinel_for_missing_key(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)
    # nvidia_prev=None → MSI key absent before apply
    _seed_pci_tree(monkeypatch, fake, nvidia_prev=None, intel_prev=1)

    backup = system_tweaks.apply_msi_mode_all()

    assert backup["_targets_found"] == 2
    assert backup["_writes_succeeded"] == 2
    # The NVIDIA instance had no prior value; its backup entry is the sentinel.
    assert system_tweaks.MSI_SENTINEL_ABSENT in backup["values"].values()
    # The Intel instance had a prior value of 1; that integer is preserved.
    assert 1 in backup["values"].values()


def test_apply_msi_skips_non_wifi_ethernet_devices(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)
    # Include the Ethernet device; it should be filtered out by _is_target_device.
    _seed_pci_tree(
        monkeypatch, fake,
        include_nvidia=False,
        include_intel_wifi=False,
        include_eth=True,
    )

    backup = system_tweaks.apply_msi_mode_all()

    assert backup["_targets_found"] == 0
    assert backup["values"] == {}
    assert fake.writes == []


def test_apply_msi_reports_access_denied_when_write_blocked(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)
    _seed_pci_tree(monkeypatch, fake, nvidia_prev=0, intel_prev=0)

    def deny(subkey, value_name, value):
        raise PermissionError("denied")
    monkeypatch.setattr(system_tweaks, "_write_reg_dword", deny)

    backup = system_tweaks.apply_msi_mode_all()

    assert backup["_targets_found"] == 2
    assert backup["_writes_succeeded"] == 0
    assert backup["_access_denied"] is True


def test_restore_msi_writes_prior_values_and_deletes_absent(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)

    backup = {
        "values": {
            "subkey-a": 0,                                 # had a 0 before apply
            "subkey-b": system_tweaks.MSI_SENTINEL_ABSENT, # key was absent before apply
        }
    }

    system_tweaks.restore_msi_mode(backup)

    assert ("subkey-a", system_tweaks.MSI_VALUE_NAME, 0) in fake.writes
    assert ("subkey-b", system_tweaks.MSI_VALUE_NAME) in fake.deletes


def test_restore_msi_is_safe_on_empty_or_missing_backup(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)

    system_tweaks.restore_msi_mode({})
    system_tweaks.restore_msi_mode(None)

    assert fake.writes == []
    assert fake.deletes == []


# ---------------------------------------------------------------------------
# NDU service
# ---------------------------------------------------------------------------

def test_disable_ndu_shells_sc_config_and_captures_prior_start(monkeypatch):
    fake = _FakeRegistry({(system_tweaks.NDU_REG_PATH, system_tweaks.NDU_VALUE_NAME): 2})
    _install_fake_registry(monkeypatch, fake)

    sc_calls = []
    def fake_run(args, capture_output, text, timeout):
        sc_calls.append(args)
        result = MagicMock()
        result.returncode = 0
        result.stdout = "[SC] ChangeServiceConfig SUCCESS"
        result.stderr = ""
        return result
    monkeypatch.setattr(system_tweaks.subprocess, "run", fake_run)

    backup = system_tweaks.disable_ndu_service()

    assert backup["start"] == 2
    assert backup["_ok"] is True
    assert sc_calls[0] == ["sc.exe", "config", "Ndu", "start=disabled"]


def test_disable_ndu_reports_failure_when_sc_returns_nonzero(monkeypatch):
    fake = _FakeRegistry({(system_tweaks.NDU_REG_PATH, system_tweaks.NDU_VALUE_NAME): 2})
    _install_fake_registry(monkeypatch, fake)

    def fake_run(args, capture_output, text, timeout):
        result = MagicMock()
        result.returncode = 5
        result.stdout = ""
        result.stderr = "Access is denied."
        return result
    monkeypatch.setattr(system_tweaks.subprocess, "run", fake_run)

    backup = system_tweaks.disable_ndu_service()

    assert backup["_ok"] is False
    assert "denied" in backup["_error"].lower()


def test_restore_ndu_maps_prior_dword_back_to_sc_token(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)

    sc_calls = []
    def fake_run(args, capture_output, text, timeout):
        sc_calls.append(args)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result
    monkeypatch.setattr(system_tweaks.subprocess, "run", fake_run)

    # Prior Start=2 → sc.exe config ... start=auto
    system_tweaks.restore_ndu_service({"start": 2})
    assert sc_calls[-1] == ["sc.exe", "config", "Ndu", "start=auto"]

    # Prior Start=3 → start=demand
    system_tweaks.restore_ndu_service({"start": 3})
    assert sc_calls[-1] == ["sc.exe", "config", "Ndu", "start=demand"]

    # No prior recorded → fallback "demand"
    system_tweaks.restore_ndu_service({})
    assert sc_calls[-1] == ["sc.exe", "config", "Ndu", "start=demand"]


# ---------------------------------------------------------------------------
# NetworkThrottlingIndex
# ---------------------------------------------------------------------------

def test_disable_throttling_writes_max_dword_and_records_prior(monkeypatch):
    fake = _FakeRegistry({
        (system_tweaks.THROTTLING_REG_PATH, system_tweaks.THROTTLING_VALUE_NAME): 10,
    })
    _install_fake_registry(monkeypatch, fake)

    backup = system_tweaks.disable_network_throttling()

    assert backup["prev_value"] == 10
    assert backup["_ok"] is True
    assert (
        system_tweaks.THROTTLING_REG_PATH,
        system_tweaks.THROTTLING_VALUE_NAME,
        system_tweaks.THROTTLING_DISABLED,
    ) in fake.writes


def test_disable_throttling_handles_missing_prior_value(monkeypatch):
    fake = _FakeRegistry()  # no prior value
    _install_fake_registry(monkeypatch, fake)

    backup = system_tweaks.disable_network_throttling()

    assert backup["prev_value"] is None
    assert backup["_ok"] is True


def test_restore_throttling_writes_prior_value(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)

    system_tweaks.restore_network_throttling({"prev_value": 10})

    assert (
        system_tweaks.THROTTLING_REG_PATH,
        system_tweaks.THROTTLING_VALUE_NAME,
        10,
    ) in fake.writes


def test_restore_throttling_deletes_when_prior_was_absent(monkeypatch):
    fake = _FakeRegistry()
    _install_fake_registry(monkeypatch, fake)

    system_tweaks.restore_network_throttling({"prev_value": None})

    assert (
        system_tweaks.THROTTLING_REG_PATH,
        system_tweaks.THROTTLING_VALUE_NAME,
    ) in fake.deletes
    assert fake.writes == []

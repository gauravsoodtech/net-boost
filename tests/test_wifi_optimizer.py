from core import wifi_optimizer


def test_apply_writes_current_intel_ax211_driver_keywords(monkeypatch):
    writes = []
    reads = {
        "RoamingPreferredBandType": 4,
        "IbssTxPower": 75,
        "ThroughputBoosterEnabled": 0,
        "MIMOPowerSaveMode": 0,
    }

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: reads.get(value))

    def write_reg(subkey, value, new_value):
        writes.append((subkey, value, new_value))
        reads[value] = new_value

    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        write_reg,
    )

    backup = wifi_optimizer.apply(
        {
            "disable_power_saving": True,
            "minimize_roaming": True,
            "max_tx_power": True,
            "disable_bss_scan": True,
            "prefer_6ghz": True,
            "throughput_booster": True,
            "disable_mimo_power_save": True,
            "disable_lso": True,
            "disable_interrupt_mod": True,
        }
    )

    assert ("adapter-key", "RoamAggressiveness", 0) in writes
    assert ("adapter-key", "IbssTxPower", 100) in writes
    assert ("adapter-key", "RoamingPreferredBandType", 3) in writes
    assert ("adapter-key", "ThroughputBoosterEnabled", 1) in writes
    assert ("adapter-key", "MIMOPowerSaveMode", 3) in writes
    assert ("adapter-key", "*LsoV2IPv4", 0) in writes
    assert ("adapter-key", "*LsoV2IPv6", 0) in writes
    assert ("adapter-key", "InterruptModeration", 0) in writes
    assert backup["_adapter_found"] is True
    assert backup["_write_count"] == len(writes)
    assert backup["_verified_count"] == len(writes)
    assert backup["_failed_values"] == []


def test_apply_keeps_legacy_keyword_fallbacks_for_older_drivers(monkeypatch):
    writes = []

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(
        wifi_optimizer,
        "_read_reg",
        lambda subkey, value: 1 if value == "PreferredBand" else None,
    )
    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((value, new_value)),
    )

    wifi_optimizer.apply(
        {
            "max_tx_power": True,
            "prefer_6ghz": True,
            "throughput_booster": True,
            "disable_mimo_power_save": True,
        }
    )

    assert ("TxPowerLevel", 5) in writes
    assert ("PreferredBand", 3) in writes
    assert ("Throughput Booster", 1) in writes
    assert ("MIMO Power Save Mode", 3) in writes


def test_apply_clears_disabled_throughput_booster_keywords(monkeypatch):
    writes = []
    reads = {
        "ThroughputBoosterEnabled": 1,
        "Throughput Booster": 1,
    }

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: reads.get(value))
    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((value, new_value)),
    )

    wifi_optimizer.apply({"throughput_booster": False})

    assert ("ThroughputBoosterEnabled", 0) in writes
    assert ("Throughput Booster", 0) in writes


def test_get_current_band_prefers_current_intel_driver_keyword(monkeypatch):
    values = {
        "RoamingPreferredBandType": 4,
        "PreferredBand": 1,
    }

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: values.get(value))

    assert wifi_optimizer.get_current_band() == "5GHz + 6GHz"


def test_apply_reports_adapter_not_found(monkeypatch):
    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: None)

    backup = wifi_optimizer.apply({"disable_lso": True})

    assert backup["_adapter_found"] is False
    assert backup["_write_count"] == 0
    assert backup["_verified_count"] == 0
    assert backup["_failed_values"] == []


def test_apply_reports_readback_mismatch(monkeypatch):
    writes = []

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: 1)
    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((value, new_value)),
    )

    backup = wifi_optimizer.apply({"disable_power_saving": True})

    assert writes == [("PowerSavingMode", 0)]
    assert backup["_write_count"] == 1
    assert backup["_verified_count"] == 0
    assert backup["_failed_count"] == 1
    assert backup["_failed_values"][0]["name"] == "PowerSavingMode"
    assert backup["_failed_values"][0]["reason"] == "readback mismatch"


def test_apply_reports_unsupported_preferred_band(monkeypatch):
    writes = []

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: None)
    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((value, new_value)),
    )

    backup = wifi_optimizer.apply({"prefer_6ghz": True})

    assert writes == []
    assert backup["_6ghz_unsupported"] is True
    assert backup["_unsupported_values"] == ["RoamingPreferredBandType", "PreferredBand"]
    assert backup["_write_count"] == 0


# ---------------------------------------------------------------------------
# Adapter restart — driver only re-reads advanced params on a miniport reset
# ---------------------------------------------------------------------------

def test_apply_flags_requires_restart_when_a_value_changes(monkeypatch):
    reads = {"DriverDesc": "Intel(R) Wi-Fi 6E AX211 160MHz"}

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: reads.get(value))

    def write_reg(subkey, value, new_value):
        reads[value] = new_value

    monkeypatch.setattr(wifi_optimizer, "_write_reg", write_reg)

    # *LsoV2IPv4/6 start absent (None) → written to 0 → changed.
    backup = wifi_optimizer.apply({"disable_lso": True})

    assert backup["_requires_restart"] is True
    assert backup["_changed_count"] == 2          # IPv4 + IPv6
    assert backup["_driver_desc"] == "Intel(R) Wi-Fi 6E AX211 160MHz"


def test_apply_no_restart_when_values_already_set(monkeypatch):
    # Registry already holds the target value, so nothing changes and the
    # adapter must NOT be restarted (no needless Wi-Fi drop).
    def fake_read(subkey, value):
        if value == "DriverDesc":
            return "Intel(R) Wi-Fi 6E AX211 160MHz"
        return 0   # *LsoV2IPv4/6 already 0

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", fake_read)
    monkeypatch.setattr(wifi_optimizer, "_write_reg", lambda *a, **k: None)

    backup = wifi_optimizer.apply({"disable_lso": True})

    assert backup["_verified_count"] == 2          # writes still verify
    assert backup["_changed_count"] == 0
    assert backup["_requires_restart"] is False


def test_restore_does_not_mutate_backup_metadata(monkeypatch):
    writes = []

    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((subkey, value, new_value)),
    )
    monkeypatch.setattr(wifi_optimizer, "_delete_reg", lambda *a, **k: None)

    backup = {
        "_adapter_key": "adapter-key",
        "_requires_restart": True,
        "_driver_desc": "Intel AX211",
        "PowerSavingMode": 1,
    }

    wifi_optimizer.restore(backup)

    assert backup["_adapter_key"] == "adapter-key"
    assert backup["_requires_restart"] is True
    assert backup["_driver_desc"] == "Intel AX211"
    assert writes == [("adapter-key", "PowerSavingMode", 1)]


def test_restart_adapter_runs_targeted_powershell(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(wifi_optimizer.subprocess, "run", fake_run)

    res = wifi_optimizer.restart_adapter("Intel(R) Wi-Fi 6E AX211 160MHz")

    assert res == {"ok": True, "error": ""}
    assert captured["cmd"][0] == "powershell"
    script = captured["cmd"][-1]
    assert "Restart-NetAdapter" in script
    assert "-InterfaceDescription" in script
    assert "AX211" in script
    assert captured["kwargs"]["timeout"] == 30


def test_restart_adapter_falls_back_to_regex_match(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(wifi_optimizer.subprocess, "run", fake_run)

    res = wifi_optimizer.restart_adapter()   # no driver desc

    assert res["ok"] is True
    script = captured["cmd"][-1]
    assert "Get-NetAdapter" in script
    assert "Intel.*(Wi-Fi|Wireless|AX)" in script
    assert "Restart-NetAdapter" in script


def test_restart_adapter_reports_failure(monkeypatch):
    class _Result:
        returncode = 1
        stdout = ""
        stderr = "Restart-NetAdapter : Access denied"

    monkeypatch.setattr(wifi_optimizer.subprocess, "run", lambda cmd, **k: _Result())

    res = wifi_optimizer.restart_adapter("Intel AX211")

    assert res["ok"] is False
    assert "Access denied" in res["error"]


def test_restart_adapter_handles_timeout(monkeypatch):
    import subprocess as _sp

    def fake_run(cmd, **kwargs):
        raise _sp.TimeoutExpired(cmd, kwargs.get("timeout", 30))

    monkeypatch.setattr(wifi_optimizer.subprocess, "run", fake_run)

    res = wifi_optimizer.restart_adapter("Intel AX211")

    assert res["ok"] is False
    assert res["error"] == "restart timed out"


def test_class_wrapper_delegates_to_restart_adapter(monkeypatch):
    seen = {}

    def fake_restart(desc=None):
        seen["desc"] = desc
        return {"ok": True, "error": ""}

    monkeypatch.setattr(wifi_optimizer, "restart_adapter", fake_restart)

    res = wifi_optimizer.WifiOptimizer().restart_adapter("Intel AX211")

    assert res == {"ok": True, "error": ""}
    assert seen["desc"] == "Intel AX211"

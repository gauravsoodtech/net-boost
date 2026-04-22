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
    monkeypatch.setattr(
        wifi_optimizer,
        "_write_reg",
        lambda subkey, value, new_value: writes.append((subkey, value, new_value)),
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


def test_get_current_band_prefers_current_intel_driver_keyword(monkeypatch):
    values = {
        "RoamingPreferredBandType": 4,
        "PreferredBand": 1,
    }

    monkeypatch.setattr(wifi_optimizer, "get_wifi_adapter_key", lambda: "adapter-key")
    monkeypatch.setattr(wifi_optimizer, "_read_reg", lambda subkey, value: values.get(value))

    assert wifi_optimizer.get_current_band() == "5GHz + 6GHz"

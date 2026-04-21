"""
core/settings_risk.py
Risk metadata registry for NetBoost toggle settings.
Maps every UI key → risk level, affected tab, cause, and remediation advice.
"""

RISK_REGISTRY: dict[str, dict] = {
    # ------------------------------------------------------------------ Wi-Fi
    "disable_lso": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Disable Large Send Offload (LSO)",
        "cause": "Eliminates NIC packet-batching delays — key fix for in-game ping spikes.",
        "advice": "Safe to leave on. Required reboot only if NIC driver re-enables it.",
    },
    "disable_interrupt_mod": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Disable Interrupt Moderation",
        "cause": "Forces immediate CPU interrupt per packet — reduces jitter.",
        "advice": "Slightly higher CPU usage; reverts on restore.",
    },
    "minimize_roaming": {
        "level": "HIGH",
        "tab": "wifi",
        "display": "Minimize Roaming Aggressiveness",
        "cause": "RoamAggressiveness=1 causes 100–500 ms drops during AP handoffs.",
        "advice": "Disable first if you see random disconnects.",
    },
    "prefer_6ghz": {
        "level": "MEDIUM",
        "tab": "wifi",
        "display": "Prefer 6 GHz Band",
        "cause": "Forces 6 GHz band — brief reconnect when Windows re-evaluates.",
        "advice": "Only useful if your router has a 6 GHz radio.",
    },
    "disable_bss_scan": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Disable BSS Scan",
        "cause": "Prevents background channel scans.",
        "advice": "Generally safe; reduces scan-induced micro-drops.",
    },
    "disable_power_saving": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Disable Wi-Fi Power Saving",
        "cause": "Keeps radio at full power — increases battery draw.",
        "advice": "Disable if on battery for extended sessions.",
    },
    "max_tx_power": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Max Transmit Power",
        "cause": "Sets TX power to maximum.",
        "advice": "May increase heat on the Wi-Fi adapter.",
    },
    "throughput_booster": {
        "level": "MEDIUM",
        "tab": "wifi",
        "display": "Throughput Booster",
        "cause": "Throughput-oriented packet bursting can compete with latency stability.",
        "advice": "Keep off for Stable Ping Mode; test manually only if upload throughput matters.",
    },
    "disable_mimo_power_save": {
        "level": "LOW",
        "tab": "wifi",
        "display": "Disable MIMO Power Save",
        "cause": "Keeps all MIMO chains active.",
        "advice": "Minor battery impact.",
    },

    # ------------------------------------------------------------------ FPS — GPU
    "nvidia_max_perf": {
        "level": "MEDIUM",
        "tab": "fps",
        "display": "NVIDIA Maximum Performance",
        "cause": "Locks GPU at max clock. RTX 4060 Laptop thermal-throttles hard after ~10 min.",
        "advice": "Disable if FPS drops after 10 min. Check laptop cooling.",
    },
    "disable_hags": {
        "level": "MEDIUM",
        "tab": "fps",
        "display": "Disable HAGS",
        "cause": "HAGS disable requires a reboot. Mismatched state until reboot.",
        "advice": "Reboot after applying.",
    },
    "pcores_affinity": {
        "level": "MEDIUM",
        "tab": "fps",
        "display": "P-Core Affinity",
        "cause": "Restricts game to P-cores. Can hurt if CS2 shader threads need E-cores.",
        "advice": "Disable if you see micro-stutters.",
    },
    "nvidia_ull": {
        "level": "LOW",
        "tab": "fps",
        "display": "NVIDIA Ultra Low Latency",
        "cause": "Enables ULL mode in the driver.",
        "advice": "Low risk; reverts on restore.",
    },
    "power_plan": {
        "level": "LOW",
        "tab": "fps",
        "display": "High Performance Power Plan",
        "cause": "Switches Windows power plan to High Performance.",
        "advice": "Increases power draw; reverts on restore.",
    },
    "timer_resolution": {
        "level": "LOW",
        "tab": "fps",
        "display": "0.5 ms Timer Resolution",
        "cause": "Sets system timer to 0.5 ms.",
        "advice": "Reverts automatically on restore.",
    },
    "game_dvr_off": {
        "level": "LOW",
        "tab": "fps",
        "display": "Disable Game DVR",
        "cause": "Turns off Xbox Game Bar recording.",
        "advice": "Low risk; reverts on restore.",
    },
    "sysmain_off": {
        "level": "LOW",
        "tab": "fps",
        "display": "Disable SysMain",
        "cause": "Stops the SysMain (Superfetch) service.",
        "advice": "Cold-boot app loading may be slower.",
    },
    "visual_effects_off": {
        "level": "LOW",
        "tab": "fps",
        "display": "Disable Visual Effects",
        "cause": "Turns off Windows animations.",
        "advice": "Low risk; reverts on restore.",
    },
    "fullscreen_opt_off": {
        "level": "LOW",
        "tab": "fps",
        "display": "Disable Fullscreen Optimizations",
        "cause": "Disables DWG fullscreen optimizations.",
        "advice": "Low risk; reverts on restore.",
    },

    # ------------------------------------------------------------------ Optimizer
    "pause_onedrive": {
        "level": "HIGH",
        "tab": "optimizer",
        "display": "Pause OneDrive",
        "cause": "Suspending OneDrive mid-sync can leave files in a partial/corrupt state.",
        "advice": "Only apply if OneDrive is not actively syncing.",
    },
    "tcp_window_scale": {
        "level": "MEDIUM",
        "tab": "optimizer",
        "display": "TCP Window Scaling",
        "cause": "Some ISP routers mishandle window scaling — causes TCP stalls.",
        "advice": "Disable if web browsing becomes unreliable after applying.",
    },
    "tcp_no_delay": {
        "level": "MEDIUM",
        "tab": "optimizer",
        "display": "TCP No-Delay (Nagle off)",
        "cause": "System-wide TCP tweak; VALORANT gameplay traffic is UDP, so this usually will not stabilize match ping.",
        "advice": "Leave off for Stable Ping Mode unless you are testing a TCP-heavy game or app.",
    },
    "tcp_ack_freq": {
        "level": "MEDIUM",
        "tab": "optimizer",
        "display": "TCP ACK Frequency",
        "cause": "System-wide delayed-ACK tweak; it does not target VALORANT's UDP game packets.",
        "advice": "Leave off for Stable Ping Mode; apply manually only for measured TCP latency issues.",
    },
    "switch_dns": {
        "level": "LOW",
        "tab": "optimizer",
        "display": "Switch DNS Provider",
        "cause": "Changes system DNS server.",
        "advice": "Reverts on restore.",
    },
    "pause_windows_update": {
        "level": "LOW",
        "tab": "optimizer",
        "display": "Pause Windows Update",
        "cause": "Suspends the Windows Update service during gaming.",
        "advice": "Remember to restore when done gaming.",
    },
    "pause_bits": {
        "level": "LOW",
        "tab": "optimizer",
        "display": "Pause BITS",
        "cause": "Stops background download transfers.",
        "advice": "Low risk; reverts on restore.",
    },
    "pause_telemetry": {
        "level": "LOW",
        "tab": "optimizer",
        "display": "Pause Windows Telemetry",
        "cause": "DiagTrack sends telemetry bursts that cause brief network congestion spikes.",
        "advice": "Safe; telemetry resumes on restore or next boot.",
    },
}

_LEVEL_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def get_risk(key: str) -> dict | None:
    """Return the risk entry for *key*, or None if not found."""
    return RISK_REGISTRY.get(key)


def filter_by_level(
    keys: list[str], min_level: str = "MEDIUM"
) -> list[tuple[str, dict]]:
    """
    Return (key, entry) pairs for *keys* whose level >= *min_level*,
    sorted HIGH → MEDIUM → LOW.

    Parameters
    ----------
    keys      : toggle key names to check
    min_level : minimum level to include ("HIGH", "MEDIUM", or "LOW")
    """
    threshold = _LEVEL_ORDER.get(min_level, 1)
    results = []
    for key in keys:
        entry = RISK_REGISTRY.get(key)
        if entry and _LEVEL_ORDER.get(entry["level"], 2) <= threshold:
            results.append((key, entry))
    results.sort(key=lambda x: _LEVEL_ORDER.get(x[1]["level"], 2))
    return results

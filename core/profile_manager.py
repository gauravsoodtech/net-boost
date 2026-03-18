"""
profile_manager.py — JSON-based optimizer profile management for NetBoost.

Profiles are stored as individual JSON files under:
    %APPDATA%\\NetBoost\\profiles\\<name>.json

The active profile name is persisted in:
    %APPDATA%\\NetBoost\\active_profile.txt
"""

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NetBoost")
_PROFILES_DIR = os.path.join(_BASE_DIR, "profiles")
_ACTIVE_FILE = os.path.join(_BASE_DIR, "active_profile.txt")


def _ensure_dirs() -> None:
    os.makedirs(_PROFILES_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Profile schema helpers
# ---------------------------------------------------------------------------

def _empty_profile(name: str = "") -> dict:
    """Return a profile dict populated with all keys set to their off/default values."""
    return {
        "name": name,
        "dns": {
            "switch_dns": False,
            "dns_provider": "Cloudflare 1.1.1.1",
            "dns_primary": "",
            "dns_secondary": "",
        },
        "tcp_optimizer": {
            "tcp_no_delay": False,
            "tcp_ack_freq": False,
            "tcp_window_scale": False,
            "enabled": False,
        },
        "bandwidth": {
            "game_priority": False,
            "enabled": False,
        },
        "background_killer": {
            "pause_windows_update": False,
            "pause_onedrive": False,
            "pause_bits": False,
            "enabled": False,
        },
        "fps_boost": {
            "power_plan": False,
            "pcores_affinity": False,
            "timer_resolution": False,
            "game_dvr_off": False,
            "nvidia_max_perf": False,
            "nvidia_ull": False,
            "disable_hags": False,
            "fullscreen_opt_off": False,
            "sysmain_off": False,
            "visual_effects_off": False,
            "enabled": False,
        },
        "ping_monitor": {
            "host": "1.1.1.1",
            "interval_ms": 500,
        },
        "game_list": [],
        "wifi_optimizer": {
            "disable_power_saving": False,
            "minimize_roaming": False,
            "prefer_6ghz": False,
            "max_tx_power": False,
            "disable_bss_scan": False,
            "throughput_booster": False,
            "disable_mimo_power_save": False,
            "enabled": False,
        },
        "nvidia_optimizer": {
            "dynamic_pstate_off": False,
            "ull_mode": False,
            "max_power": False,
            "enabled": False,
        },
    }


# ---------------------------------------------------------------------------
# Built-in default profiles
# ---------------------------------------------------------------------------

def _build_gaming_profile() -> dict:
    p = _empty_profile("Gaming")
    p["dns"].update({"switch_dns": True, "dns_provider": "Cloudflare 1.1.1.1", "dns_primary": "1.1.1.1", "dns_secondary": "1.0.0.1"})
    p["tcp_optimizer"].update({"tcp_no_delay": True, "tcp_ack_freq": True, "tcp_window_scale": True, "enabled": True})
    p["bandwidth"].update({"game_priority": True, "enabled": True})
    p["background_killer"].update({"pause_windows_update": True, "pause_onedrive": True, "pause_bits": True, "enabled": True})
    p["fps_boost"].update({
        "power_plan": True,
        "pcores_affinity": True,
        "timer_resolution": True,
        "game_dvr_off": True,
        "nvidia_max_perf": True,
        "nvidia_ull": False,
        "disable_hags": False,
        "fullscreen_opt_off": True,
        "sysmain_off": True,
        "visual_effects_off": True,
        "enabled": True,
    })
    p["ping_monitor"].update({"host": "1.1.1.1", "interval_ms": 500})
    p["wifi_optimizer"].update({
        "disable_power_saving": True,
        "minimize_roaming": True,
        "prefer_6ghz": True,
        "max_tx_power": True,
        "disable_bss_scan": True,
        "throughput_booster": True,
        "disable_mimo_power_save": True,
        "enabled": True,
    })
    p["nvidia_optimizer"].update({"dynamic_pstate_off": True, "ull_mode": True, "max_power": True, "enabled": True})
    return p


def _build_work_profile() -> dict:
    p = _empty_profile("Work")
    p["dns"].update({"switch_dns": True, "dns_provider": "Google 8.8.8.8", "dns_primary": "8.8.8.8", "dns_secondary": "8.8.4.4"})
    p["tcp_optimizer"].update({"tcp_no_delay": False, "tcp_ack_freq": True, "tcp_window_scale": True, "enabled": True})
    p["bandwidth"].update({"game_priority": False, "enabled": False})
    p["background_killer"].update({"pause_windows_update": False, "pause_onedrive": False, "pause_bits": False, "enabled": False})
    p["fps_boost"].update({
        "power_plan": False,
        "pcores_affinity": False,
        "timer_resolution": False,
        "game_dvr_off": False,
        "nvidia_max_perf": False,
        "nvidia_ull": False,
        "disable_hags": False,
        "fullscreen_opt_off": False,
        "sysmain_off": False,
        "visual_effects_off": False,
        "enabled": False,
    })
    p["ping_monitor"].update({"host": "8.8.8.8", "interval_ms": 1000})
    p["wifi_optimizer"].update({
        "disable_power_saving": True,
        "minimize_roaming": False,
        "prefer_6ghz": False,
        "max_tx_power": False,
        "disable_bss_scan": False,
        "throughput_booster": False,
        "disable_mimo_power_save": False,
        "enabled": True,
    })
    p["nvidia_optimizer"].update({"dynamic_pstate_off": False, "ull_mode": False, "max_power": False, "enabled": False})
    return p


def _build_default_profile() -> dict:
    """Baseline profile — everything off, system defaults."""
    return _empty_profile("Default")


_BUILTIN_PROFILES = {
    "Gaming": _build_gaming_profile,
    "Work": _build_work_profile,
    "Default": _build_default_profile,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _profile_path(name: str) -> str:
    return os.path.join(_PROFILES_DIR, f"{name}.json")


def _write_profile(name: str, profile: dict) -> None:
    _ensure_dirs()
    path = _profile_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)
    os.replace(tmp, path)


def _seed_defaults() -> None:
    """Write built-in profiles to disk if no profiles exist yet."""
    _ensure_dirs()
    existing = [
        f for f in os.listdir(_PROFILES_DIR) if f.endswith(".json")
    ]
    if existing:
        return
    logger.info("No profiles found; seeding default profiles.")
    for name, factory in _BUILTIN_PROFILES.items():
        _write_profile(name, factory())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all() -> dict[str, dict]:
    """
    Return all profiles as a mapping of ``{name: profile_dict}``.

    Seeds the built-in defaults if the profiles directory is empty.
    """
    _seed_defaults()
    profiles: dict[str, dict] = {}
    try:
        for filename in os.listdir(_PROFILES_DIR):
            if not filename.endswith(".json"):
                continue
            name = filename[:-5]  # strip .json
            try:
                path = os.path.join(_PROFILES_DIR, filename)
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Ensure the stored name matches the file name.
                data["name"] = name
                profiles[name] = data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping corrupt profile file '%s': %s", filename, exc)
    except OSError as exc:
        logger.error("Could not list profiles directory: %s", exc)
    return profiles


def save_profile(name: str, profile_dict: dict) -> None:
    """Persist *profile_dict* under *name*, overwriting any existing profile."""
    profile_dict = dict(profile_dict)
    profile_dict["name"] = name
    _write_profile(name, profile_dict)
    logger.info("Profile '%s' saved.", name)


def load_profile(name: str) -> dict:
    """
    Load and return the profile named *name*.

    Raises :class:`KeyError` if no such profile exists.
    """
    path = _profile_path(name)
    if not os.path.isfile(path):
        # Maybe the defaults haven't been seeded yet.
        _seed_defaults()
        if not os.path.isfile(path):
            raise KeyError(f"Profile '{name}' does not exist.")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["name"] = name
    return data


def delete_profile(name: str) -> None:
    """Delete the profile named *name*. No-op if it does not exist."""
    path = _profile_path(name)
    try:
        os.remove(path)
        logger.info("Profile '%s' deleted.", name)
    except FileNotFoundError:
        pass


def get_profile(name: str) -> dict | None:
    """Return the profile named *name*, or None if it does not exist."""
    try:
        return load_profile(name)
    except KeyError:
        return None


def list_profiles() -> list[str]:
    """Return a sorted list of available profile names."""
    _seed_defaults()
    try:
        names = [
            f[:-5] for f in os.listdir(_PROFILES_DIR) if f.endswith(".json")
        ]
        return sorted(names)
    except OSError:
        return []


def import_profile(filepath: str) -> str:
    """
    Import a profile JSON file from *filepath*.

    The profile ``name`` field inside the file is used as the profile name
    (defaulting to the file stem if absent).  Returns the imported profile
    name.
    """
    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    name = data.get("name") or os.path.splitext(os.path.basename(filepath))[0]
    data["name"] = name
    save_profile(name, data)
    logger.info("Imported profile '%s' from '%s'.", name, filepath)
    return name


def export_profile(name: str, filepath: str) -> None:
    """Export the profile *name* to *filepath* as a JSON file."""
    profile = load_profile(name)
    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)
    logger.info("Exported profile '%s' to '%s'.", name, filepath)


def get_active() -> dict:
    """
    Return the currently active profile dict.

    Falls back to the "Gaming" profile (or the first available profile) if the
    active profile file is missing or refers to a non-existent profile.
    """
    name = _read_active_name()
    if name:
        try:
            return load_profile(name)
        except KeyError:
            logger.warning("Active profile '%s' not found; falling back.", name)

    # Fallback order: Gaming > Default > first available
    for fallback in ("Gaming", "Default"):
        try:
            return load_profile(fallback)
        except KeyError:
            pass

    names = list_profiles()
    if names:
        return load_profile(names[0])

    # Absolute last resort: return an empty default profile in memory.
    logger.warning("No profiles available; returning in-memory Default.")
    return _build_default_profile()


def set_active(name: str) -> None:
    """
    Persist *name* as the active profile.

    Raises :class:`KeyError` if no profile with that name exists.
    """
    # Validate existence first.
    load_profile(name)
    _ensure_dirs()
    tmp = _ACTIVE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(name)
    os.replace(tmp, _ACTIVE_FILE)
    logger.info("Active profile set to '%s'.", name)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _read_active_name() -> str:
    """Read the stored active profile name, or return empty string."""
    try:
        with open(_ACTIVE_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except (FileNotFoundError, OSError):
        return ""


# ---------------------------------------------------------------------------
# Class wrapper (used by main.py and main_window.py)
# ---------------------------------------------------------------------------

class ProfileManager:
    """Thin class wrapper around the module-level profile functions."""

    def load_all(self) -> dict:
        return load_all()

    def list_profiles(self) -> list:
        return list_profiles()

    def get_active(self) -> dict:
        return get_active()

    def set_active(self, name: str) -> None:
        set_active(name)

    def load_profile(self, name: str) -> dict:
        return load_profile(name)

    def save_profile(self, name: str, profile_dict: dict) -> None:
        save_profile(name, profile_dict)

    def delete_profile(self, name: str) -> None:
        delete_profile(name)

    def get_profile(self, name: str) -> dict | None:
        return get_profile(name)

    def import_profile(self, filepath: str) -> str:
        return import_profile(filepath)

    def export_profile(self, name: str, filepath: str) -> None:
        export_profile(name, filepath)

"""
Guard tests for core/setting_keys.py — the single source of truth for toggle
key names.

Every layer that references a toggle key must agree with the canonical key set:
  * the UI tabs (where keys originate),
  * core/settings_risk.py (risk metadata),
  * core/stable_ping_policy.py (Game Mode bundles),
  * core/profile_manager.py (profile JSON schema).

A mismatch means a toggle silently no-ops in production (CLAUDE.md: "Mismatches
cause silent no-ops").  These tests turn that silent failure into a loud one.
"""

from core import setting_keys as sk
from core import stable_ping_policy as policy
from core.profile_manager import _empty_profile
from core.settings_risk import RISK_REGISTRY


# ------------------------------------------------------------- internal shape

def test_categories_are_disjoint_and_partition_all_keys():
    wifi, fps, opt = set(sk.WIFI_KEYS), set(sk.FPS_KEYS), set(sk.OPTIMIZER_KEYS)
    assert wifi & fps == set()
    assert wifi & opt == set()
    assert fps & opt == set()
    assert wifi | fps | opt == sk.ALL_KEYS


def test_no_duplicate_keys_within_a_category():
    for name, keys in (("WIFI", sk.WIFI_KEYS), ("FPS", sk.FPS_KEYS),
                       ("OPTIMIZER", sk.OPTIMIZER_KEYS)):
        assert len(keys) == len(set(keys)), f"duplicate key in {name}_KEYS"


def test_expected_partition_sizes():
    # Tripwire: changing these counts must be deliberate.  If you add or remove
    # a toggle, update the tab row, the settings_risk entry, the profile field,
    # AND this count together — that is the whole point of the guard.
    assert len(sk.WIFI_KEYS) == 9
    assert len(sk.FPS_KEYS) == 10
    assert len(sk.OPTIMIZER_KEYS) == 11
    assert len(sk.ALL_KEYS) == 30


def test_optimizer_subgroups_partition_optimizer_keys():
    sub = (set(sk.TCP_KEYS) | set(sk.DNS_KEYS)
           | set(sk.BACKGROUND_KILLER_KEYS) | set(sk.SYSTEM_TWEAK_KEYS))
    assert sub == set(sk.OPTIMIZER_KEYS)


def test_fps_subgroups_partition_fps_keys():
    assert set(sk.FPS_CPU_KEYS) | set(sk.FPS_GPU_KEYS) == set(sk.FPS_KEYS)
    assert set(sk.FPS_CPU_KEYS) & set(sk.FPS_GPU_KEYS) == set()


# --------------------------------------------------------- stable_ping_policy

def test_stable_ping_policy_reexports_canonical_tuples():
    assert policy.WIFI_SETTING_KEYS == sk.WIFI_KEYS
    assert policy.FPS_SETTING_KEYS == sk.FPS_KEYS
    assert policy.OPTIMIZER_SETTING_KEYS == sk.OPTIMIZER_KEYS


def test_game_mode_enabled_subsets_are_within_canonical_keys():
    assert policy.VALORANT_WIFI_ENABLED_KEYS <= set(sk.WIFI_KEYS)
    assert policy.CS2_WIFI_ENABLED_KEYS <= set(sk.WIFI_KEYS)
    assert policy.CS2_FPS_ENABLED_KEYS <= set(sk.FPS_KEYS)
    assert policy.CS2_OPTIMIZER_ENABLED_KEYS <= set(sk.OPTIMIZER_KEYS)


# ------------------------------------------------------------- settings_risk

def test_risk_registry_covers_exactly_the_canonical_keys():
    assert set(RISK_REGISTRY) == sk.ALL_KEYS


def test_risk_registry_tab_matches_canonical_owner():
    for key, entry in RISK_REGISTRY.items():
        assert entry["tab"] == sk.TAB_BY_KEY[key], (
            f"{key}: settings_risk tab={entry['tab']!r} "
            f"but canonical owner is {sk.TAB_BY_KEY[key]!r}"
        )


# ------------------------------------------------------------- profile schema

def test_profile_schema_serializes_every_canonical_key():
    profile = _empty_profile()
    for section, keys in sk.PROFILE_SECTION_KEYS.items():
        assert section in profile, f"profile missing section {section!r}"
        missing = set(keys) - set(profile[section])
        assert not missing, f"profile section {section!r} missing keys: {sorted(missing)}"


def test_profile_toggle_keys_union_equals_all_canonical_keys():
    profile = _empty_profile()
    serialized = set()
    for section in sk.PROFILE_SECTION_KEYS:
        serialized |= (set(profile[section]) & sk.ALL_KEYS)
    assert serialized == sk.ALL_KEYS


# ----------------------------------------------------------------- helpers

def test_tab_for_returns_owner_or_none():
    assert sk.tab_for("disable_lso") == "wifi"
    assert sk.tab_for("nvidia_ull") == "fps"
    assert sk.tab_for("switch_dns") == "optimizer"
    assert sk.tab_for("not_a_real_key") is None


def test_is_known_key():
    assert sk.is_known_key("disable_bss_scan") is True
    assert sk.is_known_key("force_msi_mode") is True
    assert sk.is_known_key("game_priority") is False  # bandwidth, not a canonical toggle
    assert sk.is_known_key("") is False


# ----------------------------------------------------------- UI tabs (origin)

def test_ui_tabs_expose_exactly_the_canonical_keys(qt_app):
    """The tabs are where keys originate; every other layer mirrors them."""
    from ui.tab_wifi import TabWifi
    from ui.tab_fps import TabFps
    from ui.tab_optimizer import TabOptimizer

    assert set(TabWifi()._toggle_rows) == set(sk.WIFI_KEYS)
    assert set(TabFps()._toggle_rows) == set(sk.FPS_KEYS)
    assert set(TabOptimizer()._toggle_rows) == set(sk.OPTIMIZER_KEYS)

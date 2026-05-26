"""
Tests for core.cs2_paths — Steam library discovery and autoexec writer.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from core import cs2_paths


# ---------------------------------------------------------------------------
# Steam install discovery
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_winreg(monkeypatch):
    """Provide a fake winreg module with controllable values."""
    fake = mock.MagicMock()
    fake.HKEY_LOCAL_MACHINE = "HKLM"
    fake.HKEY_CURRENT_USER = "HKCU"
    fake._store = {}

    class _Key:
        def __init__(self, kv): self.kv = kv
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(root, subkey):
        key = (root, subkey)
        if key not in fake._store:
            raise OSError(2, "not found")
        return _Key(fake._store[key])

    def _query(handle, name):
        if name not in handle.kv:
            raise OSError(2, "missing value")
        return (handle.kv[name], 1)

    fake.OpenKey = _open
    fake.QueryValueEx = _query

    monkeypatch.setitem(__import__("sys").modules, "winreg", fake)
    return fake


def test_find_steam_install_reads_wow6432_first(fake_winreg):
    fake_winreg._store[("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam")] = {
        "InstallPath": r"C:\Program Files (x86)\Steam",
    }
    assert cs2_paths.find_steam_install() == os.path.normpath(
        r"C:\Program Files (x86)\Steam"
    )


def test_find_steam_install_falls_back_to_hkcu(fake_winreg):
    fake_winreg._store[("HKCU", r"Software\Valve\Steam")] = {
        "SteamPath": "D:/SteamLibrary",
    }
    assert cs2_paths.find_steam_install() == os.path.normpath("D:/SteamLibrary")


def test_find_steam_install_returns_none_when_absent(fake_winreg):
    # Empty store
    assert cs2_paths.find_steam_install() is None


# ---------------------------------------------------------------------------
# libraryfolders.vdf parsing
# ---------------------------------------------------------------------------

VDF_TEMPLATE = """
"libraryfolders"
{
    "0"
    {
        "path"        "C:\\\\Program Files (x86)\\\\Steam"
        "label"       ""
    }
    "1"
    {
        "path"        "D:\\\\SteamLibrary"
        "label"       "Games"
    }
}
"""


def test_find_steam_libraries_unescapes_backslashes(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        VDF_TEMPLATE, encoding="utf-8"
    )

    libs = cs2_paths.find_steam_libraries(str(steam))

    # steam_root always first
    assert libs[0] == os.path.normpath(str(steam))
    # parsed entries are decoded and normalised
    assert os.path.normpath(r"C:\Program Files (x86)\Steam") in libs
    assert os.path.normpath(r"D:\SteamLibrary") in libs


def test_find_steam_libraries_missing_vdf_returns_root_only(tmp_path):
    steam = tmp_path / "Steam"
    steam.mkdir()
    assert cs2_paths.find_steam_libraries(str(steam)) == [
        os.path.normpath(str(steam))
    ]


def test_find_steam_libraries_dedupes_case_insensitively(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    vdf_dupe = '"path"  "%s"' % str(steam).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        vdf_dupe, encoding="utf-8"
    )

    libs = cs2_paths.find_steam_libraries(str(steam))
    assert len(libs) == 1


# ---------------------------------------------------------------------------
# CS2 install resolution
# ---------------------------------------------------------------------------

def _make_cs2_layout(library: os.PathLike, *, layout: str) -> str:
    base = os.path.join(
        str(library), "steamapps", "common", "Counter-Strike Global Offensive"
    )
    if layout == "current":
        cfg_dir = os.path.join(base, "game", "csgo", "cfg")
    elif layout == "legacy":
        cfg_dir = os.path.join(base, "csgo", "cfg")
    else:
        raise ValueError(layout)
    os.makedirs(cfg_dir, exist_ok=True)
    return cfg_dir


def test_find_cs2_install_prefers_current_layout(tmp_path, monkeypatch):
    library = tmp_path / "Steam"
    library.mkdir()
    cfg_dir = _make_cs2_layout(library, layout="current")

    monkeypatch.setattr(cs2_paths, "find_steam_install", lambda: str(library))
    monkeypatch.setattr(cs2_paths, "find_steam_libraries", lambda _: [str(library)])

    result = cs2_paths.find_cs2_install()
    assert result is not None
    found_cfg, exe = result
    assert found_cfg == cfg_dir
    assert exe.endswith(os.path.join("win64", "cs2.exe"))


def test_find_cs2_install_falls_back_to_legacy_layout(tmp_path, monkeypatch):
    library = tmp_path / "Steam"
    library.mkdir()
    legacy_cfg = _make_cs2_layout(library, layout="legacy")

    monkeypatch.setattr(cs2_paths, "find_steam_install", lambda: str(library))
    monkeypatch.setattr(cs2_paths, "find_steam_libraries", lambda _: [str(library)])

    result = cs2_paths.find_cs2_install()
    assert result is not None
    assert result[0] == legacy_cfg


def test_find_cs2_install_walks_multiple_libraries(tmp_path, monkeypatch):
    lib_a = tmp_path / "Steam"
    lib_b = tmp_path / "Games"
    lib_a.mkdir()
    lib_b.mkdir()
    cfg_dir = _make_cs2_layout(lib_b, layout="current")

    monkeypatch.setattr(cs2_paths, "find_steam_install", lambda: str(lib_a))
    monkeypatch.setattr(
        cs2_paths,
        "find_steam_libraries",
        lambda _: [str(lib_a), str(lib_b)],
    )

    result = cs2_paths.find_cs2_install()
    assert result is not None
    assert result[0] == cfg_dir


def test_find_cs2_install_returns_none_when_steam_absent(monkeypatch):
    monkeypatch.setattr(cs2_paths, "find_steam_install", lambda: None)
    assert cs2_paths.find_cs2_install() is None


def test_find_cs2_install_returns_none_when_cs2_absent(tmp_path, monkeypatch):
    library = tmp_path / "Steam"
    library.mkdir()
    monkeypatch.setattr(cs2_paths, "find_steam_install", lambda: str(library))
    monkeypatch.setattr(cs2_paths, "find_steam_libraries", lambda _: [str(library)])
    assert cs2_paths.find_cs2_install() is None


# ---------------------------------------------------------------------------
# Recommended autoexec contents
# ---------------------------------------------------------------------------

def test_recommended_autoexec_contains_critical_lines():
    text = cs2_paths.recommended_autoexec_text()
    for line in (
        "rate 786432",
        "mm_dedicated_search_maxping",
        "cl_predict 1",
        "cl_interp_ratio 1",
        "net_client_steamdatagram_enable_override 1",
        "host_writeconfig",
    ):
        assert line in text


# ---------------------------------------------------------------------------
# autoexec writer
# ---------------------------------------------------------------------------

def test_write_autoexec_creates_file(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    ok, written_path = cs2_paths.write_autoexec(str(cfg_dir), overwrite=False)
    assert ok is True
    assert os.path.basename(written_path) == "autoexec.cfg"
    with open(written_path, "r", encoding="utf-8") as fh:
        assert "rate 786432" in fh.read()


def test_write_autoexec_refuses_to_overwrite(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    target = cfg_dir / "autoexec.cfg"
    target.write_text("// existing user config", encoding="utf-8")

    ok, reason = cs2_paths.write_autoexec(str(cfg_dir), overwrite=False)
    assert ok is False
    assert reason.startswith("exists:")
    assert target.read_text(encoding="utf-8") == "// existing user config"


def test_write_autoexec_backs_up_existing(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    target = cfg_dir / "autoexec.cfg"
    target.write_text("// user-customised", encoding="utf-8")

    ok, written_path = cs2_paths.write_autoexec(str(cfg_dir), overwrite=True)
    assert ok is True
    backups = [p for p in cfg_dir.iterdir() if p.name.startswith("autoexec.cfg.bak.")]
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "// user-customised"
    assert "rate 786432" in target.read_text(encoding="utf-8")


def test_write_autoexec_creates_missing_cfg_dir(tmp_path):
    cfg_dir = tmp_path / "deep" / "cfg"
    ok, written_path = cs2_paths.write_autoexec(str(cfg_dir), overwrite=False)
    assert ok is True
    assert os.path.isfile(written_path)


def test_write_autoexec_rejects_empty_dir():
    ok, reason = cs2_paths.write_autoexec("", overwrite=False)
    assert ok is False
    assert reason.startswith("invalid:")

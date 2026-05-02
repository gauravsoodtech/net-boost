"""
Unit tests for core.background_killer.

Patches win32serviceutil / win32service / psutil so the suite stays portable
and never touches the live SCM database or real processes.
"""

from unittest.mock import MagicMock

import pytest

import win32service

from core import background_killer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stub_psutil(monkeypatch, processes=None, suspend_calls=None, resume_calls=None):
    """
    Replace psutil.process_iter and psutil.Process with mocks.

    *processes* is a list of (pid, name) pairs to enumerate.
    The returned (suspend_calls, resume_calls) lists are populated when the
    suspend/resume APIs are invoked.
    """
    processes = processes or []
    suspend_calls = suspend_calls if suspend_calls is not None else []
    resume_calls = resume_calls if resume_calls is not None else []

    def fake_process_iter(_attrs):
        for pid, name in processes:
            p = MagicMock()
            p.info = {"name": name, "pid": pid}
            yield p

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def suspend(self):
            suspend_calls.append(self.pid)

        def resume(self):
            resume_calls.append(self.pid)

    monkeypatch.setattr(background_killer.psutil, "process_iter", fake_process_iter)
    monkeypatch.setattr(background_killer.psutil, "Process", FakeProc)
    return suspend_calls, resume_calls


def _stub_service_layer(
    monkeypatch,
    state_by_name=None,
    pause_succeeds=True,
    stop_succeeds=True,
):
    """
    Replace the win32serviceutil functions used by background_killer.

    *state_by_name* maps service name → SERVICE_* state int (used by
    _get_service_state).  Returns dicts of recorded calls.
    """
    state_by_name = state_by_name or {}
    calls = {"pause": [], "stop": [], "start": [], "continue": [], "query": []}

    def fake_query(name):
        calls["query"].append(name)
        if name not in state_by_name:
            raise RuntimeError("not found")
        return (0, state_by_name[name], 0, 0, 0, 0, 0)

    def fake_pause(name):
        calls["pause"].append(name)
        if not pause_succeeds:
            raise RuntimeError("pause not supported")
        state_by_name[name] = win32service.SERVICE_PAUSED

    def fake_stop(name):
        calls["stop"].append(name)
        if not stop_succeeds:
            raise RuntimeError("stop failed")
        state_by_name[name] = win32service.SERVICE_STOPPED

    def fake_start(name):
        calls["start"].append(name)
        state_by_name[name] = win32service.SERVICE_RUNNING

    def fake_continue(name):
        calls["continue"].append(name)
        state_by_name[name] = win32service.SERVICE_RUNNING

    monkeypatch.setattr(background_killer.win32serviceutil, "QueryServiceStatus", fake_query, raising=False)
    monkeypatch.setattr(background_killer.win32serviceutil, "PauseService", fake_pause, raising=False)
    monkeypatch.setattr(background_killer.win32serviceutil, "StopService", fake_stop, raising=False)
    monkeypatch.setattr(background_killer.win32serviceutil, "StartService", fake_start, raising=False)
    monkeypatch.setattr(background_killer.win32serviceutil, "ContinueService", fake_continue, raising=False)
    # Skip the real polling loop.
    monkeypatch.setattr(background_killer, "_wait_for_service_state", lambda *a, **kw: None)
    return calls


# ── _pause_or_stop_service ───────────────────────────────────────────────────

def test_pause_or_stop_service_pauses_when_supported(monkeypatch):
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "wuauserv": win32service.SERVICE_RUNNING,
    })

    entry = background_killer._pause_or_stop_service("wuauserv")

    assert entry == {
        "name": "wuauserv",
        "action": "pause",
        "previous_state": win32service.SERVICE_RUNNING,
    }
    assert calls["pause"] == ["wuauserv"]
    assert calls["stop"] == []


def test_pause_or_stop_service_falls_back_to_stop(monkeypatch):
    calls = _stub_service_layer(
        monkeypatch,
        state_by_name={"BITS": win32service.SERVICE_RUNNING},
        pause_succeeds=False,
    )

    entry = background_killer._pause_or_stop_service("BITS")

    assert entry["action"] == "stop"
    assert calls["pause"] == ["BITS"]
    assert calls["stop"] == ["BITS"]


def test_pause_or_stop_service_returns_none_action_when_missing(monkeypatch):
    _stub_service_layer(monkeypatch, state_by_name={})  # service does not exist

    entry = background_killer._pause_or_stop_service("FakeSvc")

    assert entry == {"name": "FakeSvc", "action": "none", "previous_state": -1}


def test_pause_or_stop_service_no_action_when_already_stopped(monkeypatch):
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "BITS": win32service.SERVICE_STOPPED,
    })

    entry = background_killer._pause_or_stop_service("BITS")

    assert entry["action"] == "none"
    assert entry["previous_state"] == win32service.SERVICE_STOPPED
    assert calls["pause"] == []
    assert calls["stop"] == []


# ── _resume_or_start_service ─────────────────────────────────────────────────

def test_resume_or_start_service_continues_paused(monkeypatch):
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "wuauserv": win32service.SERVICE_PAUSED,
    })

    background_killer._resume_or_start_service({
        "name": "wuauserv", "action": "pause", "previous_state": 0,
    })

    assert calls["continue"] == ["wuauserv"]
    assert calls["start"] == []


def test_resume_or_start_service_starts_stopped(monkeypatch):
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "BITS": win32service.SERVICE_STOPPED,
    })

    background_killer._resume_or_start_service({
        "name": "BITS", "action": "stop", "previous_state": 0,
    })

    assert calls["start"] == ["BITS"]
    assert calls["continue"] == []


def test_resume_or_start_service_noop_for_action_none(monkeypatch):
    calls = _stub_service_layer(monkeypatch)

    background_killer._resume_or_start_service({
        "name": "x", "action": "none", "previous_state": -1,
    })

    assert calls["start"] == []
    assert calls["continue"] == []


# ── _find_onesync_services ───────────────────────────────────────────────────

def test_find_onesync_services_filters_by_prefix(monkeypatch):
    fake_scm = object()
    services = [
        ("OneSyncSvc",          "OneDrive Sync",          0),
        ("OneSyncSvc_12abc",    "Per-User Sync",          0),
        ("BITS",                "Background Intelligent", 0),
        ("OneSyncSvc_88def",    "Per-User Sync 2",        0),
    ]

    monkeypatch.setattr(
        background_killer.win32service,
        "OpenSCManager",
        lambda *a, **kw: fake_scm,
    )
    monkeypatch.setattr(
        background_killer.win32service,
        "EnumServicesStatus",
        lambda *a, **kw: services,
    )
    monkeypatch.setattr(
        background_killer.win32service,
        "CloseServiceHandle",
        lambda h: None,
    )

    found = background_killer._find_onesync_services()
    assert found == ["OneSyncSvc", "OneSyncSvc_12abc", "OneSyncSvc_88def"]


def test_find_onesync_services_returns_empty_on_scm_error(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("SCM denied")

    monkeypatch.setattr(background_killer.win32service, "OpenSCManager", boom)

    assert background_killer._find_onesync_services() == []


# ── _find_pids_by_name ───────────────────────────────────────────────────────

def test_find_pids_by_name_case_insensitive(monkeypatch):
    _stub_psutil(monkeypatch, processes=[
        (101, "OneDrive.exe"),
        (102, "onedrive.exe"),  # lowercase variant
        (103, "Discord.exe"),
        (104, None),  # missing name — must not crash
    ])

    pids = background_killer._find_pids_by_name("onedrive.exe")
    assert sorted(pids) == [101, 102]


# ── apply() ──────────────────────────────────────────────────────────────────

def test_apply_pause_windows_update(monkeypatch):
    _stub_psutil(monkeypatch)
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "wuauserv": win32service.SERVICE_RUNNING,
    })
    monkeypatch.setattr(background_killer, "_find_onesync_services", lambda: [])
    monkeypatch.setattr(background_killer, "_deprioritize_process", lambda pid, n: None)

    backup = background_killer.apply({"pause_windows_update": True})

    assert calls["pause"] == ["wuauserv"]
    names = [e["name"] for e in backup["services_backup"]]
    assert "wuauserv" in names


def test_apply_pause_onedrive_handles_services_and_process(monkeypatch):
    suspend_calls, _ = _stub_psutil(monkeypatch, processes=[
        (4242, "OneDrive.exe"),
    ])
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "OneSyncSvc_abc": win32service.SERVICE_RUNNING,
    })
    monkeypatch.setattr(
        background_killer,
        "_find_onesync_services",
        lambda: ["OneSyncSvc_abc"],
    )
    monkeypatch.setattr(background_killer, "_deprioritize_process", lambda pid, n: None)

    backup = background_killer.apply({"pause_onedrive": True})

    assert "OneSyncSvc_abc" in calls["pause"]
    assert 4242 in suspend_calls
    assert 4242 in backup["suspended_pids"]


def test_apply_pause_telemetry_targets_diagtrack(monkeypatch):
    _stub_psutil(monkeypatch)
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "DiagTrack": win32service.SERVICE_RUNNING,
    })
    monkeypatch.setattr(background_killer, "_find_onesync_services", lambda: [])
    monkeypatch.setattr(background_killer, "_deprioritize_process", lambda pid, n: None)

    background_killer.apply({"pause_telemetry": True})

    assert "DiagTrack" in calls["pause"]


def test_apply_pause_bits_targets_BITS(monkeypatch):
    _stub_psutil(monkeypatch)
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "BITS": win32service.SERVICE_RUNNING,
    })
    monkeypatch.setattr(background_killer, "_find_onesync_services", lambda: [])
    monkeypatch.setattr(background_killer, "_deprioritize_process", lambda pid, n: None)

    background_killer.apply({"pause_bits": True})

    assert "BITS" in calls["pause"]


def test_apply_always_suspends_search_indexer(monkeypatch):
    suspend_calls, _ = _stub_psutil(monkeypatch, processes=[
        (777, "SearchIndexer.exe"),
    ])
    _stub_service_layer(monkeypatch)
    monkeypatch.setattr(background_killer, "_find_onesync_services", lambda: [])
    monkeypatch.setattr(background_killer, "_deprioritize_process", lambda pid, n: None)

    backup = background_killer.apply({})

    assert 777 in suspend_calls
    assert 777 in backup["suspended_pids"]


# ── restore() ────────────────────────────────────────────────────────────────

def test_restore_resumes_pids_and_services(monkeypatch):
    _, resume_calls = _stub_psutil(monkeypatch)
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "wuauserv": win32service.SERVICE_PAUSED,
        "BITS": win32service.SERVICE_STOPPED,
    })

    backup = {
        "services_backup": [
            {"name": "wuauserv", "action": "pause", "previous_state": 0},
            {"name": "BITS", "action": "stop", "previous_state": 0},
        ],
        "suspended_pids": [12, 34],
    }

    background_killer.restore(backup)

    assert sorted(resume_calls) == [12, 34]
    assert calls["continue"] == ["wuauserv"]
    assert calls["start"] == ["BITS"]


# ── suspend_process / resume_process error swallowing ────────────────────────

def test_suspend_process_swallows_no_such_process(monkeypatch):
    import psutil as real_psutil

    class BadProc:
        def __init__(self, pid):
            raise real_psutil.NoSuchProcess(pid)

    monkeypatch.setattr(background_killer.psutil, "Process", BadProc)

    background_killer.suspend_process(9999)  # must not raise


def test_resume_process_swallows_access_denied(monkeypatch):
    import psutil as real_psutil

    class DeniedProc:
        def __init__(self, pid):
            self.pid = pid

        def resume(self):
            raise real_psutil.AccessDenied(self.pid)

    monkeypatch.setattr(background_killer.psutil, "Process", DeniedProc)

    background_killer.resume_process(9999)  # must not raise


# ── resume_service compat shim ───────────────────────────────────────────────

def test_resume_service_calls_start_service(monkeypatch):
    calls = _stub_service_layer(monkeypatch, state_by_name={
        "wuauserv": win32service.SERVICE_STOPPED,
    })

    background_killer.resume_service("wuauserv")

    assert calls["start"] == ["wuauserv"]


# ── Regression guards for CLAUDE.md pitfalls ─────────────────────────────────

def test_processes_to_suspend_excludes_msmpeng_and_onedrive():
    """
    CLAUDE.md pitfall: MsMpEng.exe (Windows Defender) and OneDrive.exe must
    NOT be in PROCESSES_TO_SUSPEND.  MsMpEng would degrade the network
    inspection driver; OneDrive is handled conditionally inside the
    pause_onedrive block instead.
    """
    suspended_lower = {p.lower() for p in background_killer.PROCESSES_TO_SUSPEND}
    assert "msmpeng.exe" not in suspended_lower
    assert "onedrive.exe" not in suspended_lower

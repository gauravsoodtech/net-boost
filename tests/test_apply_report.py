"""Unit tests for core.apply_report — the shared apply-verification report."""

from core import apply_report as ar


def test_new_report_is_empty():
    assert ar.new_report() == {
        "target_found": True,
        "written": 0,
        "verified": 0,
        "failed": 0,
        "verified_values": [],
        "failed_values": [],
    }


def test_record_verified_and_failed_accumulate():
    r = ar.new_report()
    ar.record_verified(r, "A")
    ar.record_failed(r, "B", 1, 0, "readback mismatch")
    assert r["written"] == 2
    assert r["verified"] == 1
    assert r["failed"] == 1
    assert r["verified_values"] == ["A"]
    assert r["failed_values"] == [
        {"name": "B", "target": 1, "actual": 0, "reason": "readback mismatch"}
    ]


def test_mark_target_missing():
    r = ar.new_report()
    ar.mark_target_missing(r)
    assert r["target_found"] is False


# ── summarize() — all branches ───────────────────────────────────────────────

def test_summarize_nothing_attempted_is_clean():
    assert ar.summarize(ar.new_report(), "GPU") == (True, "")


def test_summarize_clean_success():
    r = ar.new_report()
    ar.record_verified(r, "A")
    assert ar.summarize(r, "GPU") == (True, "")


def test_summarize_target_missing_is_unusable():
    r = ar.new_report()
    ar.mark_target_missing(r)
    usable, msg = ar.summarize(r, "TCP")
    assert usable is False
    assert "TCP" in msg and "not found" in msg


def test_summarize_none_confirmed_is_unusable():
    r = ar.new_report()
    ar.record_failed(r, "A", 1, 0, "readback mismatch")
    usable, msg = ar.summarize(r, "GPU")
    assert usable is False
    assert "none confirmed" in msg


def test_summarize_partial_is_usable_with_warning():
    r = ar.new_report()
    ar.record_verified(r, "A")
    ar.record_failed(r, "B", 1, 0, "readback mismatch")
    usable, msg = ar.summarize(r, "GPU")
    assert usable is True
    assert "partially applied" in msg
    assert "1/2" in msg

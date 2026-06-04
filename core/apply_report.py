"""
core/apply_report.py — shared apply-verification report for optimizer modules.

Registry-writing optimizers should read each value back after writing it and
record whether it actually stuck.  Windows can accept a write call and silently
fail to persist it (permission virtualization, policy, a driver re-claiming the
key), so "no exception raised" does NOT mean "the tweak applied".  Verifying by
read-back converts that silent no-op into a structured, surfaceable result.

`core/wifi_optimizer.py` pioneered this inline; this module standardizes the
shape so nvidia_optimizer, network_optimizer, and the UI all speak the same
language.  A report is a plain dict (JSON-serializable, so it rides along in
state.json backups without special handling) with this shape::

    {
        "target_found": bool,    # False = device / registry root missing
        "written":   int,        # writes attempted
        "verified":  int,        # writes confirmed by read-back
        "failed":    int,        # writes that did not confirm
        "verified_values": [str, ...],
        "failed_values":   [{"name", "target", "actual", "reason"}, ...],
    }

All keys are underscore-free here, but callers store the whole report under a
single ``"_verify"`` key in their backup dict so restore() loops that skip
``_``-prefixed keys ignore it automatically.
"""

from __future__ import annotations


def new_report() -> dict:
    """Return a fresh, empty verification report."""
    return {
        "target_found": True,
        "written": 0,
        "verified": 0,
        "failed": 0,
        "verified_values": [],
        "failed_values": [],
    }


def record_verified(report: dict, name: str) -> None:
    """Record that a write to *name* was confirmed by read-back."""
    report["written"] += 1
    report["verified"] += 1
    report["verified_values"].append(name)


def record_failed(report: dict, name: str, target, actual, reason: str) -> None:
    """Record that a write to *name* did not stick (or could not be made)."""
    report["written"] += 1
    report["failed"] += 1
    report["failed_values"].append(
        {"name": name, "target": target, "actual": actual, "reason": reason}
    )


def mark_target_missing(report: dict) -> None:
    """Flag that the target device / registry root could not be located."""
    report["target_found"] = False


def summarize(report: dict, label: str) -> tuple[bool, str]:
    """
    Reduce a report to ``(usable, message)`` for UI surfacing.

    * ``usable`` is False only when the change clearly did not take effect
      (target missing, or writes attempted but none confirmed).
    * ``message`` is ``""`` on full, clean success; otherwise a short,
      human-readable warning prefixed with *label* (e.g. ``"GPU"``).
    """
    if not report.get("target_found", True):
        return False, (
            f"{label}: target device/key not found - changes may not have applied. "
            f"Run as admin and confirm the hardware is present."
        )

    written = int(report.get("written", 0))
    verified = int(report.get("verified", 0))
    failed = int(report.get("failed", 0))

    if written <= 0:
        return True, ""  # nothing attempted is not a failure
    if verified <= 0:
        return False, f"{label}: {written} change(s) attempted but none confirmed by readback."
    if failed:
        return True, f"{label}: partially applied - {verified}/{written} values confirmed."
    return True, ""

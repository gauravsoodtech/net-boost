"""
Tests for NetBoost startup dependency checks.
"""

import main


def test_missing_runtime_dependencies_reports_requirement_names():
    seen_modules = []

    def fake_find_spec(module_name):
        seen_modules.append(module_name)
        if module_name in {"psutil", "win32api"}:
            return None
        return object()

    missing = main.missing_runtime_dependencies(fake_find_spec)

    assert missing == ["psutil", "pywin32"]
    assert seen_modules == ["PyQt5", "pyqtgraph", "psutil", "win32api"]


def test_missing_dependency_message_points_to_requirements_install():
    message = main._missing_dependency_message(["PyQt5", "psutil"])

    assert "PyQt5, psutil" in message
    assert "python -m pip install -r requirements.txt" in message

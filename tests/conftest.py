"""
pytest configuration for NetBoost tests.
Adds the project root to sys.path and provides shared fixtures.
"""
import os
import sys

# Ensure project root is on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """Session-scoped QApplication for all tests that need Qt."""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app

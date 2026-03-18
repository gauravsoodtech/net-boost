"""
ui/tab_fps.py
FPS Boost tab — CPU, GPU, and Windows optimisation toggles.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QFrame,
    QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from .widgets.toggle_switch import ToggleSwitch


# ── Helper: a labelled toggle row (with optional note) ───────────────────────

class _ToggleRow(QWidget):
    def __init__(self, key: str, label: str, note: str = "", tooltip: str = "", parent=None):
        super().__init__(parent)
        self.key = key

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        self.switch = ToggleSwitch()
        layout.addWidget(self.switch)

        lbl = QLabel(label)
        lbl.setStyleSheet("background: transparent; border: none; color: #e0e0e0;")
        if tooltip:
            lbl.setToolTip(tooltip)
            # Visual cue: underline + cursor
            lbl.setStyleSheet(
                "background: transparent; border: none; color: #e0e0e0;"
                " text-decoration: underline dotted; cursor: help;"
            )
        layout.addWidget(lbl)

        if note:
            note_lbl = QLabel(note)
            note_lbl.setStyleSheet(
                "color: #9e9e9e; font-size: 11px; background: transparent; border: none;"
            )
            layout.addWidget(note_lbl)

        layout.addStretch()
        self.setStyleSheet("background: transparent;")


def _make_group_with_rows(title: str, rows_spec: list) -> tuple[QGroupBox, dict]:
    """
    Create a QGroupBox containing _ToggleRow widgets.

    rows_spec: list of (key, label, note, tooltip)
    Returns (group_widget, {key: _ToggleRow})
    """
    group = QGroupBox(title)
    layout = QVBoxLayout(group)
    layout.setSpacing(4)

    toggle_map: dict[str, _ToggleRow] = {}
    for key, label, note, tooltip in rows_spec:
        row = _ToggleRow(key, label, note, tooltip)
        toggle_map[key] = row
        layout.addWidget(row)

    return group, toggle_map


# ── FPS Tab ───────────────────────────────────────────────────────────────────

class TabFps(QWidget):
    """
    FPS Booster tab.

    Signals
    -------
    settings_applied(dict)  — emitted when user clicks "Apply FPS Boost"
    """

    settings_applied = pyqtSignal(dict)

    _CPU_ROWS = [
        ("ultimate_perf_plan",   "Ultimate Performance Power Plan",           "",               ""),
        ("pcore_affinity",       "P-Core Affinity (i7-13650HX: Cores 0-11)",  "",
         "Restricts game processes to high-performance P-Cores only, avoiding E-Core scheduling overhead."),
        ("timer_resolution",     "Force 0.5ms Timer Resolution",              "Default: 15.6ms",""),
    ]

    _GPU_ROWS = [
        ("nvidia_max_perf",      "NVIDIA Maximum Performance Mode",           "", ""),
        ("nvidia_ull",           "Ultra Low Latency Mode (NVIDIA)",           "", ""),
        ("disable_hags",         "Disable Hardware-Accelerated GPU Scheduling","",""),
    ]

    _WIN_ROWS = [
        ("disable_game_dvr",     "Disable Xbox Game DVR",                     "", ""),
        ("disable_fullscreen_opt","Disable Fullscreen Optimizations",          "", ""),
        ("disable_visual_fx",    "Disable Visual Effects & Animations",       "", ""),
        ("disable_sysmain",      "Disable SysMain (Superfetch)",               "", ""),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle_rows: dict[str, _ToggleRow] = {}
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Title ────────────────────────────────────────────────────────────
        title = QLabel("FPS Booster")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel("Reduce Frame Time Variance & Maximize GPU Performance")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

        # ── Sections ─────────────────────────────────────────────────────────
        for section_title, rows_spec in [
            ("CPU Optimization",     self._CPU_ROWS),
            ("GPU Optimization",     self._GPU_ROWS),
            ("Windows Optimization", self._WIN_ROWS),
        ]:
            group, toggle_map = _make_group_with_rows(section_title, rows_spec)
            self._toggle_rows.update(toggle_map)
            layout.addWidget(group)

        # ── Apply button ─────────────────────────────────────────────────────
        self._apply_btn = QPushButton("Apply FPS Boost")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setMinimumHeight(44)
        self._apply_btn.setMinimumWidth(200)
        self._apply_btn.clicked.connect(self._on_apply)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

    # ---------------------------------------------------------- Internals ------

    def _on_apply(self) -> None:
        self.settings_applied.emit(self.get_settings())

    # ---------------------------------------------------------- Public API ------

    def get_settings(self) -> dict:
        """Return {key: bool} for all toggle rows."""
        return {key: row.switch.isChecked() for key, row in self._toggle_rows.items()}

    def set_settings(self, settings: dict) -> None:
        """Apply a {key: bool} dict to the toggles."""
        for key, row in self._toggle_rows.items():
            if key in settings:
                row.switch.setChecked(bool(settings[key]))

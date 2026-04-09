"""
ui/tab_fps.py
FPS Boost tab — CPU, GPU, and Windows optimisation toggles.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QFrame,
    QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from .widgets.toggle_row import ToggleRow as _ToggleRow


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

    settings_applied  = pyqtSignal(dict)
    settings_restored = pyqtSignal()

    _CPU_ROWS = [
        ("power_plan",           "Ultimate Performance Power Plan",           "",               ""),
        ("pcores_affinity",      "P-Core Affinity (i7-13650HX: Cores 0-11)",  "",
         "Restricts game processes to high-performance P-Cores only, avoiding E-Core scheduling overhead."),
        ("timer_resolution",     "Force 0.5ms Timer Resolution",              "Default: 15.6ms",""),
    ]

    _GPU_ROWS = [
        ("nvidia_max_perf",      "NVIDIA Maximum Performance Mode",           "", ""),
        ("nvidia_ull",           "Ultra Low Latency Mode (NVIDIA)",           "", ""),
        ("disable_hags",         "Disable Hardware-Accelerated GPU Scheduling","",""),
    ]

    _WIN_ROWS = [
        ("game_dvr_off",         "Disable Xbox Game DVR",                     "", ""),
        ("fullscreen_opt_off",   "Disable Fullscreen Optimizations",          "", ""),
        ("visual_effects_off",   "Disable Visual Effects & Animations",       "", ""),
        ("sysmain_off",          "Disable SysMain (Superfetch)",               "", ""),
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

        # ── Action buttons ────────────────────────────────────────────────────
        self._apply_btn = QPushButton("Apply FPS Boost")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setMinimumHeight(44)
        self._apply_btn.setMinimumWidth(200)
        self._apply_btn.clicked.connect(self._on_apply)

        self._restore_btn = QPushButton("Restore Defaults")
        self._restore_btn.setObjectName("dangerButton")
        self._restore_btn.setMinimumHeight(44)
        self._restore_btn.clicked.connect(self._on_restore)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        # Default all toggles to ON
        self.set_settings({key: True for key in self._toggle_rows})

    # ---------------------------------------------------------- Internals ------

    def _on_apply(self) -> None:
        self.settings_applied.emit(self.get_settings())

    def _on_restore(self) -> None:
        self.settings_restored.emit()
        self.set_settings({key: True for key in self._toggle_rows})

    # ---------------------------------------------------------- Public API ------

    def get_settings(self) -> dict:
        """Return {key: bool} for all toggle rows."""
        return {key: row.switch.isChecked() for key, row in self._toggle_rows.items()}

    def set_settings(self, settings: dict) -> None:
        """Apply a {key: bool} dict to the toggles."""
        for key, row in self._toggle_rows.items():
            if key in settings:
                row.switch.setChecked(bool(settings[key]))

    def mark_applied(self, settings: dict) -> None:
        """Show ● Active badge on each toggle that was ON when Apply was clicked."""
        for key, row in self._toggle_rows.items():
            row.set_applied(bool(settings.get(key)))

    def clear_applied(self) -> None:
        """Remove all Active badges (called on Restore)."""
        for row in self._toggle_rows.values():
            row.set_applied(False)

    def show_apply_success(self) -> None:
        self._apply_btn.setObjectName("successButton")
        self._apply_btn.setText("\u2713 Applied!")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
        QTimer.singleShot(2500, self._reset_apply_btn)

    def show_apply_error(self) -> None:
        self._apply_btn.setObjectName("dangerButton")
        self._apply_btn.setText("\u2717 Error")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
        QTimer.singleShot(2500, self._reset_apply_btn)

    def _reset_apply_btn(self) -> None:
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setText("Apply FPS Boost")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)

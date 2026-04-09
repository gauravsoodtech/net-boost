"""
ui/tab_settings.py
Settings tab — startup options, monitoring intervals, game list editor, about.
"""

import platform
from typing import List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QCheckBox, QSpinBox,
    QListWidget, QListWidgetItem, QLineEdit, QFrame,
    QScrollArea, QSizePolicy, QAbstractItemView,
)
from PyQt5.QtCore import Qt, pyqtSignal


def _sys_info_text() -> str:
    """Build a multi-line system info string using stdlib + optional psutil."""
    lines = [
        f"OS:  {platform.system()} {platform.release()} ({platform.version()})",
        f"CPU: {platform.processor() or platform.machine()}",
    ]
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        lines.append(f"RAM: {ram_gb:.1f} GB")
    except ImportError:
        lines.append("RAM: (psutil not installed)")

    try:
        # GPU info via wmi (Windows only, best-effort)
        import subprocess
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True, text=True, timeout=3,
        )
        gpus = [ln.strip() for ln in result.stdout.splitlines() if ln.strip() and ln.strip() != "Name"]
        if gpus:
            lines.append(f"GPU: {', '.join(gpus)}")
        else:
            lines.append("GPU: (unknown)")
    except Exception:
        lines.append("GPU: (unavailable)")

    return "\n".join(lines)


class TabSettings(QWidget):
    """
    Settings tab.

    Signals
    -------
    settings_changed(dict)       — emitted when any setting is changed
    game_list_changed(list)      — emitted when the game exe list changes
    """

    settings_changed   = pyqtSignal(dict)
    game_list_changed  = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # ── Startup ──────────────────────────────────────────────────────────
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)
        startup_layout.setSpacing(6)

        self._chk_start_windows = QCheckBox("Start with Windows")
        self._chk_start_tray    = QCheckBox("Start minimized to tray")
        self._chk_auto_game     = QCheckBox("Auto-enable Game Mode on game detect")
        self._chk_adaptive      = QCheckBox("Adaptive Mode — auto-adjust settings based on network conditions")
        self._chk_adaptive.setToolTip(
            "When enabled, NetBoost monitors ping/loss in real-time and\n"
            "automatically adjusts DNS, LSO, and background services\n"
            "when network conditions degrade during gaming."
        )

        for chk in (self._chk_start_windows, self._chk_start_tray, self._chk_auto_game, self._chk_adaptive):
            chk.stateChanged.connect(self._on_settings_changed)
            startup_layout.addWidget(chk)

        layout.addWidget(startup_group)

        # ── Monitoring ───────────────────────────────────────────────────────
        mon_group = QGroupBox("Monitoring")
        mon_form  = QFormLayout(mon_group)
        mon_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        mon_form.setSpacing(10)

        self._spin_ping_interval = QSpinBox()
        self._spin_ping_interval.setRange(100, 5000)
        self._spin_ping_interval.setValue(500)
        self._spin_ping_interval.setSuffix(" ms")
        self._spin_ping_interval.setFixedWidth(120)
        self._spin_ping_interval.valueChanged.connect(self._on_settings_changed)

        self._spin_proc_interval = QSpinBox()
        self._spin_proc_interval.setRange(500, 10000)
        self._spin_proc_interval.setValue(1500)
        self._spin_proc_interval.setSuffix(" ms")
        self._spin_proc_interval.setFixedWidth(120)
        self._spin_proc_interval.valueChanged.connect(self._on_settings_changed)

        mon_form.addRow("Ping interval:", self._spin_ping_interval)
        mon_form.addRow("Process poll interval:", self._spin_proc_interval)

        layout.addWidget(mon_group)

        # ── Game List Editor ─────────────────────────────────────────────────
        games_group = QGroupBox("Game List Editor")
        games_layout = QVBoxLayout(games_group)
        games_layout.setSpacing(8)

        self._games_list = QListWidget()
        self._games_list.setMaximumHeight(180)
        self._games_list.setSelectionMode(QAbstractItemView.SingleSelection)
        games_layout.addWidget(self._games_list)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)

        self._new_game_input = QLineEdit()
        self._new_game_input.setPlaceholderText("e.g. game.exe")
        self._new_game_input.returnPressed.connect(self._on_add_game)

        self._add_game_btn = QPushButton("Add")
        self._add_game_btn.setFixedWidth(70)
        self._add_game_btn.setObjectName("successButton")
        self._add_game_btn.clicked.connect(self._on_add_game)

        self._remove_game_btn = QPushButton("Remove")
        self._remove_game_btn.setFixedWidth(80)
        self._remove_game_btn.setObjectName("dangerButton")
        self._remove_game_btn.clicked.connect(self._on_remove_game)

        add_row.addWidget(self._new_game_input, stretch=1)
        add_row.addWidget(self._add_game_btn)
        add_row.addWidget(self._remove_game_btn)
        games_layout.addLayout(add_row)

        layout.addWidget(games_group)

        # ── About ─────────────────────────────────────────────────────────────
        about_group = QGroupBox("About")
        about_layout = QVBoxLayout(about_group)
        about_layout.setSpacing(8)

        version_lbl = QLabel("NetBoost v1.0.0")
        version_lbl.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #4fc3f7;"
            " background: transparent; border: none;"
        )
        about_layout.addWidget(version_lbl)

        tagline = QLabel("Gaming Network Optimizer for Windows")
        tagline.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        about_layout.addWidget(tagline)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #2a2a4a; border: none; max-height: 1px;")
        about_layout.addWidget(separator)

        sys_info = _sys_info_text()
        sys_lbl = QLabel(sys_info)
        sys_lbl.setWordWrap(True)
        sys_lbl.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 11px;"
            " color: #9e9e9e; background: transparent; border: none;"
        )
        about_layout.addWidget(sys_lbl)

        layout.addWidget(about_group)
        layout.addStretch()

    # ---------------------------------------------------------- Internals ------

    def _on_settings_changed(self, *_) -> None:
        self.settings_changed.emit(self.get_settings())

    def _on_add_game(self) -> None:
        exe = self._new_game_input.text().strip()
        if not exe:
            return
        # Avoid duplicates (case-insensitive)
        existing = [
            self._games_list.item(i).text().lower()
            for i in range(self._games_list.count())
        ]
        if exe.lower() not in existing:
            self._games_list.addItem(exe)
            self.game_list_changed.emit(self.get_game_list())
        self._new_game_input.clear()

    def _on_remove_game(self) -> None:
        row = self._games_list.currentRow()
        if row >= 0:
            self._games_list.takeItem(row)
            self.game_list_changed.emit(self.get_game_list())

    # ---------------------------------------------------------- Public API ------

    def get_settings(self) -> dict:
        return {
            "start_with_windows":    self._chk_start_windows.isChecked(),
            "start_minimized":       self._chk_start_tray.isChecked(),
            "auto_game_mode":        self._chk_auto_game.isChecked(),
            "adaptive_mode":         self._chk_adaptive.isChecked(),
            "ping_interval_ms":      self._spin_ping_interval.value(),
            "proc_poll_interval_ms": self._spin_proc_interval.value(),
        }

    def set_settings(self, settings: dict) -> None:
        """Apply a settings dict to the UI (does not emit settings_changed)."""
        def _set_chk(chk, key):
            if key in settings:
                chk.blockSignals(True)
                chk.setChecked(bool(settings[key]))
                chk.blockSignals(False)

        def _set_spin(spin, key):
            if key in settings:
                spin.blockSignals(True)
                spin.setValue(int(settings[key]))
                spin.blockSignals(False)

        _set_chk(self._chk_start_windows, "start_with_windows")
        _set_chk(self._chk_start_tray,    "start_minimized")
        _set_chk(self._chk_auto_game,     "auto_game_mode")
        _set_chk(self._chk_adaptive,      "adaptive_mode")
        _set_spin(self._spin_ping_interval, "ping_interval_ms")
        _set_spin(self._spin_proc_interval, "proc_poll_interval_ms")

    def set_game_list(self, games: List[str]) -> None:
        """Populate the game exe list widget."""
        self._games_list.blockSignals(True)
        self._games_list.clear()
        for exe in games:
            self._games_list.addItem(exe)
        self._games_list.blockSignals(False)

    def get_game_list(self) -> List[str]:
        """Return the current list of game exe names."""
        return [
            self._games_list.item(i).text()
            for i in range(self._games_list.count())
        ]

"""
ui/tab_bandwidth.py
Bandwidth Manager tab — process table with priority and suspend/resume controls.
"""

from typing import List, Dict, Any

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QHeaderView, QFrame, QAbstractItemView,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QBrush, QFont


# Priority display names (ordered lowest → highest)
_PRIORITIES = [
    ("Idle",          0x40),
    ("Below Normal",  0x4000),
    ("Normal",        0x20),
    ("Above Normal",  0x8000),
    ("High",          0x80),
    ("Realtime",      0x100),
]
_PRIORITY_NAMES = [p[0] for p in _PRIORITIES]
_PRIORITY_VALUES = {p[0]: p[1] for p in _PRIORITIES}
_VALUE_TO_NAME = {v: k for k, v in _PRIORITY_VALUES.items()}


def _priority_name(value: int) -> str:
    return _VALUE_TO_NAME.get(value, "Normal")


# ── Column indices ────────────────────────────────────────────────────────────
_COL_PROCESS  = 0
_COL_PID      = 1
_COL_CPU      = 2
_COL_MEM      = 3
_COL_PRIORITY = 4
_COL_ACTIONS  = 5


class TabBandwidth(QWidget):
    """
    Bandwidth Manager tab.

    Signals
    -------
    refresh_requested                   — user clicks Refresh
    priority_change_requested(int, int) — (pid, win32_priority_class)
    suspend_requested(int)              — (pid)
    resume_requested(int)               — (pid)
    """

    refresh_requested          = pyqtSignal()
    priority_change_requested  = pyqtSignal(int, int)
    suspend_requested          = pyqtSignal(int)
    resume_requested           = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._suspended_pids: set[int] = set()
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Header row
        header_row = QHBoxLayout()

        title = QLabel("Bandwidth Manager")
        title.setObjectName("titleLabel")
        header_row.addWidget(title)
        header_row.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(100)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        header_row.addWidget(self._refresh_btn)

        layout.addLayout(header_row)

        # Legend
        legend_row = QHBoxLayout()
        legend_row.setSpacing(16)
        for color, text in [("#1a3a1a", "Game process"), ("#2a1a1a", "Suspended")]:
            dot = QFrame()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background-color: {color}; border-radius: 2px; border: 1px solid #2a2a4a;")
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #9e9e9e; font-size: 11px; background: transparent; border: none;")
            legend_row.addWidget(dot)
            legend_row.addWidget(lbl)
        legend_row.addStretch()
        layout.addLayout(legend_row)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Process", "PID", "CPU %", "Memory (MB)", "Priority", "Actions"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setFocusPolicy(Qt.NoFocus)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_PROCESS,  QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_PID,      QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_CPU,      QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_MEM,      QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_PRIORITY, QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_ACTIONS,  QHeaderView.Fixed)
        hdr.resizeSection(_COL_PRIORITY, 150)
        hdr.resizeSection(_COL_ACTIONS,  100)

        self._table.verticalHeader().setDefaultSectionSize(34)

        layout.addWidget(self._table, stretch=1)

        # Footer
        self._footer_label = QLabel("No processes loaded.")
        self._footer_label.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(self._footer_label)

    # ---------------------------------------------------------- Internals ------

    def _make_item(self, text: str, align=Qt.AlignVCenter | Qt.AlignLeft) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        return item

    def _color_row(self, row: int, pid: int, is_game: bool) -> None:
        if pid in self._suspended_pids:
            bg = QColor("#2a1a1a")
        elif is_game:
            bg = QColor("#1a3a1a")
        else:
            bg = QColor()  # default (alternating handled by stylesheet)

        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item and bg.isValid():
                item.setBackground(QBrush(bg))

    # ---------------------------------------------------------- Public API ------

    def refresh_processes(self, processes: List[Dict[str, Any]]) -> None:
        """
        Populate the table.

        Each dict should contain:
          pid (int), name (str), cpu_pct (float), mem_mb (float),
          priority (int, Win32 priority class value),
          is_game (bool, optional — default False)
        """
        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(0)

        for proc in processes:
            pid      = int(proc.get("pid", 0))
            name     = str(proc.get("name", "Unknown"))
            cpu_pct  = float(proc.get("cpu_pct", 0.0))
            mem_mb   = float(proc.get("mem_mb", 0.0))
            priority = int(proc.get("priority", 0x20))
            is_game  = bool(proc.get("is_game", False))

            row = self._table.rowCount()
            self._table.insertRow(row)

            # Name (bold for game processes)
            name_item = self._make_item(name)
            if is_game:
                f = name_item.font()
                f.setBold(True)
                name_item.setFont(f)
                name_item.setForeground(QBrush(QColor("#4caf50")))
            self._table.setItem(row, _COL_PROCESS, name_item)

            self._table.setItem(row, _COL_PID,
                self._make_item(str(pid), Qt.AlignCenter | Qt.AlignVCenter))
            self._table.setItem(row, _COL_CPU,
                self._make_item(f"{cpu_pct:.1f}", Qt.AlignCenter | Qt.AlignVCenter))
            self._table.setItem(row, _COL_MEM,
                self._make_item(f"{mem_mb:.1f}", Qt.AlignCenter | Qt.AlignVCenter))

            # Priority combo
            combo = QComboBox()
            combo.addItems(_PRIORITY_NAMES)
            prio_name = _priority_name(priority)
            idx = _PRIORITY_NAMES.index(prio_name) if prio_name in _PRIORITY_NAMES else 2
            combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(
                lambda text, p=pid: self.priority_change_requested.emit(p, _PRIORITY_VALUES[text])
            )
            self._table.setCellWidget(row, _COL_PRIORITY, combo)

            # Suspend / Resume button
            is_suspended = pid in self._suspended_pids
            action_btn = QPushButton("Resume" if is_suspended else "Suspend")
            action_btn.setProperty("class", "success" if is_suspended else "danger")
            action_btn.setFixedHeight(26)
            action_btn.clicked.connect(
                lambda _, p=pid: (
                    self.resume_requested.emit(p)
                    if p in self._suspended_pids
                    else self.suspend_requested.emit(p)
                )
            )
            self._table.setCellWidget(row, _COL_ACTIONS, action_btn)

            # Row colouring (must come after all items are set)
            self._color_row(row, pid, is_game)

        self._table.setUpdatesEnabled(True)
        count = len(processes)
        self._footer_label.setText(
            f"{count} process{'es' if count != 1 else ''} listed."
        )

    def set_suspended(self, pid: int, suspended: bool) -> None:
        """Update suspended state for a PID (called by MainWindow after suspend/resume)."""
        if suspended:
            self._suspended_pids.add(pid)
        else:
            self._suspended_pids.discard(pid)

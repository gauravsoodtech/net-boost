"""
ui/tab_route.py
Route Analyzer tab — discovers the game server IP from live connections and
traces the hop-by-hop route using Windows tracert.
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer, QThreadPool, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QBrush

from ui.widgets.status_led import AnimatedLED

logger = logging.getLogger(__name__)


# ── Column indices ─────────────────────────────────────────────────────────────
_COL_HOP    = 0
_COL_IP     = 1
_COL_AVG    = 2
_COL_MIN    = 3
_COL_MAX    = 4
_COL_STATUS = 5

# ── Row colours (programmatic — QSS cannot target QTableWidgetItem) ────────────
_COLOR_BG_BOTTLENECK  = QColor("#2a2200")
_COLOR_FG_BOTTLENECK  = QColor("#ff9800")
_COLOR_BG_TIMEOUT     = QColor("#2a0a0a")
_COLOR_FG_TIMEOUT     = QColor("#f44336")
_COLOR_FG_OK          = QColor("#4caf50")

_MAX_DISCOVER_RETRIES = 2


class TabRoute(QWidget):
    """
    Route Analyzer tab.

    MainWindow calls:
        on_game_detected(exe, pid)  — after a game launch + PID lookup
        on_game_exited()            — after the game process exits

    Signals emitted back to MainWindow:
        server_found(str)  — game server IP discovered via live connections
    """

    server_found = pyqtSignal(str)   # emitted when game server IP is discovered

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detected_server_ip: Optional[str] = None
        self._game_pid: int = 0
        self._discover_retries: int = 0
        self._current_worker = None        # _TraceRouteWorker or None
        self._discover_signals = None
        self._trace_signals = None
        self._build_ui()

    # ──────────────────────────────────────────────────────── UI construction ──

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Route Analyzer")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # ── Game status bar ────────────────────────────────────────────────────
        status_frame = QFrame()
        status_frame.setObjectName("routeStatusFrame")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 6, 12, 6)
        status_layout.setSpacing(8)

        self._game_led = AnimatedLED("grey")
        status_layout.addWidget(self._game_led)

        self._game_label = QLabel("No game detected")
        self._game_label.setObjectName("dimLabel")
        status_layout.addWidget(self._game_label)

        status_layout.addStretch()

        self._server_label = QLabel("")
        self._server_label.setObjectName("dimLabel")
        self._server_label.hide()
        status_layout.addWidget(self._server_label)

        layout.addWidget(status_frame)

        # ── Buttons row ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._trace_btn = QPushButton("Trace Route")
        self._trace_btn.setObjectName("primaryButton")
        self._trace_btn.setFixedWidth(120)
        self._trace_btn.clicked.connect(self._on_trace_clicked)
        btn_row.addWidget(self._trace_btn)

        btn_row.addStretch()

        ip_label = QLabel("Target IP:")
        ip_label.setObjectName("dimLabel")
        btn_row.addWidget(ip_label)

        self._manual_ip_input = QLineEdit()
        self._manual_ip_input.setPlaceholderText("e.g. 103.28.54.12")
        self._manual_ip_input.setFixedWidth(160)
        self._manual_ip_input.returnPressed.connect(self._on_trace_clicked)
        btn_row.addWidget(self._manual_ip_input)

        layout.addLayout(btn_row)

        # ── Hop table ──────────────────────────────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Hop", "IP Address", "Avg ms", "Min ms", "Max ms", "Status"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_IP, QHeaderView.Stretch
        )
        for col in (_COL_HOP, _COL_AVG, _COL_MIN, _COL_MAX, _COL_STATUS):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents
            )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        layout.addWidget(self._table)

        # ── Summary bar ────────────────────────────────────────────────────────
        summary_frame = QFrame()
        summary_frame.setObjectName("routeSummaryFrame")
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(14, 8, 14, 8)

        self._summary_label = QLabel("No trace run yet.")
        self._summary_label.setObjectName("dimLabel")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()

        layout.addWidget(summary_frame)

    # ──────────────────────────────────────────────────────── Public API ───────

    def on_game_detected(self, exe: str, pid: int) -> None:
        """
        Called by MainWindow after a game launches and PID is found.
        Updates the status bar and schedules server discovery after a 3s delay
        (gives the game time to establish its server connection).
        """
        self._game_pid = pid
        self._discover_retries = 0
        self._detected_server_ip = None

        display = exe.replace(".exe", "").upper()
        self._game_label.setText(f"Game: {display}")
        self._game_label.setObjectName("")
        self._game_label.style().unpolish(self._game_label)
        self._game_label.style().polish(self._game_label)
        self._game_led.setState("yellow")
        self._server_label.setText("Searching for server…")
        self._server_label.show()

        QTimer.singleShot(3000, self._try_discover_server)

    def on_game_exited(self) -> None:
        """Called by MainWindow when the game process exits."""
        self._game_pid = 0
        self._detected_server_ip = None
        self._game_label.setText("No game detected")
        self._game_label.setObjectName("dimLabel")
        self._game_label.style().unpolish(self._game_label)
        self._game_label.style().polish(self._game_label)
        self._game_led.setState("grey")
        self._server_label.hide()

    # ──────────────────────────────────────────────────── Server discovery ──

    def _try_discover_server(self) -> None:
        """Spawn _DiscoverWorker to find the game server IP asynchronously."""
        if self._game_pid == 0:
            return

        from core.route_analyzer import _DiscoverWorkerSignals, _DiscoverWorker

        self._discover_signals = _DiscoverWorkerSignals()
        self._discover_signals.found.connect(self._on_server_found)
        self._discover_signals.not_found.connect(self._on_server_not_found)

        worker = _DiscoverWorker(self._discover_signals, self._game_pid)
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(str)
    def _on_server_found(self, ip: str) -> None:
        self._detected_server_ip = ip
        self._server_label.setText(f"Server: {ip}")
        self._game_led.setState("green")
        self._manual_ip_input.setText(ip)
        # Notify MainWindow so it can re-target the ping monitor
        self.server_found.emit(ip)
        # Auto-start trace with the discovered IP
        self._on_trace_clicked()

    @pyqtSlot()
    def _on_server_not_found(self) -> None:
        self._discover_retries += 1
        if self._discover_retries < _MAX_DISCOVER_RETRIES:
            self._server_label.setText("Server not found yet — retrying…")
            QTimer.singleShot(5000, self._try_discover_server)
        else:
            self._server_label.setText("Server not found — enter IP manually")
            self._game_led.setState("yellow")

    # ──────────────────────────────────────────────────────── Trace Route ──

    @pyqtSlot()
    def _on_trace_clicked(self) -> None:
        ip = self._manual_ip_input.text().strip()
        if not ip:
            ip = self._detected_server_ip or ""
        if not ip:
            self._summary_label.setText("Enter a target IP address.")
            return

        # Cancel any in-progress trace
        if self._current_worker is not None:
            self._current_worker.cancel()
            self._current_worker = None

        self._table.setRowCount(0)
        self._trace_btn.setEnabled(False)
        self._trace_btn.setText("Tracing…")
        self._summary_label.setText(f"Tracing route to {ip}…")

        from core.route_analyzer import _TraceWorkerSignals, _TraceRouteWorker

        self._trace_signals = _TraceWorkerSignals()
        self._trace_signals.hop_found.connect(self._on_hop_found)
        self._trace_signals.finished.connect(self._on_trace_finished)
        self._trace_signals.error.connect(self._on_trace_error)

        worker = _TraceRouteWorker(self._trace_signals, ip)
        self._current_worker = worker
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(dict)
    def _on_hop_found(self, hop: dict) -> None:
        """Append one hop row live as tracert produces output."""
        row = self._table.rowCount()
        self._table.insertRow(row)

        hop_item = QTableWidgetItem(str(hop["hop"]))
        hop_item.setTextAlignment(Qt.AlignCenter)

        ip_item = QTableWidgetItem(hop["ip"] or "—")

        def _ms_item(val) -> QTableWidgetItem:
            if val is None:
                return QTableWidgetItem("*")
            text = f"<1" if val == 0.5 else f"{val:.0f}"
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            return item

        status_text = "Timeout" if hop["is_timeout"] else "OK"
        status_item = QTableWidgetItem(status_text)
        status_item.setTextAlignment(Qt.AlignCenter)

        self._table.setItem(row, _COL_HOP,    hop_item)
        self._table.setItem(row, _COL_IP,     ip_item)
        self._table.setItem(row, _COL_AVG,    _ms_item(hop["latency_ms"]))
        self._table.setItem(row, _COL_MIN,    _ms_item(hop["min_ms"]))
        self._table.setItem(row, _COL_MAX,    _ms_item(hop["max_ms"]))
        self._table.setItem(row, _COL_STATUS, status_item)

        if hop["is_timeout"]:
            self._color_row(row, hop)

    @pyqtSlot(list)
    def _on_trace_finished(self, hops: list) -> None:
        """Re-color all rows with final bottleneck info and update summary."""
        self._current_worker = None
        self._trace_btn.setEnabled(True)
        self._trace_btn.setText("Trace Route")

        # Re-color every row using the fully annotated hop list
        for idx, hop in enumerate(hops):
            if idx < self._table.rowCount():
                self._color_row(idx, hop)

        # Build summary
        n = len(hops)
        bottlenecks = [h for h in hops if h["is_bottleneck"]]
        if not bottlenecks:
            timeouts = sum(1 for h in hops if h["is_timeout"])
            if n == 0:
                summary = "No hops received — ICMP may be fully blocked."
            elif timeouts == n:
                summary = f"{n} hops — All timed out (ICMP blocked on this route)."
            else:
                summary = f"{n} hops — No bottlenecks detected."
        else:
            parts = []
            prev_ms = None
            for h in hops:
                if h["is_timeout"] or h["latency_ms"] is None:
                    continue
                if h["is_bottleneck"] and prev_ms is not None:
                    jump = h["latency_ms"] - prev_ms
                    parts.append(f"hop {h['hop']} (+{jump:.0f} ms)")
                prev_ms = h["latency_ms"]
            summary = f"{n} hops — Bottleneck at: {', '.join(parts)}"

        self._summary_label.setText(summary)

    @pyqtSlot(str)
    def _on_trace_error(self, message: str) -> None:
        self._current_worker = None
        self._trace_btn.setEnabled(True)
        self._trace_btn.setText("Trace Route")
        self._summary_label.setText(f"Error: {message}")

    # ──────────────────────────────────────────────────────── Row coloring ──

    def _color_row(self, row: int, hop: dict) -> None:
        if hop["is_timeout"]:
            bg = _COLOR_BG_TIMEOUT
            fg = _COLOR_FG_TIMEOUT
        elif hop["is_bottleneck"]:
            bg = _COLOR_BG_BOTTLENECK
            fg = _COLOR_FG_BOTTLENECK
            # Update status cell text
            status_item = self._table.item(row, _COL_STATUS)
            if status_item:
                status_item.setText("Bottleneck")
        else:
            bg = None
            fg = _COLOR_FG_OK

        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item is None:
                continue
            if bg is not None:
                item.setBackground(QBrush(bg))
            if fg is not None:
                item.setForeground(QBrush(fg))

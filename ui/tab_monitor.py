"""
ui/tab_monitor.py
Network Monitor tab — rolling ping graph + per-host stats.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from .widgets.ping_graph import PingGraph


class TabMonitor(QWidget):
    """
    Network Monitor tab.

    Signals
    -------
    host_changed(str)   — emitted when user clicks Apply with a new host
    """

    host_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_host: str = "1.1.1.1"

        # rolling stats
        self._min_ping: float = float("inf")
        self._max_ping: float = 0.0
        self._sum_ping: float = 0.0
        self._count:    int   = 0
        self._last_jitter: float = 0.0
        self._timeouts: int = 0

        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Network Monitor")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # Host row
        host_row = QHBoxLayout()
        host_row.setSpacing(8)

        host_label = QLabel("Ping Host:")
        host_label.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")

        self._host_input = QLineEdit(self._current_host)
        self._host_input.setPlaceholderText("e.g. 1.1.1.1 or google.com")
        self._host_input.setFixedWidth(200)
        self._host_input.returnPressed.connect(self._on_apply)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(80)
        apply_btn.clicked.connect(self._on_apply)

        host_row.addWidget(host_label)
        host_row.addWidget(self._host_input)
        host_row.addWidget(apply_btn)
        host_row.addStretch()

        # Current host display
        self._current_host_label = QLabel(f"Monitoring: {self._current_host}")
        self._current_host_label.setStyleSheet(
            "color: #4fc3f7; font-size: 11px; background: transparent; border: none;"
        )
        host_row.addWidget(self._current_host_label)

        layout.addLayout(host_row)

        # Graph
        self._graph = PingGraph(self)
        self._graph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._graph, stretch=1)

        # Stats row
        stats_frame = QFrame()
        stats_frame.setObjectName("statsFrame")
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(12, 8, 12, 8)
        stats_layout.setSpacing(24)

        self._lbl_min    = self._mk_stat("Min:", "--")
        self._lbl_avg    = self._mk_stat("Avg:", "--")
        self._lbl_max    = self._mk_stat("Max:", "--")
        self._lbl_jitter = self._mk_stat("Jitter:", "--")
        self._lbl_loss   = self._mk_stat("Loss:", "--")

        for pair in [self._lbl_min, self._lbl_avg, self._lbl_max,
                     self._lbl_jitter, self._lbl_loss]:
            lbl_key, lbl_val = pair
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(lbl_key)
            row.addWidget(lbl_val)
            stats_layout.addLayout(row)

        stats_layout.addStretch()
        layout.addWidget(stats_frame)

    @staticmethod
    def _mk_stat(key: str, default: str):
        k = QLabel(key)
        k.setStyleSheet("color: #9e9e9e; font-size: 12px; background: transparent; border: none;")
        v = QLabel(default)
        v.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: 600; background: transparent; border: none;")
        return k, v

    # ---------------------------------------------------------- Internals ------

    def _on_apply(self) -> None:
        host = self._host_input.text().strip()
        if host and host != self._current_host:
            self._current_host = host
            self._current_host_label.setText(f"Monitoring: {host}")
            self._reset_stats()
            self._graph.clear()
            self.host_changed.emit(host)

    def _reset_stats(self) -> None:
        self._min_ping = float("inf")
        self._max_ping = 0.0
        self._sum_ping = 0.0
        self._count = 0
        self._last_jitter = 0.0
        self._timeouts = 0
        self._refresh_stat_labels(0.0, 0.0)

    def _refresh_stat_labels(self, current_latency: float, jitter: float) -> None:
        total = self._count + self._timeouts
        loss_pct = (self._timeouts / total * 100.0) if total > 0 else 0.0

        min_txt = f"{self._min_ping:.1f} ms" if self._count > 0 else "--"
        avg_txt = f"{self._sum_ping / self._count:.1f} ms" if self._count > 0 else "--"
        max_txt = f"{self._max_ping:.1f} ms" if self._count > 0 else "--"
        jit_txt = f"{jitter:.1f} ms"
        los_txt = f"{loss_pct:.1f}%"

        self._lbl_min[1].setText(min_txt)
        self._lbl_avg[1].setText(avg_txt)
        self._lbl_max[1].setText(max_txt)
        self._lbl_jitter[1].setText(jit_txt)
        self._lbl_loss[1].setText(los_txt)

        # Colour loss
        if loss_pct == 0:
            color = "#4caf50"
        elif loss_pct < 5:
            color = "#ff9800"
        else:
            color = "#f44336"
        self._lbl_loss[1].setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 600;"
            " background: transparent; border: none;"
        )

    # ---------------------------------------------------------- Public API ------

    def add_reading(self, host: str, latency_ms: float, timed_out: bool) -> None:
        """
        Feed a new measurement into the graph and update the stats bar.

        Parameters
        ----------
        host        : hostname / IP that was probed (ignored if it doesn't match current)
        latency_ms  : round-trip time in milliseconds (ignored when timed_out is True)
        timed_out   : True if no reply was received
        """
        if timed_out:
            self._timeouts += 1
            jitter = self._last_jitter
            loss_pct = self._timeouts / (self._count + self._timeouts) * 100.0
            self._graph.add_reading(0.0, jitter, loss_pct)
            self._refresh_stat_labels(0.0, jitter)
            return

        prev_avg = (self._sum_ping / self._count) if self._count > 0 else latency_ms
        self._count    += 1
        self._sum_ping += latency_ms
        self._min_ping  = min(self._min_ping, latency_ms)
        self._max_ping  = max(self._max_ping, latency_ms)

        jitter = abs(latency_ms - prev_avg)
        self._last_jitter = jitter

        total = self._count + self._timeouts
        loss_pct = (self._timeouts / total * 100.0) if total > 0 else 0.0

        self._graph.add_reading(latency_ms, jitter, loss_pct)
        self._refresh_stat_labels(latency_ms, jitter)

    def set_host(self, host: str) -> None:
        """Programmatically change the host input (does not emit host_changed)."""
        self._host_input.setText(host)
        self._current_host = host
        self._current_host_label.setText(f"Monitoring: {host}")
        self._reset_stats()
        self._graph.clear()

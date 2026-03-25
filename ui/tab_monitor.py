"""
ui/tab_monitor.py
Network Monitor tab — rolling ping graph + per-host stats + health diagnostics.
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy, QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal

from .widgets.ping_graph import PingGraph


_LEVEL_COLORS = {
    "HIGH":   "#f44336",
    "MEDIUM": "#ff9800",
    "LOW":    "#4caf50",
}


class DiagnosticPanel(QFrame):
    """
    Collapsible panel showing currently-applied settings with risk badges
    and a live alert log.  Appended below the stats bar in the Monitor tab.
    """

    disable_setting_requested = pyqtSignal(str)  # key name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diagnosticPanel")
        self.setStyleSheet(
            "QFrame#diagnosticPanel { background-color: #1a1a2e;"
            " border: 1px solid #2a2a4a; border-radius: 6px; }"
        )
        self._collapsed = False
        self._applied: dict[str, dict] = {}  # flat {key: risk_entry | {}}

        self._build_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Collapsible header
        self._header_btn = QPushButton("  \u2665  Health Diagnostics  \u25bc")
        self._header_btn.setCheckable(False)
        self._header_btn.setStyleSheet(
            "QPushButton { background-color: #16213e; color: #4fc3f7;"
            " font-size: 12px; font-weight: 700; border: none;"
            " border-radius: 6px; padding: 6px 12px; text-align: left; }"
            "QPushButton:hover { background-color: #1a2a4a; }"
        )
        self._header_btn.clicked.connect(self._toggle_collapse)
        outer.addWidget(self._header_btn)

        # Body (collapsible)
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(12, 8, 12, 10)
        body_layout.setSpacing(8)

        # Applied settings section
        settings_lbl = QLabel("Applied Settings:")
        settings_lbl.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        body_layout.addWidget(settings_lbl)

        self._settings_container = QWidget()
        self._settings_layout = QVBoxLayout(self._settings_container)
        self._settings_layout.setContentsMargins(0, 0, 0, 0)
        self._settings_layout.setSpacing(3)
        self._no_settings_lbl = QLabel("No settings applied yet.")
        self._no_settings_lbl.setStyleSheet(
            "color: #555; font-size: 11px; background: transparent; border: none;"
        )
        self._settings_layout.addWidget(self._no_settings_lbl)
        body_layout.addWidget(self._settings_container)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a4a; background: #2a2a4a;")
        sep.setFixedHeight(1)
        body_layout.addWidget(sep)

        # Alerts section
        alerts_lbl = QLabel("Active Alerts:")
        alerts_lbl.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        body_layout.addWidget(alerts_lbl)

        # Scrollable alert list
        self._alerts_scroll = QScrollArea()
        self._alerts_scroll.setWidgetResizable(True)
        self._alerts_scroll.setFrameShape(QFrame.NoFrame)
        self._alerts_scroll.setFixedHeight(100)
        self._alerts_scroll.setStyleSheet("background: transparent;")

        self._alerts_container = QWidget()
        self._alerts_layout = QVBoxLayout(self._alerts_container)
        self._alerts_layout.setContentsMargins(0, 0, 0, 0)
        self._alerts_layout.setSpacing(4)
        self._no_alerts_lbl = QLabel("No alerts.")
        self._no_alerts_lbl.setStyleSheet(
            "color: #555; font-size: 11px; background: transparent; border: none;"
        )
        self._alerts_layout.addWidget(self._no_alerts_lbl)
        self._alerts_layout.addStretch()
        self._alerts_scroll.setWidget(self._alerts_container)
        body_layout.addWidget(self._alerts_scroll)

        outer.addWidget(self._body)

    # ------------------------------------------------------------------ public API

    def update_applied_settings(self, applied: dict[str, dict]) -> None:
        """
        Rebuild the applied-settings rows.

        Parameters
        ----------
        applied : mapping of tab_name → settings_dict
                  e.g. {"wifi": {"minimize_roaming": True, ...}, "fps": {...}}
        """
        from core.settings_risk import get_risk

        # Clear old rows (preserve _no_settings_lbl — it is reused)
        while self._settings_layout.count():
            item = self._settings_layout.takeAt(0)
            if item.widget() and item.widget() is not self._no_settings_lbl:
                item.widget().deleteLater()

        # Flatten all enabled keys
        flat_rows: list[tuple[str, dict]] = []
        for _tab, settings in applied.items():
            for key, val in settings.items():
                if val:
                    entry = get_risk(key) or {}
                    flat_rows.append((key, entry))

        if not flat_rows:
            self._settings_layout.addWidget(self._no_settings_lbl)
            self._no_settings_lbl.show()
            return

        self._no_settings_lbl.hide()
        for key, entry in flat_rows:
            self._settings_layout.addWidget(self._make_setting_row(key, entry))

    def add_alert(self, message: str, culprit_key: str = "") -> None:
        """Prepend a timestamped alert row, optionally with a [Disable] button."""
        # Remove the "No alerts" placeholder if visible
        if self._no_alerts_lbl.isVisible():
            self._no_alerts_lbl.hide()
            # Remove it from layout so new rows appear above stretch
            self._alerts_layout.removeWidget(self._no_alerts_lbl)

        timestamp = datetime.now().strftime("%H:%M")

        row_frame = QFrame()
        row_frame.setStyleSheet(
            "QFrame { background-color: #2e1a00; border: 1px solid #ff9800;"
            " border-radius: 4px; }"
        )
        row_layout = QVBoxLayout(row_frame)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(4)

        msg_lbl = QLabel(f"[{timestamp}] {message}")
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "color: #ff9800; font-size: 11px; background: transparent; border: none;"
        )
        row_layout.addWidget(msg_lbl)

        if culprit_key:
            disable_btn = QPushButton(f"Disable {culprit_key}")
            disable_btn.setFixedHeight(22)
            disable_btn.setStyleSheet(
                "QPushButton { background-color: #3a2000; color: #ff9800;"
                " border: 1px solid #ff9800; border-radius: 3px; font-size: 11px;"
                " padding: 0 8px; }"
                "QPushButton:hover { background-color: #4a2800; }"
            )
            _key = culprit_key  # capture for lambda
            disable_btn.clicked.connect(lambda _checked, k=_key: self.disable_setting_requested.emit(k))
            row_layout.addWidget(disable_btn)

        # Insert at position 0 (most recent first), before stretch
        self._alerts_layout.insertWidget(0, row_frame)

    def clear_alerts(self) -> None:
        """Remove all alert rows."""
        while self._alerts_layout.count():
            item = self._alerts_layout.takeAt(0)
            if item.widget() and item.widget() is not self._no_alerts_lbl:
                item.widget().deleteLater()

        self._no_alerts_lbl.show()
        self._alerts_layout.addWidget(self._no_alerts_lbl)
        self._alerts_layout.addStretch()

    # ------------------------------------------------------------------ internals

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        arrow = "\u25b6" if self._collapsed else "\u25bc"
        self._header_btn.setText(f"  \u2665  Health Diagnostics  {arrow}")

    @staticmethod
    def _make_setting_row(key: str, entry: dict) -> QWidget:
        level = entry.get("level", "LOW")
        color = _LEVEL_COLORS.get(level, "#4caf50")
        display = entry.get("display", key)
        cause = entry.get("cause", "")

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        badge = QLabel(f" \u25cf {level} ")
        badge.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 700;"
            " background: transparent; border: none;"
        )

        name_lbl = QLabel(display)
        name_lbl.setStyleSheet(
            "color: #e0e0e0; font-size: 12px; background: transparent; border: none;"
        )

        row_layout.addWidget(badge)
        row_layout.addWidget(name_lbl)

        if cause and level != "LOW":
            row_layout.addSpacing(4)
            detail_lbl = QLabel(f"— {cause}")
            detail_lbl.setStyleSheet(
                "color: #757575; font-size: 11px; background: transparent; border: none;"
            )
            detail_lbl.setWordWrap(False)
            row_layout.addWidget(detail_lbl)

        row_layout.addStretch()
        return row


class TabMonitor(QWidget):
    """
    Network Monitor tab.

    Signals
    -------
    host_changed(str)           — emitted when user clicks Apply with a new host
    disable_setting_requested(str) — forwarded from DiagnosticPanel
    """

    host_changed = pyqtSignal(str)
    disable_setting_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_host: str = "1.1.1.1"

        # rolling stats
        self._min_ping: float = float("inf")
        self._max_ping: float = 0.0
        self._sum_ping: float = 0.0
        self._count:    int   = 0
        self._last_jitter: float = 0.0
        self._prev_latency: float = 0.0   # for consecutive-diff jitter
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

        # Diagnostic panel
        self._diag = DiagnosticPanel(self)
        self._diag.disable_setting_requested.connect(self.disable_setting_requested)
        layout.addWidget(self._diag, stretch=0)

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
        self._prev_latency = 0.0
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
            # Use running average so timeouts don't create a 0ms spike on the graph
            avg_latency = (self._sum_ping / self._count) if self._count > 0 else None
            if avg_latency is not None:
                self._graph.add_reading(avg_latency, jitter, loss_pct)
            self._refresh_stat_labels(0.0, jitter)
            return

        prev_latency = self._prev_latency if self._count > 0 else latency_ms
        self._count    += 1
        self._sum_ping += latency_ms
        self._min_ping  = min(self._min_ping, latency_ms)
        self._max_ping  = max(self._max_ping, latency_ms)

        # Proper jitter: mean absolute deviation of consecutive readings (RFC 3550).
        jitter = abs(latency_ms - prev_latency)
        self._prev_latency = latency_ms
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

    def update_applied_settings(self, applied: dict) -> None:
        """Forward applied settings to DiagnosticPanel for display."""
        self._diag.update_applied_settings(applied)

    def add_health_alert(self, message: str, culprit_key: str = "") -> None:
        """Forward a health alert to DiagnosticPanel."""
        self._diag.add_alert(message, culprit_key)

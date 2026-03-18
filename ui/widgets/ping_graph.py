"""
ui/widgets/ping_graph.py
Rolling ping / jitter / packet-loss graph for NetBoost.
Uses PyQtGraph with a 60-second (120-point @ 500 ms) rolling window.
"""

from collections import deque
from typing import Deque

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QColor


# ── Colour constants ────────────────────────────────────────────────────────
_BG        = "#0d0d1a"
_GRID      = "#2a2a4a"
_PING_CLR  = "#4fc3f7"   # blue
_JITTER_CLR = "#ff9800"  # orange
_LOSS_CLR  = "#f44336"   # red
_TEXT_CLR  = "#9e9e9e"
_AXIS_CLR  = "#4fc3f7"

_DEFAULT_WINDOW = 60        # seconds
_DEFAULT_POINTS = 120       # samples (@ 500 ms interval)


def _mk_pen(color: str, width: int = 1, style=None):
    pen = pg.mkPen(color=color, width=width)
    if style is not None:
        pen.setStyle(style)
    return pen


class PingGraph(pg.GraphicsLayoutWidget):
    """
    Two stacked PyQtGraph plots:
      - Top:    ping (solid blue) + jitter (dashed orange)  — Y: Latency (ms)
      - Bottom: packet loss % (red filled area)             — Y: Loss %
    Both plots share the X axis (relative time, -N .. 0 seconds).
    """

    def __init__(self, parent=None, window_seconds: int = _DEFAULT_WINDOW):
        super().__init__(parent=parent)

        self._window_seconds: int = window_seconds
        self._max_points: int     = window_seconds * 2   # 2 samples / second

        self._ping_data:   Deque[float] = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._jitter_data: Deque[float] = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._loss_data:   Deque[float] = deque([0.0] * self._max_points, maxlen=self._max_points)

        self._setup_ui()

    # ---------------------------------------------------------- UI setup ------

    def _setup_ui(self) -> None:
        self.setBackground(_BG)

        # Shared X data (-window .. 0)
        self._x = self._make_x()

        # ── Top plot: latency ──────────────────────────────────────────────
        self._plot_top: pg.PlotItem = self.addPlot(row=0, col=0)
        self._configure_plot(self._plot_top, "Latency (ms)", show_x_labels=False)
        self._plot_top.setYRange(0, 200, padding=0.05)

        self._curve_ping = self._plot_top.plot(
            self._x, list(self._ping_data),
            pen=_mk_pen(_PING_CLR, 2),
            name="Ping",
        )
        self._curve_jitter = self._plot_top.plot(
            self._x, list(self._jitter_data),
            pen=_mk_pen(_JITTER_CLR, 1, pg.QtCore.Qt.DashLine),
            name="Jitter",
        )

        # Legend (top-right corner)
        legend = self._plot_top.addLegend(offset=(-10, 10))
        legend.setParentItem(self._plot_top.graphicsItem())
        _style_legend(legend)

        # ── Bottom plot: loss ──────────────────────────────────────────────
        self._plot_bot: pg.PlotItem = self.addPlot(row=1, col=0)
        self._configure_plot(self._plot_bot, "Loss %", show_x_labels=True)
        self._plot_bot.setYRange(0, 100, padding=0)
        self._plot_bot.setXLink(self._plot_top)

        loss_color = QColor(_LOSS_CLR).darker(120)
        loss_color.setAlpha(160)
        loss_brush = pg.mkBrush(loss_color)
        self._curve_loss = self._plot_bot.plot(
            self._x, list(self._loss_data),
            pen=_mk_pen(_LOSS_CLR, 1),
            fillLevel=0,
            brush=loss_brush,
            name="Loss %",
        )

        # Relative height (top bigger)
        self.ci.layout.setRowStretchFactor(0, 3)
        self.ci.layout.setRowStretchFactor(1, 1)
        self.ci.layout.setSpacing(4)

    def _configure_plot(self, plot: pg.PlotItem, y_label: str, show_x_labels: bool) -> None:
        plot.setMenuEnabled(False)
        plot.hideButtons()

        # Background
        plot.getViewBox().setBackgroundColor(_BG)

        # Axes
        for axis_name in ("left", "bottom", "top", "right"):
            ax = plot.getAxis(axis_name)
            ax.setPen(_mk_pen(_GRID))
            ax.setTextPen(_mk_pen(_TEXT_CLR))

        # Y label
        plot.setLabel("left", y_label, color=_AXIS_CLR)

        # X label (only bottom plot)
        if show_x_labels:
            plot.setLabel("bottom", "Time (s)", color=_AXIS_CLR)
        else:
            plot.getAxis("bottom").setStyle(showValues=False)

        # X range fixed
        plot.setXRange(-self._window_seconds, 0, padding=0)
        plot.setMouseEnabled(x=False, y=False)

        # Grid
        plot.showGrid(x=True, y=True, alpha=0.25)

    # --------------------------------------------------------- Public API -----

    def add_reading(self, latency_ms: float, jitter_ms: float, loss_pct: float) -> None:
        """Append a single sample and refresh the graph."""
        self._ping_data.append(max(0.0, latency_ms))
        self._jitter_data.append(max(0.0, jitter_ms))
        self._loss_data.append(max(0.0, min(100.0, loss_pct)))
        self._refresh()

    def clear(self) -> None:
        """Reset all data to zero."""
        for buf in (self._ping_data, self._jitter_data, self._loss_data):
            for i in range(len(buf)):
                buf[i] = 0.0
        self._refresh()

    def set_window_seconds(self, n: int) -> None:
        """Change the rolling window width (seconds).  Clears existing data."""
        if n < 1:
            raise ValueError("window_seconds must be >= 1")
        self._window_seconds = n
        self._max_points = n * 2
        self._ping_data   = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._jitter_data = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._loss_data   = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._x = self._make_x()
        for plot in (self._plot_top, self._plot_bot):
            plot.setXRange(-self._window_seconds, 0, padding=0)
        self._refresh()

    # --------------------------------------------------------- Internals ------

    def _make_x(self) -> np.ndarray:
        return np.linspace(-self._window_seconds, 0, self._max_points)

    def _refresh(self) -> None:
        ping   = np.array(self._ping_data,   dtype=float)
        jitter = np.array(self._jitter_data, dtype=float)
        loss   = np.array(self._loss_data,   dtype=float)

        self._curve_ping.setData(self._x, ping)
        self._curve_jitter.setData(self._x, jitter)
        self._curve_loss.setData(self._x, loss)

        # Auto-scale Y on top plot
        max_lat = max(max(ping), max(jitter), 1.0)
        self._plot_top.setYRange(0, max_lat * 1.15, padding=0)


def _style_legend(legend: pg.LegendItem) -> None:
    legend.setLabelTextColor(_TEXT_CLR)
    try:
        legend.setBrush(pg.mkBrush(QColor("#1a1a2e")))
        legend.setPen(pg.mkPen(color="#2a2a4a"))
    except Exception:
        pass

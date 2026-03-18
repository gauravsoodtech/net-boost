"""
ui/widgets/status_led.py
Animated LED status indicator widget for NetBoost.
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen, QRadialGradient


# Maps state name -> (core colour, glow colour)
_STATE_COLORS = {
    "green":  (QColor("#4caf50"), QColor(76,  175, 80,  120)),
    "yellow": (QColor("#ff9800"), QColor(255, 152, 0,   120)),
    "red":    (QColor("#f44336"), QColor(244, 67,  54,  120)),
    "grey":   (QColor("#555575"), QColor(85,  85,  117, 60)),
}

_VALID_STATES = frozenset(_STATE_COLORS.keys())


class AnimatedLED(QWidget):
    """
    A small circular LED indicator that renders a solid filled circle with a
    radial glow behind it.  Supported states: "green", "yellow", "red", "grey".
    """

    def __init__(self, state: str = "grey", parent=None):
        super().__init__(parent)
        self._state: str = state if state in _VALID_STATES else "grey"
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.sizeHint())

    # ------------------------------------------------------------------ API --

    def setState(self, state: str) -> None:
        """Set LED state to one of: 'green', 'yellow', 'red', 'grey'."""
        if state not in _VALID_STATES:
            raise ValueError(f"Invalid LED state '{state}'. Choose from {sorted(_VALID_STATES)}.")
        if state != self._state:
            self._state = state
            self.update()

    def getState(self) -> str:
        """Return the current LED state string."""
        return self._state

    # ----------------------------------------------------------- Qt overrides --

    def sizeHint(self) -> QSize:
        return QSize(16, 16)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        core_color, glow_color = _STATE_COLORS[self._state]

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0

        # --- Glow: larger semi-transparent circle ---
        glow_r = min(w, h) / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(
            int(cx - glow_r), int(cy - glow_r),
            int(glow_r * 2), int(glow_r * 2),
        )

        # --- Core: solid filled circle with radial gradient for 3-D look ---
        core_r = glow_r * 0.62
        gradient = QRadialGradient(cx - core_r * 0.25, cy - core_r * 0.25, core_r)
        lighter = core_color.lighter(160)
        gradient.setColorAt(0.0, lighter)
        gradient.setColorAt(0.6, core_color)
        gradient.setColorAt(1.0, core_color.darker(130))

        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(core_color.darker(150), 1))
        painter.drawEllipse(
            int(cx - core_r), int(cy - core_r),
            int(core_r * 2), int(core_r * 2),
        )

        painter.end()

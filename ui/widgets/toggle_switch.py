"""
ui/widgets/toggle_switch.py
iOS-style animated toggle switch for NetBoost.
"""

from PyQt5.QtWidgets import QAbstractButton, QSizePolicy
from PyQt5.QtCore import (
    Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty,
)
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen


_COLOR_TRACK_OFF  = QColor("#232332")
_COLOR_TRACK_ON   = QColor("#00E5FF")
_COLOR_THUMB      = QColor("#F3F4F6")
_COLOR_THUMB_SHADOW = QColor(0, 0, 0, 80)

_ANIM_DURATION_MS = 200  # milliseconds


class ToggleSwitch(QAbstractButton):
    """
    Animated iOS-style toggle switch.

    Use ``isChecked()`` / ``setChecked()`` for state control.
    The inherited ``toggled(bool)`` signal fires on every state change.
    The ``thumb_pos`` property (0.0 = off, 1.0 = on) drives the animation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)

        # Internal animated position (0.0 → off, 1.0 → on)
        self._thumb_pos: float = 0.0

        # Animation
        self._animation = QPropertyAnimation(self, b"thumb_pos", self)
        self._animation.setDuration(_ANIM_DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)

        # Keep thumb_pos in sync when toggled externally (e.g. setChecked)
        self.toggled.connect(self._on_toggled)

    # --------------------------------------------------------------- Property --

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, value: float) -> None:
        self._thumb_pos = float(value)
        self.update()

    thumb_pos = pyqtProperty(float, _get_thumb_pos, _set_thumb_pos)

    # -------------------------------------------------------------- Internals --

    def _animate_to(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._thumb_pos)
        self._animation.setEndValue(target)
        self._animation.start()

    def _on_toggled(self, checked: bool) -> None:
        self._animate_to(1.0 if checked else 0.0)

    # ----------------------------------------------------------- Qt overrides --

    def sizeHint(self) -> QSize:
        return QSize(50, 26)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggle()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        track_h = int(h * 0.75)
        track_y  = (h - track_h) // 2
        radius   = track_h // 2

        # --- Interpolate track colour between off and on ---
        t = self._thumb_pos  # 0.0 → 1.0
        r = int(_COLOR_TRACK_OFF.red()   + t * (_COLOR_TRACK_ON.red()   - _COLOR_TRACK_OFF.red()))
        g = int(_COLOR_TRACK_OFF.green() + t * (_COLOR_TRACK_ON.green() - _COLOR_TRACK_OFF.green()))
        b = int(_COLOR_TRACK_OFF.blue()  + t * (_COLOR_TRACK_ON.blue()  - _COLOR_TRACK_OFF.blue()))
        track_color = QColor(r, g, b)

        # Track
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(0, track_y, w, track_h, radius, radius)

        # Thumb shadow
        thumb_diameter = int(h * 0.88)
        thumb_margin   = (h - thumb_diameter) // 2
        travel         = w - thumb_diameter - thumb_margin * 2
        thumb_x        = int(thumb_margin + t * travel)
        thumb_y        = thumb_margin

        shadow_offset = 1
        painter.setBrush(QBrush(_COLOR_THUMB_SHADOW))
        painter.drawEllipse(
            thumb_x + shadow_offset,
            thumb_y + shadow_offset,
            thumb_diameter,
            thumb_diameter,
        )

        # Thumb
        painter.setBrush(QBrush(_COLOR_THUMB))
        painter.setPen(QPen(QColor(200, 200, 200, 80), 0.5))
        painter.drawEllipse(thumb_x, thumb_y, thumb_diameter, thumb_diameter)

        # Focus ring (keyboard navigation)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#4fc3f7"), 2))
            painter.drawRoundedRect(0, 0, w, h, radius + 2, radius + 2)

        painter.end()

"""
ui/widgets/status_toast.py
Floating toast notification — shows success / error / info feedback.
Appears in the top-right corner of the parent window and auto-dismisses.
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve


class StatusToast(QWidget):
    """
    Semi-transparent overlay toast that fades in, holds, then fades out.

    Usage::
        toast = StatusToast(main_window)
        toast.show_message("Applied!", "success")
    """

    _STYLES = {
        "success": ("#0a2e10", "#4caf50", "\u2713"),
        "error":   ("#2e0a0a", "#f44336", "\u2717"),
        "info":    ("#0a1a2e", "#4fc3f7", "\u2139"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        self._icon_lbl = QLabel()
        layout.addWidget(self._icon_lbl)

        self._msg_lbl = QLabel()
        self._msg_lbl.setWordWrap(False)
        layout.addWidget(self._msg_lbl)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        # Separate animations so finished.connect(hide) is wired exactly once
        self._in_anim = QPropertyAnimation(self._opacity, b"opacity")
        self._in_anim.setDuration(250)
        self._in_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._in_anim.setStartValue(0.0)
        self._in_anim.setEndValue(0.95)

        self._out_anim = QPropertyAnimation(self._opacity, b"opacity")
        self._out_anim.setDuration(300)
        self._out_anim.setEasingCurve(QEasingCurve.InCubic)
        self._out_anim.setEndValue(0.0)
        self._out_anim.finished.connect(self.hide)  # wired once, never re-added

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._start_fade_out)

        self.hide()

    def show_message(self, msg: str, kind: str = "info", duration_ms: int = 3000) -> None:
        bg, fg, icon = self._STYLES.get(kind, self._STYLES["info"])

        self.setStyleSheet(
            f"QWidget {{ background-color:{bg}; border:1px solid {fg}; border-radius:8px; }}"
        )
        self._icon_lbl.setStyleSheet(
            f"color:{fg}; font-size:14px; font-weight:700; background:transparent; border:none;"
        )
        self._icon_lbl.setText(icon)
        self._msg_lbl.setStyleSheet(
            f"color:{fg}; font-size:13px; font-weight:600; background:transparent; border:none;"
        )
        self._msg_lbl.setText(msg)

        # Cancel whatever is currently running
        self._hold_timer.stop()
        self._in_anim.stop()
        self._out_anim.stop()

        self.adjustSize()
        self._reposition()
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self._in_anim.start()
        self._hold_timer.start(duration_ms)

    def _reposition(self) -> None:
        if self.parent():
            p = self.parent()
            self.move(p.width() - self.width() - 16, 66)

    def _start_fade_out(self) -> None:
        self._out_anim.setStartValue(self._opacity.opacity())
        self._out_anim.start()

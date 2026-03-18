"""
ui/widgets/risk_warning_dialog.py
Pre-apply warning modal shown when HIGH or MEDIUM risk settings are about to be applied.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame,
)
from PyQt5.QtCore import Qt


_LEVEL_COLORS = {
    "HIGH":   ("#f44336", "#2e0a0a"),
    "MEDIUM": ("#ff9800", "#2e1a00"),
    "LOW":    ("#4caf50", "#0a2e10"),
}


class RiskWarningDialog(QDialog):
    """
    Modal listing risky settings with cause/advice before the user applies.

    Parameters
    ----------
    risky  : list of (key, risk_entry) from filter_by_level()
    parent : parent QWidget
    """

    def __init__(self, risky: list[tuple[str, dict]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings Risk Warning")
        self.setMinimumWidth(520)
        self.setModal(True)
        self._build_ui(risky)

    def _build_ui(self, risky: list[tuple[str, dict]]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        header = QLabel("\u26a0  The following settings carry elevated risk")
        header.setStyleSheet(
            "color: #ff9800; font-size: 14px; font-weight: 700;"
            " background: transparent; border: none;"
        )
        layout.addWidget(header)

        sub = QLabel(
            "Review the warnings below before proceeding. "
            "You can still apply these settings if you accept the trade-offs."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            "color: #9e9e9e; font-size: 12px; background: transparent; border: none;"
        )
        layout.addWidget(sub)

        # Scrollable risk rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(320)

        container = QWidget()
        rows_layout = QVBoxLayout(container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(8)

        for key, entry in risky:
            rows_layout.addWidget(self._make_row(key, entry))

        rows_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        review_btn = QPushButton("Review Settings")
        review_btn.setObjectName("primaryButton")
        review_btn.setFixedWidth(140)
        review_btn.clicked.connect(self.reject)

        apply_btn = QPushButton("Apply Anyway")
        apply_btn.setObjectName("dangerButton")
        apply_btn.setFixedWidth(140)
        apply_btn.clicked.connect(self.accept)

        btn_row.addWidget(review_btn)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _make_row(key: str, entry: dict) -> QFrame:
        level = entry.get("level", "LOW")
        fg, bg = _LEVEL_COLORS.get(level, ("#4caf50", "#0a2e10"))
        display = entry.get("display", key)
        cause = entry.get("cause", "")
        advice = entry.get("advice", "")

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {fg};"
            " border-radius: 6px; padding: 4px; }}"
        )

        main_layout = QVBoxLayout(frame)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(4)

        # Top row: badge + name
        top = QHBoxLayout()
        top.setSpacing(8)

        badge = QLabel(f" {level} ")
        badge.setStyleSheet(
            f"color: #121212; background-color: {fg}; border-radius: 3px;"
            " font-size: 11px; font-weight: 700; padding: 1px 4px; border: none;"
        )
        badge.setFixedHeight(20)

        name_lbl = QLabel(display)
        name_lbl.setStyleSheet(
            f"color: {fg}; font-size: 13px; font-weight: 700;"
            " background: transparent; border: none;"
        )

        top.addWidget(badge)
        top.addWidget(name_lbl)
        top.addStretch()
        main_layout.addLayout(top)

        if cause:
            cause_lbl = QLabel(f"\u2022 {cause}")
            cause_lbl.setWordWrap(True)
            cause_lbl.setStyleSheet(
                "color: #e0e0e0; font-size: 12px; background: transparent; border: none;"
            )
            main_layout.addWidget(cause_lbl)

        if advice:
            advice_lbl = QLabel(f"\U0001f4a1 {advice}")
            advice_lbl.setWordWrap(True)
            advice_lbl.setStyleSheet(
                "color: #9e9e9e; font-size: 11px; background: transparent; border: none;"
            )
            main_layout.addWidget(advice_lbl)

        return frame

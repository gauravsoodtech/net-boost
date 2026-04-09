"""
ui/widgets/toggle_row.py — Shared toggle row widget for all optimizer tabs.
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from .toggle_switch import ToggleSwitch


class ToggleRow(QWidget):
    """
    One row: [ToggleSwitch] [Label] [optional badge/note] ... [● Active]

    Parameters
    ----------
    key : str
        Setting key name (e.g. ``"disable_lso"``).
    label : str
        Human-readable label text.
    badge : str
        Optional red badge text (e.g. ``"CRITICAL"``).
    note : str
        Optional grey note text (e.g. ``"(requires reboot)"``).
    tooltip : str
        Optional tooltip; adds dotted underline visual cue when set.
    """

    def __init__(
        self,
        key: str,
        label: str,
        badge: str = "",
        note: str = "",
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.key = key

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        self.switch = ToggleSwitch()
        layout.addWidget(self.switch)

        lbl = QLabel(label)
        lbl_style = "background: transparent; border: none; color: #e0e0e0;"
        if tooltip:
            lbl.setToolTip(tooltip)
            lbl_style += " text-decoration: underline dotted; cursor: help;"
        lbl.setStyleSheet(lbl_style)
        layout.addWidget(lbl)

        if badge:
            badge_lbl = QLabel(badge)
            badge_lbl.setStyleSheet(
                "background-color: #3a0a0a; color: #f44336;"
                " border: 1px solid #f44336; border-radius: 3px;"
                " font-size: 10px; font-weight: 700; padding: 1px 5px;"
            )
            layout.addWidget(badge_lbl)

        if note:
            note_lbl = QLabel(note)
            note_lbl.setStyleSheet(
                "color: #9e9e9e; font-size: 11px;"
                " background: transparent; border: none;"
            )
            layout.addWidget(note_lbl)

        layout.addStretch()

        self._status_badge = QLabel("\u25cf Active")
        self._status_badge.setStyleSheet(
            "color: #4caf50; font-size: 10px; font-weight: 700;"
            " background: transparent; border: none;"
        )
        self._status_badge.setVisible(False)
        layout.addWidget(self._status_badge)

        self.setStyleSheet("background: transparent;")

    def set_applied(self, applied: bool) -> None:
        """Show or hide the green '● Active' badge."""
        self._status_badge.setVisible(applied)

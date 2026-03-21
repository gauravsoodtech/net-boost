"""
ui/tab_dashboard.py
Dashboard tab — master game-mode toggle, live ping stats, battery warning.
"""

from PyQt5.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QSizePolicy, QSpacerItem,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .widgets.toggle_switch import ToggleSwitch


# ── Small helper: stat badge ─────────────────────────────────────────────────

class _StatBadge(QFrame):
    """A card widget that displays a large metric value + small unit label."""

    def __init__(self, label: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("statBadge")
        self.setMinimumSize(120, 90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        self._value_label = QLabel("--")
        value_font = QFont("Segoe UI", 28, QFont.Bold)
        self._value_label.setFont(value_font)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet("color: #4fc3f7; background: transparent; border: none;")

        self._unit_label = QLabel(unit)
        self._unit_label.setAlignment(Qt.AlignCenter)
        self._unit_label.setStyleSheet("color: #9e9e9e; font-size: 11px; background: transparent; border: none;")

        self._desc_label = QLabel(label)
        self._desc_label.setAlignment(Qt.AlignCenter)
        self._desc_label.setStyleSheet("color: #9e9e9e; font-size: 11px; background: transparent; border: none;")

        layout.addWidget(self._value_label)
        layout.addWidget(self._unit_label)
        layout.addWidget(self._desc_label)

    def set_value(self, value) -> None:
        if isinstance(value, float):
            self._value_label.setText(f"{value:.1f}")
        else:
            self._value_label.setText(str(value))

    def set_color(self, css_color: str) -> None:
        self._value_label.setStyleSheet(
            f"color: {css_color}; background: transparent; border: none;"
        )


# ── Dashboard Tab ─────────────────────────────────────────────────────────────

class TabDashboard(QWidget):
    """
    Main dashboard tab.

    Signals
    -------
    game_mode_toggled(bool)   — emitted when the master Game Mode switch changes
    """

    game_mode_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        root = QGridLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # ── Row 0: Game Mode toggle ──────────────────────────────────────────
        top_frame = QFrame()
        top_frame.setObjectName("topFrame")
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(16)

        # Master toggle
        self._game_mode_switch = ToggleSwitch()
        self._game_mode_switch.setToolTip("Enable/disable all NetBoost optimisations")
        self._game_mode_switch.toggled.connect(self._on_game_mode_toggled)

        gm_title = QLabel("Game Mode")
        gm_title.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #4fc3f7;"
            " background: transparent; border: none;"
        )
        # Bigger toggle
        self._game_mode_switch.setFixedSize(70, 36)

        top_layout.addWidget(self._game_mode_switch)
        top_layout.addWidget(gm_title)
        top_layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Detected game
        self._game_label = QLabel("No game detected")
        self._game_label.setStyleSheet(
            "color: #9e9e9e; font-size: 13px; background: transparent; border: none;"
        )
        top_layout.addWidget(self._game_label)

        separator = QLabel("  |  ")
        separator.setStyleSheet("color: #2a2a4a; background: transparent; border: none;")
        top_layout.addWidget(separator)

        # Active profile
        self._profile_label = QLabel("Profile: Default")
        self._profile_label.setStyleSheet(
            "color: #e040fb; font-size: 13px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        top_layout.addWidget(self._profile_label)

        root.addWidget(top_frame, 0, 0, 1, 4)

        # ── Row 1: Stat badges ───────────────────────────────────────────────
        self._badge_ping   = _StatBadge("Current Ping", "ms")
        self._badge_jitter = _StatBadge("Jitter", "ms")
        self._badge_loss   = _StatBadge("Packet Loss", "%")
        self._badge_ram    = _StatBadge("Free RAM", "MB")

        for col, badge in enumerate([
            self._badge_ping, self._badge_jitter,
            self._badge_loss, self._badge_ram,
        ]):
            badge.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            root.addWidget(badge, 1, col)

        # ── Row 2: Battery warning ───────────────────────────────────────────
        self._battery_warning = QLabel(
            "  WARNING: Running on battery — optimisation effectiveness reduced  "
        )
        self._battery_warning.setAlignment(Qt.AlignCenter)
        self._battery_warning.setStyleSheet(
            "background-color: #3a1a00; color: #ff9800;"
            " border: 1px solid #ff9800; border-radius: 5px;"
            " font-size: 12px; font-weight: 600; padding: 6px;"
        )
        self._battery_warning.setVisible(False)
        root.addWidget(self._battery_warning, 2, 0, 1, 4)

        # ── Row 3: Status message ────────────────────────────────────────────
        self._status_label = QLabel("NetBoost ready.")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet(
            "color: #9e9e9e; font-size: 12px; background: transparent; border: none;"
        )
        root.addWidget(self._status_label, 3, 0, 1, 4)

        # Row stretches
        root.setRowStretch(0, 0)
        root.setRowStretch(1, 1)
        root.setRowStretch(2, 0)
        root.setRowStretch(3, 0)
        for col in range(4):
            root.setColumnStretch(col, 1)

    # ---------------------------------------------------------- Internals ------

    def _on_game_mode_toggled(self, checked: bool) -> None:
        self.game_mode_toggled.emit(checked)
        self._status_label.setText(
            "Game Mode ENABLED — all optimisations active." if checked
            else "Game Mode DISABLED."
        )

    # ---------------------------------------------------------- Public API ------

    def update_ping_stats(self, ping, jitter, loss: float) -> None:
        """Update the three latency stat badges. ping/jitter are None when offline."""
        if ping is None:
            self._badge_ping.set_value("--")
            self._badge_ping.set_color("#9e9e9e")
            self._badge_jitter.set_value("--")
        else:
            self._badge_ping.set_value(ping)
            self._badge_jitter.set_value(jitter if jitter is not None else 0.0)
            if ping < 30:
                self._badge_ping.set_color("#4caf50")
            elif ping < 80:
                self._badge_ping.set_color("#4fc3f7")
            elif ping < 150:
                self._badge_ping.set_color("#ff9800")
            else:
                self._badge_ping.set_color("#f44336")

        # Colour-code loss badge and update its value
        self._badge_loss.set_value(loss)
        if loss == 0:
            self._badge_loss.set_color("#4caf50")
        elif loss < 2:
            self._badge_loss.set_color("#ff9800")
        else:
            self._badge_loss.set_color("#f44336")

    def set_game_detected(self, name) -> None:
        """Show/hide the detected game name."""
        if name:
            self._game_label.setText(f"Game: {name}")
            self._game_label.setStyleSheet(
                "color: #4caf50; font-size: 13px; font-weight: 600;"
                " background: transparent; border: none;"
            )
        else:
            self._game_label.setText("No game detected")
            self._game_label.setStyleSheet(
                "color: #9e9e9e; font-size: 13px; background: transparent; border: none;"
            )

    def set_active_profile(self, name: str) -> None:
        self._profile_label.setText(f"Profile: {name}")

    def set_game_mode(self, enabled: bool) -> None:
        """Set the Game Mode toggle without emitting the signal recursively."""
        self._game_mode_switch.blockSignals(True)
        self._game_mode_switch.setChecked(enabled)
        self._game_mode_switch.blockSignals(False)

    def set_battery_warning(self, on_battery: bool) -> None:
        self._battery_warning.setVisible(on_battery)

    def set_free_ram(self, mb: int) -> None:
        self._badge_ram.set_value(mb)
        self._badge_ram.set_color("#e040fb")

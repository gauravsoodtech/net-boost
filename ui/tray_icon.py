"""
NetBoost System Tray Icon
Grey (idle) / Green (game mode on) / Yellow (game detected, mode off)
Quick-toggle + profile switcher in tray menu
"""
import logging

from PyQt5.QtWidgets import (
    QSystemTrayIcon, QMenu, QAction, QActionGroup,
    QApplication
)
from PyQt5.QtGui import QIcon, QPixmap, QColor, QPainter, QBrush
from PyQt5.QtCore import Qt, QSize

logger = logging.getLogger(__name__)


def _make_circle_icon(color: str, size: int = 22) -> QIcon:
    """Create a simple circle icon of the given color."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(Qt.NoPen)
    margin = 2
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pixmap)


ICON_GREY = None
ICON_GREEN = None
ICON_YELLOW = None


def _get_icons():
    global ICON_GREY, ICON_GREEN, ICON_YELLOW
    if ICON_GREY is None:
        ICON_GREY = _make_circle_icon("#9e9e9e")
        ICON_GREEN = _make_circle_icon("#4caf50")
        ICON_YELLOW = _make_circle_icon("#ff9800")
    return ICON_GREY, ICON_GREEN, ICON_YELLOW


class TrayIcon(QSystemTrayIcon):
    """System tray icon with quick-toggle and profile switcher."""

    def __init__(self, main_window, app: QApplication, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.app = app
        self._game_mode_on = False
        self._game_detected = False
        self._profiles = []

        ICON_GREY, ICON_GREEN, ICON_YELLOW = _get_icons()
        self.setIcon(ICON_GREY)
        self.setToolTip("NetBoost — Idle")

        self._build_menu()
        self.activated.connect(self._on_activated)

        # Connect to main window signals via dashboard tab
        try:
            main_window.tab_dashboard.game_mode_toggled.connect(self._on_game_mode_changed)
        except Exception as e:
            logger.warning(f"Could not connect game_mode_toggled: {e}")

        self.show()

    def _build_menu(self):
        menu = QMenu()

        # Show/Hide window
        self._show_action = QAction("Show NetBoost", self)
        self._show_action.triggered.connect(self._toggle_window)
        menu.addAction(self._show_action)

        menu.addSeparator()

        # Game Mode toggle
        self._toggle_action = QAction("Enable Game Mode", self)
        self._toggle_action.setCheckable(True)
        self._toggle_action.triggered.connect(self._toggle_game_mode)
        menu.addAction(self._toggle_action)

        menu.addSeparator()

        # Profile submenu
        self._profile_menu = QMenu("Switch Profile", menu)
        self._profile_group = QActionGroup(self._profile_menu)
        self._profile_group.setExclusive(True)
        menu.addMenu(self._profile_menu)

        menu.addSeparator()

        # Quit
        quit_action = QAction("Quit NetBoost", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _toggle_window(self):
        if self.main_window.isVisible():
            self.main_window.hide()
            self._show_action.setText("Show NetBoost")
        else:
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()
            self._show_action.setText("Hide NetBoost")

    def _toggle_game_mode(self, checked: bool):
        """Called when user clicks tray toggle."""
        try:
            self.main_window.tab_dashboard.set_game_mode(checked)
            # This triggers the signal which will also call our _on_game_mode_changed
        except Exception as e:
            logger.error(f"Tray game mode toggle failed: {e}")

    def _on_game_mode_changed(self, enabled: bool):
        """Called when game mode changes (from window or tray)."""
        self._game_mode_on = enabled
        self._toggle_action.setChecked(enabled)
        self._update_icon()
        self.setToolTip(f"NetBoost — {'Game Mode ON' if enabled else 'Idle'}")

    def set_game_detected(self, game_name: str | None):
        self._game_detected = game_name is not None
        self._update_icon()
        if game_name:
            self.setToolTip(f"NetBoost — {game_name} detected")

    def _update_icon(self):
        ICON_GREY, ICON_GREEN, ICON_YELLOW = _get_icons()
        if self._game_mode_on:
            self.setIcon(ICON_GREEN)
        elif self._game_detected:
            self.setIcon(ICON_YELLOW)
        else:
            self.setIcon(ICON_GREY)

    def update_profiles(self, profiles: list, active: str):
        """Rebuild profile submenu."""
        self._profiles = profiles
        self._profile_menu.clear()

        for action in self._profile_group.actions():
            self._profile_group.removeAction(action)

        for name in profiles:
            action = QAction(name, self._profile_menu)
            action.setCheckable(True)
            action.setChecked(name == active)
            action.triggered.connect(lambda checked, n=name: self._switch_profile(n))
            self._profile_group.addAction(action)
            self._profile_menu.addAction(action)

    def _switch_profile(self, name: str):
        try:
            self.main_window._on_profile_load(name)
            # Update checkmarks
            for action in self._profile_group.actions():
                action.setChecked(action.text() == name)
        except Exception as e:
            logger.error(f"Tray profile switch failed: {e}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_window()

    def _quit(self):
        self.main_window.show()  # Ensure cleanup happens
        self.app.quit()

"""
ui/tab_profiles.py
Profiles tab — list, preview, create, duplicate, import/export profiles.
"""

import json
from typing import List

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QGroupBox, QListWidget,
    QListWidgetItem, QTextEdit, QSplitter, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class TabProfiles(QWidget):
    """
    Profiles management tab.

    Signals
    -------
    profile_selected(str)        — fired when a profile is clicked in the list
    profile_load_requested(str)  — "Load Profile" button
    profile_delete_requested(str)— "Delete" button
    profile_new_requested()      — "New" button
    profile_import_requested()   — "Import" button
    profile_export_requested(str)— "Export" button (passes selected name)
    """

    profile_selected          = pyqtSignal(str)
    profile_load_requested    = pyqtSignal(str)
    profile_delete_requested  = pyqtSignal(str)
    profile_new_requested     = pyqtSignal()
    profile_duplicate_requested = pyqtSignal(str)
    profile_import_requested  = pyqtSignal()
    profile_export_requested  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: List[str] = []
        self._active_profile: str = ""
        self._profile_data: dict  = {}  # name -> arbitrary dict, for JSON preview
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Profiles")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        # ── Left panel ───────────────────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        list_label = QLabel("Saved Profiles")
        list_label.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; font-weight: 700;"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        left_layout.addWidget(list_label)

        self._list = QListWidget()
        self._list.setMinimumWidth(180)
        self._list.currentTextChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._list, stretch=1)

        # Action buttons
        btn_grid_top = QHBoxLayout()
        btn_grid_top.setSpacing(6)

        self._new_btn = QPushButton("New")
        self._dup_btn = QPushButton("Duplicate")
        self._del_btn = QPushButton("Delete")
        self._del_btn.setObjectName("dangerButton")

        for btn in (self._new_btn, self._dup_btn, self._del_btn):
            btn.setMinimumHeight(30)
            btn_grid_top.addWidget(btn)

        btn_grid_bot = QHBoxLayout()
        btn_grid_bot.setSpacing(6)

        self._import_btn = QPushButton("Import")
        self._export_btn = QPushButton("Export")

        for btn in (self._import_btn, self._export_btn):
            btn.setMinimumHeight(30)
            btn_grid_bot.addWidget(btn)

        left_layout.addLayout(btn_grid_top)
        left_layout.addLayout(btn_grid_bot)

        # Wire buttons
        self._new_btn.clicked.connect(self.profile_new_requested.emit)
        self._dup_btn.clicked.connect(self._on_duplicate)
        self._del_btn.clicked.connect(self._on_delete)
        self._import_btn.clicked.connect(self.profile_import_requested.emit)
        self._export_btn.clicked.connect(self._on_export)

        splitter.addWidget(left)

        # ── Right panel ──────────────────────────────────────────────────────
        details_group = QGroupBox("Profile Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(10)

        self._name_label = QLabel("No profile selected")
        name_font = QFont("Segoe UI", 15, QFont.Bold)
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet(
            "color: #4fc3f7; background: transparent; border: none;"
        )
        details_layout.addWidget(self._name_label)

        self._active_badge = QLabel("ACTIVE")
        self._active_badge.setStyleSheet(
            "background-color: #0d2e10; color: #4caf50;"
            " border: 1px solid #4caf50; border-radius: 3px;"
            " font-size: 10px; font-weight: 700; padding: 2px 6px;"
        )
        self._active_badge.setVisible(False)
        details_layout.addWidget(self._active_badge)

        preview_label = QLabel("Settings Preview (JSON)")
        preview_label.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; background: transparent; border: none;"
        )
        details_layout.addWidget(preview_label)

        self._json_preview = QTextEdit()
        self._json_preview.setReadOnly(True)
        self._json_preview.setPlaceholderText("Select a profile to preview its settings…")
        details_layout.addWidget(self._json_preview, stretch=1)

        # Detail action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._load_btn = QPushButton("Load Profile")
        self._load_btn.setObjectName("primaryButton")
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)

        self._activate_btn = QPushButton("Set as Active")
        self._activate_btn.setObjectName("successButton")
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_set_active)

        action_row.addStretch()
        action_row.addWidget(self._load_btn)
        action_row.addWidget(self._activate_btn)
        details_layout.addLayout(action_row)

        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

    # ---------------------------------------------------------- Internals ------

    def _selected_name(self):
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self, _text: str) -> None:
        name = self._selected_name()
        if not name:
            self._name_label.setText("No profile selected")
            self._json_preview.clear()
            self._active_badge.setVisible(False)
            self._load_btn.setEnabled(False)
            self._activate_btn.setEnabled(False)
            return

        self._name_label.setText(name)
        self._active_badge.setVisible(name == self._active_profile)
        self._load_btn.setEnabled(True)
        self._activate_btn.setEnabled(True)

        data = self._profile_data.get(name, {})
        self._json_preview.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        self.profile_selected.emit(name)

    def _on_duplicate(self) -> None:
        name = self._selected_name()
        if name:
            self.profile_duplicate_requested.emit(name)

    def _on_delete(self) -> None:
        name = self._selected_name()
        if name:
            self.profile_delete_requested.emit(name)

    def _on_export(self) -> None:
        name = self._selected_name()
        if name:
            self.profile_export_requested.emit(name)

    def _on_load(self) -> None:
        name = self._selected_name()
        if name:
            self.profile_load_requested.emit(name)

    def _on_set_active(self) -> None:
        name = self._selected_name()
        if name:
            self._active_profile = name
            self._refresh_list_display()
            self._active_badge.setVisible(True)

    def _refresh_list_display(self) -> None:
        """Reapply bold/checkmark decoration based on active profile."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.data(Qt.UserRole)
            is_active = (name == self._active_profile)
            f = item.font()
            f.setBold(is_active)
            item.setFont(f)
            item.setText(f"✓  {name}" if is_active else f"    {name}")

    # ---------------------------------------------------------- Public API ------

    def set_profiles(self, profiles: List[str], active: str,
                     profile_data: dict = None) -> None:
        """
        Populate the profile list.

        Parameters
        ----------
        profiles     : ordered list of profile name strings
        active       : name of the currently active profile
        profile_data : optional {name: dict} for JSON preview pane
        """
        self._profiles = list(profiles)
        self._active_profile = active
        if profile_data:
            self._profile_data = profile_data

        self._list.blockSignals(True)
        self._list.clear()
        for name in profiles:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            is_active = (name == active)
            f = item.font()
            f.setBold(is_active)
            item.setFont(f)
            item.setText(f"✓  {name}" if is_active else f"    {name}")
            self._list.addItem(item)
        self._list.blockSignals(False)

        # Re-select previously selected if possible
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
            self._on_selection_changed("")

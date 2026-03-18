"""
ui/tab_wifi.py
Wi-Fi Optimizer tab — toggle switches for Intel AX211 6E adapter settings.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QGroupBox, QFrame,
    QScrollArea, QSizePolicy, QSpacerItem,
)
from PyQt5.QtCore import Qt, pyqtSignal

from .widgets.toggle_switch import ToggleSwitch


# ── Helper: a labelled toggle row ────────────────────────────────────────────

class _ToggleRow(QWidget):
    """One row: [ToggleSwitch] [Label] [optional badge]"""

    def __init__(self, key: str, label: str, badge: str = "", tooltip: str = "", parent=None):
        super().__init__(parent)
        self.key = key

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        self.switch = ToggleSwitch()
        layout.addWidget(self.switch)

        lbl = QLabel(label)
        lbl.setStyleSheet("background: transparent; border: none; color: #e0e0e0;")
        if tooltip:
            lbl.setToolTip(tooltip)
        layout.addWidget(lbl)

        if badge:
            badge_lbl = QLabel(badge)
            badge_lbl.setStyleSheet(
                "background-color: #3a0a0a; color: #f44336;"
                " border: 1px solid #f44336; border-radius: 3px;"
                " font-size: 10px; font-weight: 700; padding: 1px 5px;"
            )
            layout.addWidget(badge_lbl)

        layout.addStretch()
        self.setStyleSheet("background: transparent;")


# ── Wi-Fi Tab ─────────────────────────────────────────────────────────────────

class TabWifi(QWidget):
    """
    Wi-Fi Optimizer tab.

    Signals
    -------
    settings_applied(dict)  — emitted when user clicks "Apply All"
    settings_restored()     — emitted when user clicks "Restore Defaults"
    """

    settings_applied  = pyqtSignal(dict)
    settings_restored = pyqtSignal()

    # Ordered list of (key, label, badge, tooltip)
    _TOGGLES = [
        ("disable_power_saving",    "Disable Power Saving",              "CRITICAL", ""),
        ("minimize_roaming",        "Minimize Roaming Aggressiveness",   "", ""),
        ("max_tx_power",            "Maximum TX Power",                  "", ""),
        ("disable_bss_scan",        "Disable Background BSS Scanning",   "", ""),
        ("prefer_6ghz",             "Prefer 6 GHz Band",                 "", ""),
        ("throughput_booster",      "Throughput Booster",                "", ""),
        ("disable_mimo_power_save", "Disable MIMO Power Saving",         "", ""),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle_rows: dict[str, _ToggleRow] = {}
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        container.setObjectName("wifiContainer")
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Title ────────────────────────────────────────────────────────────
        title = QLabel("Wi-Fi Optimizer")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel("Intel AX211 6E — Disable Power Saving & Background Scanning")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

        # ── Status row ───────────────────────────────────────────────────────
        status_frame = QFrame()
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(16)

        self._band_label = QLabel("Current Band: --")
        self._band_label.setStyleSheet(
            "color: #4fc3f7; font-weight: 600; font-size: 13px; background: transparent; border: none;"
        )
        status_layout.addWidget(self._band_label)

        sep = QLabel("|")
        sep.setStyleSheet("color: #2a2a4a; background: transparent; border: none;")
        status_layout.addWidget(sep)

        self._adapter_label = QLabel("Intel Wi-Fi 6E AX211")
        self._adapter_label.setStyleSheet(
            "color: #9e9e9e; font-size: 12px; background: transparent; border: none;"
        )
        status_layout.addWidget(self._adapter_label)
        status_layout.addStretch()

        layout.addWidget(status_frame)

        # ── Toggles group ────────────────────────────────────────────────────
        group = QGroupBox("Wi-Fi Settings")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(4)

        for key, label, badge, tooltip in self._TOGGLES:
            row = _ToggleRow(key, label, badge, tooltip)
            self._toggle_rows[key] = row
            group_layout.addWidget(row)

        layout.addWidget(group)

        # ── Latency comparison ───────────────────────────────────────────────
        lat_group = QGroupBox("Latency Test")
        lat_layout = QHBoxLayout(lat_group)
        lat_layout.setContentsMargins(12, 8, 12, 8)
        lat_layout.setSpacing(16)

        before_lbl = QLabel("Before:")
        before_lbl.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        self._before_val = QLabel("-- ms")
        self._before_val.setStyleSheet(
            "color: #f44336; font-weight: 600; background: transparent; border: none;"
        )

        arrow = QLabel("→")
        arrow.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")

        after_lbl = QLabel("After:")
        after_lbl.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        self._after_val = QLabel("-- ms")
        self._after_val.setStyleSheet(
            "color: #4caf50; font-weight: 600; background: transparent; border: none;"
        )

        self._test_btn = QPushButton("Test Latency")
        self._test_btn.setFixedWidth(120)

        lat_layout.addWidget(before_lbl)
        lat_layout.addWidget(self._before_val)
        lat_layout.addWidget(arrow)
        lat_layout.addWidget(after_lbl)
        lat_layout.addWidget(self._after_val)
        lat_layout.addStretch()
        lat_layout.addWidget(self._test_btn)

        layout.addWidget(lat_group)

        # ── Action buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._apply_btn = QPushButton("Apply All")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setMinimumHeight(40)
        self._apply_btn.setMinimumWidth(160)
        self._apply_btn.clicked.connect(self._on_apply)

        self._restore_btn = QPushButton("Restore Defaults")
        self._restore_btn.setObjectName("dangerButton")
        self._restore_btn.setMinimumHeight(40)
        self._restore_btn.clicked.connect(self._on_restore)

        btn_row.addStretch()
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(self._apply_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

    # ---------------------------------------------------------- Internals ------

    def _on_apply(self) -> None:
        self.settings_applied.emit(self.get_settings())

    def _on_restore(self) -> None:
        defaults = {key: False for key in self._toggle_rows}
        self.set_settings(defaults)
        self.settings_restored.emit()

    # ---------------------------------------------------------- Public API ------

    def get_settings(self) -> dict:
        """Return current toggle states as {key: bool}."""
        return {key: row.switch.isChecked() for key, row in self._toggle_rows.items()}

    def set_settings(self, settings: dict) -> None:
        """Apply a dict of {key: bool} to the toggles."""
        for key, row in self._toggle_rows.items():
            if key in settings:
                row.switch.setChecked(bool(settings[key]))

    def set_current_band(self, band: str) -> None:
        self._band_label.setText(f"Current Band: {band}")

    def set_latency_before(self, ms: float) -> None:
        self._before_val.setText(f"{ms:.1f} ms")

    def set_latency_after(self, ms: float) -> None:
        self._after_val.setText(f"{ms:.1f} ms")

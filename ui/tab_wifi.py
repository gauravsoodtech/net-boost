"""
ui/tab_wifi.py
Wi-Fi Optimizer tab — toggle switches for Intel AX211 6E adapter settings.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QGroupBox, QFrame,
    QScrollArea, QSizePolicy, QSpacerItem,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from .widgets.toggle_row import ToggleRow as _ToggleRow


# ── Wi-Fi Tab ─────────────────────────────────────────────────────────────────

class TabWifi(QWidget):
    """
    Wi-Fi Optimizer tab.

    Signals
    -------
    settings_applied(dict)  — emitted when user clicks "Apply All"
    settings_restored()     — emitted when user clicks "Restore Defaults"
    """

    settings_applied      = pyqtSignal(dict)
    settings_restored     = pyqtSignal()
    latency_test_requested = pyqtSignal()

    # Ordered list of (key, label, badge, tooltip)
    _TOGGLES = [
        ("disable_lso",            "Disable Large Send Offload (LSO)",   "CRITICAL", "Stops NIC from batching outgoing packets — biggest single fix for in-game ping spikes"),
        ("disable_interrupt_mod",  "Disable Interrupt Moderation",       "", "Forces NIC to deliver every packet immediately — reduces jitter"),
        ("disable_power_saving",   "Disable Power Saving",               "CRITICAL", ""),
        ("minimize_roaming",       "Minimize Roaming Aggressiveness",    "", ""),
        ("max_tx_power",           "Maximum TX Power",                   "", ""),
        ("disable_bss_scan",       "Disable Background BSS Scanning",    "", ""),
        ("prefer_6ghz",            "Prefer 6 GHz Band",                  "", ""),
        ("throughput_booster",     "Throughput Booster",                 "", ""),
        ("disable_mimo_power_save","Disable MIMO Power Saving",          "", ""),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle_rows: dict[str, _ToggleRow] = {}
        self._before_set = False
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
        self._test_btn.clicked.connect(self._on_test_latency)

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

        # Default all toggles to ON
        self.set_settings({key: True for key in self._toggle_rows})

    # ---------------------------------------------------------- Internals ------

    def _on_apply(self) -> None:
        self.settings_applied.emit(self.get_settings())

    def _on_restore(self) -> None:
        self.settings_restored.emit()
        self.set_settings({key: True for key in self._toggle_rows})

    def _on_test_latency(self) -> None:
        self._test_btn.setEnabled(False)
        self._test_btn.setText("Testing...")
        self.latency_test_requested.emit()

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

    def on_latency_result(self, ms: float) -> None:
        if not self._before_set:
            self.set_latency_before(ms)
            self._before_set = True
        else:
            self.set_latency_after(ms)
            self._before_set = False
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test Latency")

    def on_latency_error(self) -> None:
        self._test_btn.setEnabled(True)
        self._test_btn.setText("Test Latency")

    def mark_applied(self, settings: dict) -> None:
        """Show ● Active badge on each toggle that was ON when Apply was clicked."""
        for key, row in self._toggle_rows.items():
            row.set_applied(bool(settings.get(key)))

    def clear_applied(self) -> None:
        """Remove all Active badges (called on Restore Defaults)."""
        for row in self._toggle_rows.values():
            row.set_applied(False)

    def show_apply_success(self) -> None:
        self._apply_btn.setObjectName("successButton")
        self._apply_btn.setText("\u2713 Applied!")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
        QTimer.singleShot(2500, self._reset_apply_btn)

    def show_apply_error(self) -> None:
        self._apply_btn.setObjectName("dangerButton")
        self._apply_btn.setText("\u2717 Error")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
        QTimer.singleShot(2500, self._reset_apply_btn)

    def _reset_apply_btn(self) -> None:
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setText("Apply All")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)

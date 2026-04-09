"""
ui/tab_optimizer.py
Network Optimizer tab — TCP, DNS, services, and RAM optimiser.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QFrame,
    QScrollArea, QComboBox, QLineEdit, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from .widgets.toggle_row import ToggleRow as _ToggleRow


# ── Network Optimizer Tab ─────────────────────────────────────────────────────

class TabOptimizer(QWidget):
    """
    Network Optimizer tab.

    Signals
    -------
    settings_applied(dict)      — emitted on "Apply All Optimizations"
    ram_optimize_requested()    — emitted when user clicks "Free RAM Now"
    """

    settings_applied      = pyqtSignal(dict)
    settings_restored     = pyqtSignal()
    ram_optimize_requested = pyqtSignal()

    _DNS_PROVIDERS = [
        ("OpenDNS 208.67.222.222", "208.67.222.222", "208.67.220.220"),
        ("Cloudflare 1.1.1.1",     "1.1.1.1",        "1.0.0.1"),
        ("Google 8.8.8.8",         "8.8.8.8",        "8.8.4.4"),
        ("Quad9 9.9.9.9",          "9.9.9.9",        "149.112.112.112"),
        ("Custom",                 "",               ""),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle_rows: dict[str, _ToggleRow] = {}
        self._ram_freed_mb: int = 0
        self._build_ui()

    # --------------------------------------------------------- UI construction --

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Title ────────────────────────────────────────────────────────────
        title = QLabel("Network Optimizer")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # ── TCP Optimization ─────────────────────────────────────────────────
        tcp_group = QGroupBox("TCP Optimization")
        tcp_layout = QVBoxLayout(tcp_group)
        tcp_layout.setSpacing(4)
        for key, label in [
            ("tcp_no_delay",     "Disable Nagle's Algorithm (TCP No-Delay)"),
            ("tcp_ack_freq",     "TCP Acknowledgement Frequency=1"),
            ("tcp_window_scale", "Enable TCP Window Scaling"),
        ]:
            row = _ToggleRow(key, label)
            self._toggle_rows[key] = row
            tcp_layout.addWidget(row)
        layout.addWidget(tcp_group)

        # ── DNS ──────────────────────────────────────────────────────────────
        dns_group = QGroupBox("DNS")
        dns_layout = QVBoxLayout(dns_group)
        dns_layout.setSpacing(8)

        self._dns_toggle = _ToggleRow("switch_dns", "Switch DNS Provider")
        self._toggle_rows["switch_dns"] = self._dns_toggle
        dns_layout.addWidget(self._dns_toggle)

        # Provider selector
        provider_row = QHBoxLayout()
        provider_row.setSpacing(10)
        provider_lbl = QLabel("Provider:")
        provider_lbl.setStyleSheet(
            "color: #9e9e9e; background: transparent; border: none; margin-left: 52px;"
        )
        self._dns_combo = QComboBox()
        for name, _, _ in self._DNS_PROVIDERS:
            self._dns_combo.addItem(name)
        self._dns_combo.setFixedWidth(220)
        self._dns_combo.currentIndexChanged.connect(self._on_dns_provider_changed)

        provider_row.addWidget(provider_lbl)
        provider_row.addWidget(self._dns_combo)
        provider_row.addStretch()
        dns_layout.addLayout(provider_row)

        # Custom DNS fields (hidden by default)
        self._custom_dns_frame = QFrame()
        self._custom_dns_frame.setFrameShape(QFrame.NoFrame)
        custom_layout = QHBoxLayout(self._custom_dns_frame)
        custom_layout.setContentsMargins(52, 0, 0, 0)
        custom_layout.setSpacing(10)

        prim_lbl = QLabel("Primary:")
        prim_lbl.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        self._dns_primary = QLineEdit()
        self._dns_primary.setPlaceholderText("e.g. 1.1.1.1")
        self._dns_primary.setFixedWidth(140)

        sec_lbl = QLabel("Secondary:")
        sec_lbl.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        self._dns_secondary = QLineEdit()
        self._dns_secondary.setPlaceholderText("e.g. 1.0.0.1")
        self._dns_secondary.setFixedWidth(140)

        custom_layout.addWidget(prim_lbl)
        custom_layout.addWidget(self._dns_primary)
        custom_layout.addWidget(sec_lbl)
        custom_layout.addWidget(self._dns_secondary)
        custom_layout.addStretch()

        # Validate custom DNS IPs on text change
        self._dns_primary.textChanged.connect(
            lambda t: self._validate_dns_input(self._dns_primary, t))
        self._dns_secondary.textChanged.connect(
            lambda t: self._validate_dns_input(self._dns_secondary, t))

        self._custom_dns_frame.setVisible(False)
        dns_layout.addWidget(self._custom_dns_frame)

        # DNS speed test
        dns_test_row = QHBoxLayout()
        dns_test_row.setContentsMargins(52, 0, 0, 0)
        dns_test_row.setSpacing(10)
        self._dns_test_btn = QPushButton("Test DNS Speed")
        self._dns_test_btn.setFixedWidth(140)
        self._dns_test_btn.clicked.connect(self._on_dns_test)
        self._dns_test_result = QLabel("")
        self._dns_test_result.setStyleSheet("color: #9e9e9e; background: transparent; border: none;")
        dns_test_row.addWidget(self._dns_test_btn)
        dns_test_row.addWidget(self._dns_test_result)
        dns_test_row.addStretch()
        dns_layout.addLayout(dns_test_row)

        layout.addWidget(dns_group)

        # ── Service Management ────────────────────────────────────────────────
        svc_group = QGroupBox("Service Management")
        svc_layout = QVBoxLayout(svc_group)
        svc_layout.setSpacing(4)
        for key, label in [
            ("pause_windows_update", "Pause Windows Update"),
            ("pause_onedrive",       "Pause OneDrive Sync"),
            ("pause_bits",           "Pause BITS (Background Download)"),
            ("pause_telemetry",      "Pause Windows Telemetry (DiagTrack)"),
        ]:
            row = _ToggleRow(key, label)
            self._toggle_rows[key] = row
            svc_layout.addWidget(row)
        layout.addWidget(svc_group)

        # ── RAM Optimizer ─────────────────────────────────────────────────────
        ram_group = QGroupBox("RAM Optimizer")
        ram_layout = QHBoxLayout(ram_group)
        ram_layout.setContentsMargins(12, 8, 12, 8)
        ram_layout.setSpacing(12)

        self._free_ram_btn = QPushButton("Free RAM Now")
        self._free_ram_btn.setObjectName("accentButton")
        self._free_ram_btn.setFixedWidth(140)
        self._free_ram_btn.clicked.connect(self.ram_optimize_requested.emit)

        self._ram_result_label = QLabel("Freed -- MB")
        self._ram_result_label.setStyleSheet(
            "color: #e040fb; font-weight: 600; background: transparent; border: none;"
        )

        ram_layout.addWidget(self._free_ram_btn)
        ram_layout.addWidget(self._ram_result_label)
        ram_layout.addStretch()
        layout.addWidget(ram_group)

        # ── Apply All button ─────────────────────────────────────────────────
        self._apply_btn = QPushButton("Apply All Optimizations")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setMinimumHeight(44)
        self._apply_btn.setMinimumWidth(220)
        self._apply_btn.clicked.connect(self._on_apply)

        self._restore_btn = QPushButton("Restore Defaults")
        self._restore_btn.setObjectName("dangerButton")
        self._restore_btn.setMinimumHeight(44)
        self._restore_btn.clicked.connect(self._on_restore)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()
        btn_row.addWidget(self._restore_btn)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        # Default all toggles to ON
        self.set_settings({key: True for key in self._toggle_rows})

    # ---------------------------------------------------------- Internals ------

    def _on_restore(self) -> None:
        self.settings_restored.emit()
        self.set_settings({key: True for key in self._toggle_rows})

    @staticmethod
    def _validate_dns_input(field, text: str) -> None:
        """Show red border on invalid IP address."""
        import ipaddress
        text = text.strip()
        if not text:
            field.setStyleSheet("")
            return
        try:
            ipaddress.ip_address(text)
            field.setStyleSheet("border: 1px solid #4caf50;")
        except ValueError:
            field.setStyleSheet("border: 1px solid #f44336;")

    def _on_dns_provider_changed(self, index: int) -> None:
        is_custom = (self._dns_combo.currentText() == "Custom")
        self._custom_dns_frame.setVisible(is_custom)

    def _on_dns_test(self) -> None:
        """Run DNS benchmark in a background thread and display results."""
        self._dns_test_btn.setEnabled(False)
        self._dns_test_btn.setText("Testing...")
        self._dns_test_result.setText("Benchmarking all providers...")
        self._dns_test_result.setStyleSheet("color: #4fc3f7; background: transparent; border: none;")

        from PyQt5.QtCore import QThreadPool, QRunnable, QObject, pyqtSignal

        class _Signals(QObject):
            done = pyqtSignal(list)

        class _Worker(QRunnable):
            def __init__(self, signals):
                super().__init__()
                self.signals = signals
                self.setAutoDelete(True)
            def run(self):
                from core.dns_switcher import benchmark_dns_providers
                results = benchmark_dns_providers()
                self.signals.done.emit(results)

        signals = _Signals()
        signals.done.connect(self._on_dns_test_done)
        QThreadPool.globalInstance().start(_Worker(signals))

    def _on_dns_test_done(self, results: list) -> None:
        self._dns_test_btn.setEnabled(True)
        self._dns_test_btn.setText("Test DNS Speed")
        if not results:
            self._dns_test_result.setText("No results")
            return

        best = results[0]
        parts = [f"{r['provider']}: {r['avg_ms']}ms" for r in results[:4]]
        self._dns_test_result.setText("  |  ".join(parts))
        self._dns_test_result.setStyleSheet("color: #4caf50; background: transparent; border: none;")

        # Auto-select fastest provider in the combo box
        name_map = {
            "opendns": "OpenDNS 208.67.222.222",
            "cloudflare": "Cloudflare 1.1.1.1",
            "google": "Google 8.8.8.8",
            "quad9": "Quad9 9.9.9.9",
        }
        best_display = name_map.get(best["provider"])
        if best_display:
            idx = self._dns_combo.findText(best_display)
            if idx >= 0:
                self._dns_combo.setCurrentIndex(idx)

    def _on_apply(self) -> None:
        self.settings_applied.emit(self.get_settings())

    # ---------------------------------------------------------- Public API ------

    def get_settings(self) -> dict:
        """Return current UI state as a dict."""
        s = {key: row.switch.isChecked() for key, row in self._toggle_rows.items()}
        s["dns_provider"] = self._dns_combo.currentText()
        if self._dns_combo.currentText() == "Custom":
            s["dns_primary"]   = self._dns_primary.text().strip()
            s["dns_secondary"] = self._dns_secondary.text().strip()
        else:
            idx = self._dns_combo.currentIndex()
            _, prim, sec = self._DNS_PROVIDERS[idx]
            s["dns_primary"]   = prim
            s["dns_secondary"] = sec
        return s

    def set_settings(self, settings: dict) -> None:
        """Apply a settings dict to the UI controls."""
        for key, row in self._toggle_rows.items():
            if key in settings:
                row.switch.setChecked(bool(settings[key]))

        if "dns_provider" in settings:
            for i in range(self._dns_combo.count()):
                if self._dns_combo.itemText(i) == settings["dns_provider"]:
                    self._dns_combo.setCurrentIndex(i)
                    break

        if "dns_primary" in settings:
            self._dns_primary.setText(settings["dns_primary"])
        if "dns_secondary" in settings:
            self._dns_secondary.setText(settings["dns_secondary"])

    def set_ram_freed(self, mb: int) -> None:
        """Update the RAM freed result label."""
        self._ram_freed_mb = mb
        if mb >= 1024:
            self._ram_result_label.setText(f"Freed {mb / 1024:.2f} GB")
        else:
            self._ram_result_label.setText(f"Freed {mb} MB")

    def mark_applied(self, settings: dict) -> None:
        """Show ● Active badge on each toggle that was ON when Apply was clicked."""
        for key, row in self._toggle_rows.items():
            row.set_applied(bool(settings.get(key)))

    def clear_applied(self) -> None:
        """Remove all Active badges."""
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
        self._apply_btn.setText("Apply All Optimizations")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)

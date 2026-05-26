"""
Cs2AutoexecDialog — confirmation modal for writing CS2's autoexec.cfg.

Shown by MainWindow when the user clicks the "Write recommended autoexec.cfg"
button on the Settings tab.  The dialog surfaces the resolved CS2 cfg
directory and, when an autoexec.cfg already exists, the timestamped backup
filename that will be created.
"""

from __future__ import annotations

import datetime as _dt

from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class Cs2AutoexecDialog(QDialog):
    """Confirmation modal for the CS2 autoexec writer.

    Parameters
    ----------
    cfg_dir:
        Absolute path to CS2's ``cfg`` directory.
    existing_autoexec:
        True when an ``autoexec.cfg`` is already present and would be
        renamed to ``autoexec.cfg.bak.<timestamp>``.
    parent:
        Parent widget (used for centring + Qt parent chain).
    """

    def __init__(
        self,
        cfg_dir: str,
        *,
        existing_autoexec: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Write CS2 autoexec.cfg")
        self.setMinimumWidth(540)
        self.setModal(True)
        self._cfg_dir = cfg_dir
        self._existing = existing_autoexec
        self._build_ui()

    # ----------------------------------------------------------- internals

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        heading = QLabel("Write NetBoost-recommended CS2 autoexec")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        dir_label = QLabel(f"Target directory:\n{self._cfg_dir}")
        dir_label.setWordWrap(True)
        dir_label.setStyleSheet("color: #c0c0c0;")
        layout.addWidget(dir_label)

        if self._existing:
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_name = f"autoexec.cfg.bak.{stamp}"
            warn = QLabel(
                "An autoexec.cfg already exists in this folder.\n"
                f"It will be preserved as: {backup_name}"
            )
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #ff9800;")
            layout.addWidget(warn)
        else:
            info = QLabel("No existing autoexec.cfg detected — a new one will be created.")
            info.setWordWrap(True)
            info.setStyleSheet("color: #4caf50;")
            layout.addWidget(info)

        contents_label = QLabel(
            "Contents:\n"
            "  rate 786432\n"
            "  mm_dedicated_search_maxping 50\n"
            "  cl_predict 1\n"
            "  cl_interp_ratio 1\n"
            "  net_client_steamdatagram_enable_override 1\n"
            "  host_writeconfig"
        )
        contents_label.setStyleSheet(
            "color: #d0d0d0; background-color: #181820; padding: 8px; border-radius: 4px;"
            "font-family: Consolas, monospace; font-size: 12px;"
        )
        layout.addWidget(contents_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        write_btn = QPushButton("Write autoexec.cfg")
        write_btn.setDefault(True)
        write_btn.clicked.connect(self.accept)
        button_row.addWidget(write_btn)

        layout.addLayout(button_row)

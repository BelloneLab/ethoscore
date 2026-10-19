"""A responsive, single-window installer shared by all supported platforms."""

from __future__ import annotations

from pathlib import Path
import json
import os
import platform
import subprocess
import sys
import tempfile

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                              QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                              QMessageBox, QProgressBar, QPushButton, QTextEdit,
                              QVBoxLayout, QWidget)

from installer.backend import (default_destination, download_release, install_payload,
                               latest_release, launch, read_install)


def bundled_payload() -> Path:
    """Locate the archive embedded by the native setup build."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "installer_payload/application.tar.gz"
    return Path(__file__).resolve().parents[1] / "build/installer_payload/application.tar.gz"


class InstallWorker(QThread):
    """Run network and disk work away from the Qt user interface."""

    message = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, destination: Path, desktop: bool, menu: bool, online: bool):
        """Capture the user's choices before the UI becomes temporarily locked."""
        super().__init__()
        self.destination, self.desktop, self.menu, self.online = destination, desktop, menu, online

    def run(self):
        """Download if requested, then atomically install and report the outcome."""
        try:
            with tempfile.TemporaryDirectory(prefix="ethoscore-download-") as temporary:
                if self.online:
                    self.message.emit("Looking for the latest official application build...")
                    archive = download_release(latest_release(), Path(temporary), self.message.emit)
                else:
                    archive = bundled_payload()
                    if not archive.is_file():
                        raise RuntimeError("This source installer has no bundled application. Choose Download latest, or build a native installer first.")
                state = install_payload(archive, self.destination, self.desktop, self.menu, self.message.emit)
                self.succeeded.emit(state)
        except Exception as error:
            self.failed.emit(str(error))


class InstallerWindow(QMainWindow):
    """Collect install choices, detect existing versions, and show clear progress."""

    def __init__(self):
        """Compose a polished installation form without administrator prompts."""
        super().__init__()
        self.worker = None
        self.setWindowTitle("Ethoscore Setup")
        self.resize(760, 710)
        self.setMinimumSize(650, 650)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111722; color: #edf2fa; font-size: 14px; }
            QLabel#eyebrow { color: #7bdac9; font-size: 12px; font-weight: 700; }
            QLabel#title { font-size: 38px; font-weight: 700; }
            QLabel#subtitle { color: #a7b7cc; font-size: 15px; }
            QLabel#section { font-weight: 650; font-size: 14px; }
            QLabel#state { background: #1b2c38; border: 1px solid #2b4958; border-radius: 9px; padding: 13px; color: #a5e7d8; }
            QLineEdit, QComboBox { background: #1c2635; border: 1px solid #34465b; border-radius: 7px; padding: 10px; }
            QComboBox QAbstractItemView { background: #1c2635; }
            QPushButton { border: 1px solid #3a5068; border-radius: 7px; padding: 11px 18px; background: #233249; font-weight: 600; }
            QPushButton:hover { background: #2c425c; }
            QPushButton#primary { background: #55d8bd; color: #08271f; border: none; min-width: 155px; }
            QPushButton#primary:hover { background: #80ead4; }
            QPushButton:disabled { background: #26313d; color: #647488; }
            QCheckBox { spacing: 10px; padding: 4px 0; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QTextEdit { border: none; background: #0c121c; border-radius: 8px; color: #a7b7cc; font-size: 12px; padding: 7px; }
            QProgressBar { border: none; border-radius: 3px; background: #233249; height: 6px; text-align: center; }
            QProgressBar::chunk { background: #55d8bd; border-radius: 3px; }
        """)
        content = QWidget()
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 30, 34, 25)
        layout.setSpacing(14)
        eyebrow = QLabel("BEHAVIORAL ANNOTATION  /  SETUP")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Ethoscore Setup")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Install Ethoscore. Return here anytime to update your application.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.status = QLabel()
        self.status.setObjectName("state")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        section = QLabel("01   Installation folder")
        section.setObjectName("section")
        layout.addWidget(section)
        path_row = QHBoxLayout()
        self.destination = QLineEdit(str(default_destination()))
        self.destination.textChanged.connect(self.refresh_state)
        self.browse = QPushButton("Browse")
        self.browse.clicked.connect(self.choose_destination)
        path_row.addWidget(self.destination, 1)
        path_row.addWidget(self.browse)
        layout.addLayout(path_row)
        section = QLabel("02   Application version")
        section.setObjectName("section")
        layout.addWidget(section)
        self.source = QComboBox()
        if bundled_payload().is_file():
            self.source.addItem("Install the version bundled with this Setup (offline)", False)
        self.source.addItem("Download the latest official build (internet required)", True)
        layout.addWidget(self.source)
        shortcut_row = QHBoxLayout()
        self.desktop = QCheckBox("Desktop shortcut")
        self.desktop.setChecked(True)
        self.menu = QCheckBox("Start menu shortcut" if sys.platform == "win32" else "Applications shortcut")
        self.menu.setChecked(True)
        shortcut_row.addWidget(self.desktop)
        shortcut_row.addWidget(self.menu)
        shortcut_row.addStretch()
        layout.addLayout(shortcut_row)
        note = QLabel("Installs for your account. Updates keep your videos, annotations, settings, and earlier application versions.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(95)
        self.log.setPlaceholderText("Ready when you are.")
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Launch Ethoscore")
        self.open_button.clicked.connect(self.launch_application)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        self.install_button = QPushButton("Install Ethoscore")
        self.install_button.setObjectName("primary")
        self.install_button.clicked.connect(self.begin_install)
        buttons.addWidget(self.open_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.install_button)
        layout.addLayout(buttons)
        self.refresh_state()

    def refresh_state(self):
        """Reflect the selected folder's installed version and remembered choices."""
        try:
            state = read_install(Path(self.destination.text()).expanduser())
            self.status.setText(f"Installed: {state['version']}. Ready to update or reinstall." if state else "A fresh start. Ethoscore is ready to install for your account.")
            self.install_button.setText("Update / Reinstall" if state else "Install Ethoscore")
            self.open_button.setEnabled(bool(state))
            if state:
                self.desktop.setChecked(state.get("desktop", True))
                self.menu.setChecked(state.get("menu", True))
        except (OSError, ValueError, KeyError) as error:
            self.status.setText(f"Cannot read this installation: {error}")
            self.open_button.setEnabled(False)

    def choose_destination(self):
        """Let the user choose a parent or an existing managed install folder."""
        folder = QFileDialog.getExistingDirectory(self, "Choose installation folder", self.destination.text())
        if folder:
            chosen = Path(folder)
            if not (chosen / ".ethoscore-install.json").exists() and any(chosen.iterdir()):
                chosen /= "Ethoscore"
            self.destination.setText(str(chosen))

    def begin_install(self):
        """Freeze user choices and start installation without blocking repainting."""
        destination = Path(self.destination.text()).expanduser()
        if not self.destination.text().strip() or not destination.is_absolute():
            QMessageBox.warning(self, "Choose a folder", "Choose an absolute installation folder first.")
            return
        self.set_busy(True)
        self.log.clear()
        self.worker = InstallWorker(destination, self.desktop.isChecked(), self.menu.isChecked(), bool(self.source.currentData()))
        self.worker.message.connect(self.log.append)
        self.worker.succeeded.connect(self.install_finished)
        self.worker.failed.connect(self.install_failed)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def set_busy(self, busy: bool):
        """Keep the installation thread alive until all disk changes are complete."""
        for widget in (self.destination, self.browse, self.source, self.desktop, self.menu, self.install_button, self.close_button):
            widget.setEnabled(not busy)
        try:
            installed = read_install(Path(self.destination.text())) is not None
        except (OSError, ValueError):
            installed = False
        self.open_button.setEnabled(not busy and installed)
        self.progress.setRange(0, 0 if busy else 100)
        if not busy:
            self.progress.setValue(100)

    def install_finished(self, state: dict):
        """Show the exact active version and make the launch action available."""
        self.refresh_state()
        self.status.setText(f"Ready to launch. Ethoscore {state['version']} is installed.")
        self.open_button.setEnabled(True)

    def install_failed(self, message: str):
        """Keep error details visible while allowing a corrected retry."""
        self.log.append("Installation stopped: " + message)
        QMessageBox.warning(self, "Installation could not finish", message)

    def launch_application(self):
        """Start the active installed version while leaving Setup open for review."""
        try:
            launch(Path(self.destination.text()).expanduser())
        except Exception as error:
            QMessageBox.warning(self, "Could not launch Ethoscore", str(error))

    def closeEvent(self, event):
        """Prevent closing halfway through an installation transaction."""
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            event.accept()


def main() -> int:
    """Start the graphical installer from either source or a packaged executable."""
    app = QApplication(sys.argv)
    app.setApplicationName("Ethoscore Setup")
    if sys.platform == "win32" and not QFontDatabase.families():
        font_dir = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(font_dir / filename))
    app.setFont(QFont("Segoe UI" if platform.system() == "Windows" else "Sans Serif", 10))
    window = InstallerWindow()
    window.show()
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        # Native CI verifies the actual embedded payload and two transactions.
        report = Path(sys.argv[2]).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ethoscore-setup-smoke-") as temporary:
            destination = Path(temporary) / "installed"
            window.destination.setText(str(destination))
            window.desktop.setChecked(False)
            window.menu.setChecked(False)
            app.processEvents()
            first = install_payload(bundled_payload(), destination, False, False, shortcuts=False)
            sentinel = destination / "user-data/annotations-preserved.csv"
            sentinel.write_text("frame,label\n1,test\n", encoding="utf-8")
            second = install_payload(bundled_payload(), destination, False, False, shortcuts=False)
            if first["directory"] == second["directory"] or sentinel.read_text(encoding="utf-8") != "frame,label\n1,test\n":
                raise RuntimeError("The native installer failed its update/data preservation check.")
            from installer.backend import installed_executable
            app_report = report.with_name(report.stem + "-application.json")
            subprocess.run([str(installed_executable(destination, second)), "--smoke-test", str(app_report)],
                           timeout=120, check=True)
            if json.loads(app_report.read_text(encoding="utf-8"))["status"] != "passed":
                raise RuntimeError("The installed native application failed its startup check.")
            window.refresh_state()
            window.log.append("Native install, update, data preservation, and application startup passed.")
            app.processEvents()
            window.grab().save(str(report.with_suffix(".png")))
            report.write_text(json.dumps({"status": "passed", "version": second["version"],
                                          "checks": ["native setup GUI", "bundled offline install", "repeat install/update",
                                                     "annotation preservation", "installed application startup", "bundled FFmpeg and SVG assets"]}, indent=2), encoding="utf-8")
        window.close()
        return 0
    return app.exec()

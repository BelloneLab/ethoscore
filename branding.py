"""Shared application identity and vector artwork for source and native builds."""

from pathlib import Path
import sys

APPLICATION_ID = "org.bellonelab.ethoscore"


def asset_path(filename: str) -> Path:
    """Resolve artwork independently of the launcher's working directory."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "assets" / "branding" / filename


def set_process_identity(setup: bool = False) -> None:
    """Give Windows a stable taskbar identity before any Qt window is created."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APPLICATION_ID + (".setup" if setup else ""))


def application_icon():
    """Return the shared SVG icon, with native raster fallback for Qt plugins."""
    from PySide6.QtGui import QIcon
    icon = QIcon(str(asset_path("ethoscore-icon.svg")))
    if icon.isNull():
        icon = QIcon(str(asset_path("ethoscore-icon.png")))
    return icon


def configure_application(app, setup: bool = False) -> None:
    """Apply a consistent identity and icon to every top-level application window."""
    app.setApplicationName("Ethoscore Setup" if setup else "Ethoscore")
    app.setOrganizationName("BelloneLab")
    app.setWindowIcon(application_icon())
    app.setDesktopFileName("ethoscore-setup" if setup else "ethoscore")

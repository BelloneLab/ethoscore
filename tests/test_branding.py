"""Check Windows shell identity using real temporary shortcuts and native icons."""

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from branding import APPLICATION_ID, application_icon, asset_path, configure_application
from installer.backend import _windows_shortcut


@unittest.skipUnless(sys.platform == "win32", "Windows shell integration")
class WindowsBrandingTests(unittest.TestCase):
    """Exercise the OS integration that a title-bar-only visual check misses."""

    def test_shortcut_identity_matches_application(self):
        """Read the persisted property through a separate Windows Shell process."""
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "Ethoscore.lnk"
            host = Path(os.environ["SystemRoot"]) / "System32/wscript.exe"
            _windows_shortcut(shortcut, host, Path(directory), "",
                              asset_path("ethoscore-icon.ico"))
            command = (
                "$shell=New-Object -ComObject Shell.Application;"
                "$folder=$shell.Namespace($env:ETHO_TEST_DIRECTORY);"
                "$folder.ParseName('Ethoscore.lnk').ExtendedProperty('System.AppUserModel.ID')"
            )
            output = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                env=dict(os.environ, ETHO_TEST_DIRECTORY=directory), text=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(output.strip(), APPLICATION_ID)

    def test_taskbar_receives_native_small_and_large_icons(self):
        """Ask Windows for the same native icon handles used by the taskbar."""
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        if app.platformName() != "windows":
            self.skipTest("Native Windows Qt platform required")
        configure_application(app)
        icon = application_icon()
        self.assertTrue({16, 32, 48, 256}.issubset(
            {size.width() for size in icon.availableSizes()}))
        window = QWidget()
        try:
            window.setWindowIcon(icon)
            window.show()
            app.processEvents()
            send_message = ctypes.WinDLL("user32").SendMessageW
            send_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_size_t, ctypes.c_ssize_t]
            send_message.restype = ctypes.c_ssize_t
            for icon_kind in (0, 1):  # ICON_SMALL, ICON_BIG
                self.assertNotEqual(
                    send_message(int(window.winId()), 0x007F, icon_kind, 0), 0)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()

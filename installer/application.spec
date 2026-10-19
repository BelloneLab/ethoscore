# -*- mode: python ; coding: utf-8 -*-
"""Lean native application payload, relying on the maintained package hooks."""

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / 'installer/app_entry.py')],
    pathex=[str(root)],
    datas=[(str(root / 'assets'), 'assets')] + collect_data_files('imageio_ffmpeg'),
    hiddenimports=['ethoscore', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets'],
    excludes=['tkinter', 'matplotlib', 'IPython', 'PyQt5', 'PyQt6', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Ethoscore',
          console=False, debug=False, strip=False, upx=False,
          icon=str(root / 'assets/branding/ethoscore-icon.ico') if sys.platform == 'win32' else None)
collection = COLLECT(exe, a.binaries, a.datas, name='Ethoscore', strip=False, upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='Ethoscore.app', bundle_identifier='org.bellonelab.ethoscore',
                 icon=str(root / 'assets/branding/ethoscore-icon.icns'),
                 info_plist={'CFBundleName': 'Ethoscore', 'NSHighResolutionCapable': True})

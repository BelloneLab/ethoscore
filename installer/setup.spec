# -*- mode: python ; coding: utf-8 -*-
"""Self-contained graphical setup with the matching native application payload."""

from pathlib import Path
import sys

root = Path(SPECPATH).parent
a = Analysis([str(root / 'installer/entry.py')], pathex=[str(root)],
             datas=[(str(root / 'build/installer_payload/application.tar.gz'), 'installer_payload')],
             hiddenimports=[], excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'cv2', 'pygame',
                                          'PySide6.QtWebEngineCore', 'PySide6.QtQml'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Ethoscore-Setup',
          console=False, debug=False, strip=False, upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(exe, name='Ethoscore-Setup.app', bundle_identifier='org.bellonelab.ethoscore.setup')

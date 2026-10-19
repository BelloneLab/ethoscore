# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Ethoscore.

Properly collects all hidden imports, Qt plugins, and data files
needed for pandas, numpy, opencv-python, PySide6, and pygame.
"""

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# ---------------------------------------------------------------------------
# Data files: assets (SVGs, images) needed at runtime
# ---------------------------------------------------------------------------
datas = [
    ('assets', 'assets'),
]

# ---------------------------------------------------------------------------
# Hidden imports: modules PyInstaller might miss due to dynamic imports
# ---------------------------------------------------------------------------
hidden_imports = [
    # pandas C-extension submodules
    'pandas._libs',
    'pandas._libs.tslibs',
    'pandas._libs.tslibs.base',
    'pandas._libs.tslibs.conversion',
    'pandas._libs.tslibs.dtypes',
    'pandas._libs.tslibs.fields',
    'pandas._libs.tslibs.nattypes',
    'pandas._libs.tslibs.np_datetime',
    'pandas._libs.tslibs.offsets',
    'pandas._libs.tslibs.parsing',
    'pandas._libs.tslibs.strptime',
    'pandas._libs.tslibs.timestamps',
    'pandas._libs.tslibs.timezones',
    'pandas._libs.tslibs.timedeltas',
    'pandas._libs.window.aggregations',
    'pandas._libs.algos',
    'pandas._libs.hashtable',
    'pandas._libs.index',
    'pandas._libs.internals',
    'pandas._libs.join',
    'pandas._libs.lib',
    'pandas._libs.missing',
    'pandas._libs.nanops',
    'pandas._libs.ops',
    'pandas._libs.parsers',
    'pandas._libs.properties',
    'pandas._libs.reshape',
    'pandas._libs.sas',
    'pandas._libs.scanner',
    'pandas._libs.sparse',
    'pandas._libs.testing',
    'pandas._libs.writers',
    'pandas.io.sas.sas7bdat',
    'pandas.io.sas.sas_xport',
    'pandas.io.sas.sas_constants',
    'pandas.io.clipboard',
    'pandas.io.excel',
    'pandas.io.parsers',
    'pandas.io.sql',
    'pandas.plotting',
    'pandas.compat',
    'pandas.compat.pickle_compat',

    # numpy submodules
    'numpy.core._methods_',
    'numpy.lib.format',
    'numpy.linalg',
    'numpy.random',
    'numpy.fft',
    'numpy.polynomial',

    # opencv
    'cv2.data',
    'cv2.gapi',

    # PySide6
    'PySide6.support',
    'PySide6.QtNetwork',
    'PySide6.QtXml',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',

    # pygame
    'pygame.surface',
    'pygame.display',
    'pygame.joystick',
    'pygame.key',
    'pygame.event',
    'pygame.time',
    'pygame.image',
    'pygame.pixelcopy',

    # annotator_libs submodules (explicit to be safe)
    'annotator_libs.annotation_logic',
    'annotator_libs.gamification_logic',
    'annotator_libs.ui_components',
    'annotator_libs.video_handling',
]

# ---------------------------------------------------------------------------
# Collect all submodules for packages with C extensions
# ---------------------------------------------------------------------------
hidden_imports += collect_submodules('pandas')
hidden_imports += collect_submodules('numpy')
hidden_imports += collect_submodules('cv2')
hidden_imports += collect_submodules('PySide6')
hidden_imports += collect_submodules('pygame')

# ---------------------------------------------------------------------------
# Collect Qt plugins (platforms, image formats, styles, etc.)
# ---------------------------------------------------------------------------
qt_plugins = collect_data_files('PySide6', include_py_files=True)
datas.extend(qt_plugins)

# Collect OpenCV data files (XML haar cascades, etc.)
cv_datas = collect_data_files('cv2', include_py_files=False)
datas.extend(cv_datas)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['ethoscore.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=list(set(hidden_imports)),       # deduplicate
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_qt_plugins.py'],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'IPython',
        'setuptools',
        'pip',
        'Cython',
        'PyQt5',
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ archive (compressed bytecode)
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE – one-file, no console (windowed mode)
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ethoscore',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='assets/branding/ethoscore-icon.ico' if sys.platform == 'win32' else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(exe, name='Ethoscore.app',
                 icon='assets/branding/ethoscore-icon.icns',
                 bundle_identifier='org.bellonelab.ethoscore')

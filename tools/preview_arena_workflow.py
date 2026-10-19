"""Render reproducible arena UI previews using disposable synthetic footage.

Run from the repository root with ``python tools/preview_arena_workflow.py``.
All output goes to tests/artifacts; application preferences are isolated in INI
files. This script never reads a user's recordings or registry preferences.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

# Preview settings are grouped here for quick visual-layout experiments.
OUTPUT_DIR = Path(__file__).resolve().parents[1] / 'tests/artifacts'
VIDEO_WIDTH, VIDEO_HEIGHT = 800, 600
VIDEO_FRAMES, VIDEO_FPS = 36, 30
EDITOR_SIZE = (1180, 760)
ANNOTATOR_SIZE = (1380, 940)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

import ethoscore
from annotator_libs.arena_model import detect_arenas, default_project_dir
from annotator_libs.arena_export import export_arenas, ffmpeg_executable
from annotator_libs.arena_ui import ArenaEditor
from installer.gui import InstallerWindow


def synthetic_frame(index):
    """Draw four clearly divided test arenas with moving animal-shaped markers."""
    image = np.full((VIDEO_HEIGHT, VIDEO_WIDTH, 3), 165, dtype=np.uint8)
    image[:, VIDEO_WIDTH // 2 - 2:VIDEO_WIDTH // 2 + 2] = 35
    image[VIDEO_HEIGHT // 2 - 2:VIDEO_HEIGHT // 2 + 2] = 35
    for arena_index in range(4):
        x = 130 + arena_index % 2 * (VIDEO_WIDTH // 2) + index
        y = 140 + arena_index // 2 * (VIDEO_HEIGHT // 2)
        cv2.ellipse(image, (x, y), (22, 40), 30 * arena_index, 0, 360, (65, 65, 65), -1)
        cv2.circle(image, (x, y - 37), 14, (55, 55, 55), -1)
        cv2.line(image, (x, y + 35), (x + 20, y + 83), (65, 65, 65), 3)
    return image


def main():
    """Render editor, selected-arena annotation, and setup screenshots."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # Windows' offscreen plugin may not enumerate system fonts automatically.
    # Load real installed fonts for QA without bundling proprietary font files.
    if os.name == 'nt':
        for font_file in (Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts').glob('segoeui*.ttf'):
            QFontDatabase.addApplicationFont(str(font_file))
        app.setFont(QFont('Segoe UI', 10))
    with tempfile.TemporaryDirectory(prefix='ethoscore-preview-') as temporary:
        root = Path(temporary)
        source = root / 'four_arenas_demo.mkv'
        encoded = subprocess.run([
            ffmpeg_executable(), '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
            '-s', f'{VIDEO_WIDTH}x{VIDEO_HEIGHT}', '-r', str(VIDEO_FPS), '-i', 'pipe:0',
            '-c:v', 'ffv1', str(source),
        ], input=b''.join(synthetic_frame(i).tobytes() for i in range(VIDEO_FRAMES)),
            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        arenas = detect_arenas(synthetic_frame(0))
        if len(arenas) != 4:
            raise RuntimeError('The synthetic preview must have four detectable arenas.')
        editor = ArenaEditor(source, synthetic_frame(0), arenas)
        editor.resize(*EDITOR_SIZE)
        editor.show()
        app.processEvents()
        editor.table.selectRow(1)
        app.processEvents()
        editor.grab().save(str(OUTPUT_DIR / 'arena-editor-preview.png'))
        editor.reject()
        export_arenas(source, arenas, default_project_dir(source))

        def private_settings(organization, application):
            """Keep visual QA from changing the live user's settings."""
            return QSettings(str(root / f'{organization}_{application}.ini'), QSettings.IniFormat)

        with patch.object(ethoscore, 'QSettings', private_settings):
            window = ethoscore.VideoAnnotator()
            window.resize(*ANNOTATOR_SIZE)
            window.gamepad_timer.stop()
            window.load_video_by_path(str(source))
            window.arena_project.arenas[0].status = 'completed'
            window.arena_project.arenas[1].status = 'ongoing'
            window.arena_project.arenas[3].status = 'completed'
            window.switch_arena(arenas[1].id)
            window.annotations = {frame: ['rearing'] for frame in range(4, 14)}
            window.video_player.annotations = window.annotations
            window.update_timeline_annotations()
            window.video_player.goto_frame(9)
            window.show()
            app.processEvents()
            if window.video_player.preloader:
                window.video_player.preloader.wait()
            app.processEvents()
            window.grab().save(str(OUTPUT_DIR / 'arena-annotator-preview.png'))
            window.close()
            app.processEvents()
        setup = InstallerWindow()
        setup.show()
        app.processEvents()
        setup.grab().save(str(OUTPUT_DIR / 'installer-preview.png'))
        setup.close()
    print(f'UI previews: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()

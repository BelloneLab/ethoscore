"""Run Ethoscore with a writable data directory for packaged installations."""

from pathlib import Path
import os
import runpy
import sys


def smoke_test(report_path: Path) -> None:
    """Check the packaged GUI, resources, and FFmpeg using isolated test settings."""
    import json
    import contextlib
    import subprocess
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QFont
    from branding import configure_application, set_process_identity
    with tempfile.TemporaryDirectory(prefix="ethoscore-native-smoke-") as temporary, contextlib.chdir(temporary):
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, temporary)
        set_process_identity()
        app = QApplication(["Ethoscore smoke test"])
        configure_application(app)
        if sys.platform == "win32":
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"))
            app.setFont(QFont("Segoe UI", 10))
        if not getattr(sys, "frozen", False):
            # Source runs need the same explicit resource base as frozen builds.
            sys._MEIPASS = str(Path(__file__).resolve().parents[1])
        import ethoscore
        import imageio_ffmpeg
        import cv2
        import numpy as np
        from annotator_libs.arena_model import Arena, default_project_dir, detect_arenas
        from annotator_libs.arena_export import export_arenas
        window = ethoscore.VideoAnnotator()
        window.show()
        app.processEvents()
        resource = Path(ethoscore.resource_path("assets/controller-logo.svg"))
        if not resource.is_file():
            raise RuntimeError("The packaged SVG assets could not be found.")
        if window.windowIcon().isNull() or window.windowIcon().pixmap(32, 32).isNull():
            raise RuntimeError("The packaged Ethoscore window icon could not render.")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        completed = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        source = Path(temporary) / "synthetic-two-arenas.avi"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 12, (128, 64))
        if not writer.isOpened():
            raise RuntimeError("The packaged OpenCV video writer could not open.")
        preview = np.full((64, 128, 3), 210, dtype=np.uint8)
        preview[:, 63:66] = 10
        for index in range(12):
            frame = preview.copy()
            cv2.circle(frame, (10 + index * 2, 24), 4, (25, 25, 25), -1)
            cv2.circle(frame, (88 + index, 44), 4, (25, 25, 25), -1)
            writer.write(frame)
        writer.release()
        proposals = detect_arenas(preview)
        if len(proposals) != 2:
            raise RuntimeError("The packaged arena detector failed its two-arena fixture.")
        arenas = [Arena("left", "Left arena", 0, 0, 64, 64), Arena("right", "Right arena", 64, 0, 64, 64)]
        arenas[1].set_polygon([[64, 0], [128, 0], [64, 64]])
        export_arenas(source, arenas, default_project_dir(source))
        masked = cv2.VideoCapture(str(arenas[1].video_path(default_project_dir(source))))
        ok, masked_frame = masked.read()
        masked.release()
        if not ok or int(masked_frame[50, 50].max()) > 5:
            raise RuntimeError("The packaged polygon export did not mask its exterior.")
        if (window.arena_settings_dialog.isVisible()
                or not window.arena_settings_dialog.isAncestorOf(window.arena_selector)):
            raise RuntimeError("Arena management must reside only in its settings dialog.")
        if not window.load_video_by_path(str(source)) or window.active_arena_id != "left":
            raise RuntimeError("The packaged arena project could not reopen its first crop.")
        behavior = window.behavior_buttons.behaviors[0]
        window.annotations[0] = [behavior]
        if not window.switch_arena("right") or any(window.annotations.values()):
            raise RuntimeError("Annotations leaked between packaged arena sessions.")
        if not window.switch_arena("left") or behavior not in window.annotations.get(0, []):
            raise RuntimeError("The packaged arena switch did not restore saved annotations.")
        if window.video_player.total_frames != 12:
            raise RuntimeError("The packaged arena crop changed the decoded frame count.")
        from annotator_libs.bout_grid import GridSource, GridConfig, export_bout_grid
        grid = export_bout_grid(
            [GridSource(str(source), {0: ["test"], 1: ["test"], 5: ["test"]}, "Smoke")],
            "test", Path(temporary) / "grid",
            config=GridConfig(rows=1, columns=2, output_fps=12, page_seconds=1))
        if grid["bouts"] != 2 or grid["frames"] != 12:
            raise RuntimeError("The packaged bout-grid movie failed its complete-bout fixture.")
        if not hasattr(window, "playback_controls"):
            raise RuntimeError("The packaged playback control bar is missing.")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(report_path.with_suffix(".png")))
        report_path.write_text(json.dumps({"status": "passed", "frozen": bool(getattr(sys, "frozen", False)),
                                          "window": window.windowTitle(), "ffmpeg": completed.stdout.splitlines()[0],
                                          "assets": str(resource), "bout_grid": {"bouts": grid["bouts"], "frames": grid["frames"]},
                                          "arenas": {"detected": len(proposals), "exported": 2,
                                          "frames": 12, "polygon_mask": True, "settings_menu_only": True,
                                          "annotation_isolation": True, "switch_restoration": True}}, indent=2), encoding="utf-8")
        window.close()
        app.processEvents()


def main() -> None:
    """Create a per-user working folder and execute the bundled application code."""
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        smoke_test(Path(sys.argv[2]).resolve())
        return
    # Resource files remain in _MEIPASS; writable exports default to user data.
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    current = Path.cwd()
    data = current if current.name == "user-data" and (current.parent / ".ethoscore-install.json").is_file() else base / "Ethoscore/user-data"
    data.mkdir(parents=True, exist_ok=True)
    os.chdir(data)
    # The build spec lists ethoscore as a hidden import so runpy can preserve the
    # existing __main__ startup sequence without importing the module twice.
    runpy.run_module("ethoscore", run_name="__main__")


if __name__ == "__main__":
    main()

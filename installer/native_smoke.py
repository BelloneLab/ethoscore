"""Launch the native setup smoke test after building, on any supported OS."""

from pathlib import Path
import json
import io
import os
import subprocess
import sys
import tarfile
import tempfile


def verify_bundled_race_guards(setup: Path) -> None:
    """Inspect the executable inside Setup itself to reject a stale app snapshot."""
    from PyInstaller.archive.readers import CArchiveReader

    bootloader = CArchiveReader(str(setup))
    entry = next(name for name in bootloader.toc if name.replace("\\", "/") == "installer_payload/application.tar.gz")
    with tarfile.open(fileobj=io.BytesIO(bootloader.extract(entry)), mode="r:gz") as payload:
        metadata = json.load(payload.extractfile("payload.json"))
        with tempfile.TemporaryDirectory(prefix="ethoscore-bytecode-check-") as temporary:
            binary = Path(temporary) / "application.bin"
            with binary.open("wb") as target:
                import shutil
                shutil.copyfileobj(payload.extractfile(metadata["executable"]), target)
            modules = CArchiveReader(str(binary)).open_embedded_archive("PYZ.pyz")
            module = modules.extract("ethoscore")
            annotation_class = next(code for code in module.co_consts if getattr(code, "co_name", None) == "VideoAnnotator")
            load = next(code for code in annotation_class.co_consts if getattr(code, "co_name", None) == "load_video_by_path")
            if "_loading_video" not in load.co_names or "previous_arena_context" not in load.co_varnames:
                raise RuntimeError("Setup contains an outdated application without failed-load/autosave guards.")


def main() -> None:
    """Require the actual installed application and setup transaction reports."""
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / ("Ethoscore-Setup.app/Contents/MacOS/Ethoscore-Setup" if sys.platform == "darwin" else
                                  "Ethoscore-Setup.exe" if sys.platform == "win32" else "Ethoscore-Setup")
    report = root / "tests/artifacts/native-installer.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    verify_bundled_race_guards(executable)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", SDL_AUDIODRIVER="dummy")
    subprocess.run([str(executable), "--smoke-test", str(report)], check=True, timeout=300, env=env)
    outcome = json.loads(report.read_text(encoding="utf-8"))
    if outcome.get("status") != "passed":
        raise RuntimeError("The native installer did not pass its smoke test.")
    outcome["bundled_failed_load_race_guards"] = True
    report.write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    main()

"""Cancelable, frame-preserving FFmpeg crop export with transactional publishing.

The source is decoded once for all crops. Validation decodes each completed
output and the source to confirm exact frame counts before any files publish.
These integrity passes are intentionally included in reported export timings.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading

from annotator_libs.arena_model import ArenaProject, MANIFEST_NAME, atomic_json, source_identity


class ExportCancelled(RuntimeError):
    """Raised after a cancellation request; staged output has been removed."""


def ffmpeg_executable():
    """Prefer the bundled modern FFmpeg, honoring IMAGEIO_FFMPEG_EXE overrides.

    Some system packages predate ``-fps_mode``. The installer includes a known
    modern FFmpeg through imageio-ffmpeg; system lookup is a fallback only.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        executable = shutil.which("ffmpeg")
        if executable:
            return executable
        raise RuntimeError("Install imageio-ffmpeg to enable arena export.") from error


def _check_cancel(cancel):
    """Keep cancellation semantics identical during processing and validation."""
    if cancel is not None and cancel():
        raise ExportCancelled("Arena export was cancelled. Existing files were preserved.")


def _publish_file(staged, destination):
    """Atomically publish without replacement on Windows, macOS, and Linux.

    Windows rename refuses replacement and works on NTFS, exFAT, and network
    shares. POSIX rename replaces files, so use an atomic hard link there.
    """
    if os.name == "nt":
        os.rename(staged, destination)
    else:
        os.link(staged, destination)


def _run(arguments, cancel=None, on_frame=None):
    """Run FFmpeg without a console window, polling cancellation every 0.1 s.

    Stderr goes to a temporary file to prevent pipe deadlock. A dedicated reader
    drains progress stdout so a stalled encoder never blocks cancellation.
    """
    _check_cancel(cancel)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen([ffmpeg_executable(), "-nostdin", "-hide_banner", *map(str, arguments)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=errors, creationflags=flags, text=True)
        lines = queue.Queue()

        def read_progress():
            """Drain stdout until EOF, retaining only compact progress text."""
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        output = []
        try:
            while process.poll() is None or reader.is_alive() or not lines.empty():
                _check_cancel(cancel)
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                output.append(line)
                if on_frame and line.startswith("frame="):
                    on_frame(int(line.split("=", 1)[1].strip()))
            process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            reader.join(timeout=3)
            process.stdout.close()
        errors.seek(0)
        diagnostics = errors.read().decode("utf-8", errors="replace")
        if process.returncode:
            raise RuntimeError(f"FFmpeg failed ({process.returncode}):\n{diagnostics[-6000:]}")
        return "".join(output), diagnostics


def probe_video(source, exact_count=False, cancel=None):
    """Read source dimensions and rational frame rate, optionally decoding count.

    FFmpeg's showinfo reports rational stream frame rate directly, avoiding a
    rounded decimal FPS. Exact counts decode the whole video, including VFR.
    """
    _, diagnostics = _run(["-i", source, "-map", "0:v:0", "-vf", "showinfo", "-frames:v", "1",
                           "-an", "-f", "null", "-"], cancel)
    rate = re.search(r"frame_rate:\s*(\d+)\s*/\s*(\d+)", diagnostics)
    size = re.search(r"\bs:(\d+)x(\d+)", diagnostics)
    if not rate or not size or int(rate[2]) == 0:
        raise ValueError("Cannot determine video dimensions and rational frame rate.")
    fps = Fraction(int(rate[1]), int(rate[2]))
    metadata = {"width": int(size[1]), "height": int(size[2]),
                "fps_num": fps.numerator, "fps_den": fps.denominator}
    if exact_count:
        output, _ = _run(["-v", "error", "-i", source, "-map", "0:v:0", "-an",
                          "-fps_mode", "passthrough", "-progress", "pipe:1", "-nostats", "-f", "null", "-"], cancel)
        counts = re.findall(r"^frame=(\d+)\s*$", output, flags=re.MULTILINE)
        if not counts or int(counts[-1]) < 1:
            raise ValueError("Video has no decodable frames.")
        metadata["frame_count"] = int(counts[-1])
    return metadata


def export_arenas(source, arenas, project_dir, progress=None, cancel=None, lossless=False):
    """Export independent crops while preserving every decoded source frame.

    ``progress`` receives a float from zero to one. ``cancel`` is a callable
    returning True when cancellation is requested. Re-running refuses to replace
    any existing crop, metadata, or annotation. The caller can reuse completed
    exports rather than invoking this function again.

    Matroska plus H.264 4:4:4 supports odd rectangle dimensions. Normal exports
    use CRF 18; ``lossless=True`` selects CRF 0. No audio or temporal resampling
    is applied. Container timestamps may be quantized to Matroska's time base;
    rational frame rate, frame order, and decoded frame count are retained.
    """
    source = Path(source).resolve(strict=True)
    arenas = list(arenas)
    if not arenas:
        raise ValueError("Select at least one arena to export.")
    project_dir = Path(project_dir).resolve()
    project = ArenaProject.create(source, arenas)
    project_dir.mkdir(parents=True, exist_ok=True)
    original_identity = source_identity(source)
    if (project_dir / MANIFEST_NAME).exists():
        existing = ArenaProject.load(project_dir)
        if Path(existing.source_path).resolve() != source:
            raise ValueError("This project folder belongs to another source video.")
    outputs = {arena.id: arena.video_path(project_dir) for arena in arenas}
    for arena in arenas:
        for path in (outputs[arena.id], arena.folder(project_dir) / "arena.json"):
            if path.exists():
                raise FileExistsError(f"Existing arena output will not be overwritten: {path}")
    source_info = probe_video(source, cancel=cancel)
    _check_cancel(cancel)
    stage = Path(tempfile.mkdtemp(prefix=".arena-export-", dir=project_dir)).resolve()
    published = []
    made_folders = []
    report = progress or (lambda value: None)
    try:
        report(0.0)
        if len(arenas) == 1:
            filters = "[0:v:0]" + f"crop={arenas[0].width}:{arenas[0].height}:{arenas[0].x}:{arenas[0].y}:exact=1[c0]"
        else:
            split = "[0:v:0]split=" + str(len(arenas)) + "".join(f"[s{i}]" for i in range(len(arenas)))
            crops = [f"[s{i}]crop={a.width}:{a.height}:{a.x}:{a.y}:exact=1[c{i}]" for i, a in enumerate(arenas)]
            filters = ";".join([split, *crops])
        arguments = ["-v", "error", "-i", source, "-filter_complex_threads", "1", "-filter_complex", filters,
                     "-progress", "pipe:1", "-nostats"]
        estimated_count = max(1, project.source_metadata.get("frame_count", 1))
        for index, arena in enumerate(arenas):
            # No -r, -t, or fps filter: every crop receives every source frame.
            arguments += ["-map", f"[c{index}]", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                          "-crf", "0" if lossless else "18", "-pix_fmt", "yuv444p", "-threads", "2",
                          "-fps_mode", "passthrough", "-n", stage / f"{arena.id}.mkv"]
        _run(arguments, cancel, lambda frame: report(min(0.7, 0.7 * frame / estimated_count)))
        # Header counts can lie for damaged and variable-frame-rate sources.
        # Decode both sides before publishing and reject truncated outputs.
        source_info = probe_video(source, exact_count=True, cancel=cancel)
        report(0.75)
        for index, arena in enumerate(arenas):
            measured = probe_video(stage / f"{arena.id}.mkv", exact_count=True, cancel=cancel)
            if measured["frame_count"] != source_info["frame_count"]:
                raise RuntimeError(f"Frame count mismatch for {arena.label}; no crops were published.")
            if (measured["width"], measured["height"]) != (arena.width, arena.height):
                raise RuntimeError(f"Crop dimensions changed for {arena.label}.")
            if Fraction(measured["fps_num"], measured["fps_den"]) != Fraction(source_info["fps_num"], source_info["fps_den"]):
                raise RuntimeError(f"Frame rate changed for {arena.label}.")
            report(0.75 + 0.23 * (index + 1) / len(arenas))
        if source_identity(source) != original_identity:
            raise RuntimeError("Source video changed during export.")
        _check_cancel(cancel)
        for arena in arenas:
            folder = arena.folder(project_dir)
            if not folder.exists():
                folder.mkdir()
                made_folders.append(folder)
            destination = outputs[arena.id]
            # Staging and destination reside on the same filesystem. Publishing
            # is atomic and cannot replace a concurrent export's files.
            _publish_file(stage / f"{arena.id}.mkv", destination)
            published.append(destination)
            metadata_path = folder / "arena.json"
            staged_metadata = stage / f"{arena.id}.json"
            from dataclasses import asdict
            atomic_json(staged_metadata, {"arena": asdict(arena), "source": str(source),
                                         "source_identity": original_identity, "video": source_info,
                                         "codec": "libx264", "lossless": bool(lossless)})
            _publish_file(staged_metadata, metadata_path)
            published.append(metadata_path)
        project.source_metadata.update(source_info)
        if not (project_dir / MANIFEST_NAME).exists():
            project.save(project_dir)
            published.append(project_dir / MANIFEST_NAME)
        report(1.0)
        return outputs
    except BaseException:
        # Only remove the exact paths created by this transaction. Annotation
        # CSVs, prior exports, and existing project metadata are never deleted.
        for path in reversed(published):
            path.unlink(missing_ok=True)
        for folder in reversed(made_folders):
            try:
                folder.rmdir()
            except OSError:
                pass
        raise
    finally:
        # stage was created by mkdtemp directly inside the validated project.
        if stage.parent == project_dir and stage.name.startswith(".arena-export-"):
            shutil.rmtree(stage)

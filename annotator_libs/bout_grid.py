"""Export every annotated bout as paginated, independently looping grid tiles.

The layout follows the montage concept used by MAMIR. This implementation
reads ordinary annotated videos, keeps a bounded resized-frame cache, and
publishes a movie and an auditable frame-range manifest together.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
import csv
import math
import os
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from annotator_libs.arena_export import ExportCancelled, ffmpeg_executable


@dataclass(frozen=True)
class GridSource:
    """One source movie with zero-based annotations and a display name."""
    video_path: str | Path
    annotations: Mapping[int, Sequence[str]]
    arena_label: str = ""


@dataclass(frozen=True)
class GridConfig:
    """User-adjustable layout and playback settings; dimensions are pixels."""
    rows: int = 4
    columns: int = 5
    tile_width: int = 176
    tile_height: int = 176
    output_fps: float = 12.0
    page_seconds: float = 4.0
    cache_megabytes: int = 128

    def validate(self):
        """Reject excessive allocations and unsupported encoder geometry."""
        for value, low, high in ((self.rows, 1, 6), (self.columns, 1, 6),
                                 (self.tile_width, 96, 960), (self.tile_height, 72, 720),
                                 (self.cache_megabytes, 1, 512)):
            if not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"Grid setting must be an integer between {low} and {high}.")
        if not math.isfinite(self.output_fps) or not 1 <= self.output_fps <= 60:
            raise ValueError("Output FPS must be between 1 and 60.")
        if not math.isfinite(self.page_seconds) or not 0.1 <= self.page_seconds <= 120:
            raise ValueError("Page duration must be between 0.1 and 120 seconds.")


def extract_bouts(annotations, behavior):
    """Return inclusive zero-based contiguous runs; missing frames split runs."""
    indices = []
    for frame, labels in annotations.items():
        if isinstance(labels, str):
            labels = [labels]
        if behavior in labels:
            if isinstance(frame, bool) or not isinstance(frame, (int, np.integer)) or frame < 0:
                raise ValueError("Annotation frame indices must be nonnegative integers.")
            indices.append(int(frame))
    indices = sorted(set(indices))
    bouts = []
    for frame in indices:
        if bouts and frame == bouts[-1][1] + 1:
            bouts[-1] = (bouts[-1][0], frame)
        else:
            bouts.append((frame, frame))
    return bouts


def _cancelled(cancel):
    """Check cancellation before expensive work and before publication."""
    if cancel and cancel():
        raise ExportCancelled("Grid movie export cancelled; no output was published.")


def _text(image, text, xy, max_width, color=(225, 232, 239), scale=0.45):
    """Fit readable ASCII text to its cell without spilling into neighbours."""
    text = str(text).encode("ascii", "replace").decode("ascii")
    measured = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]
    if measured > max_width:
        scale = max(0.28, scale * max_width / measured)
    while text and cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > max_width:
        text = text[:-1]
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


class _Reader:
    """Decode on demand with a byte-limited LRU of aspect-preserving tiles."""
    def __init__(self, sources, config):
        self.sources, self.config = sources, config
        self.captures, self.positions = {}, {}
        self.cache, self.cache_bytes = OrderedDict(), 0

    def close(self):
        """Release all decoder handles, including on cancellation."""
        for capture in self.captures.values():
            capture.release()
        self.captures.clear()
        self.positions.clear()
        self.cache.clear()
        self.cache_bytes = 0

    def frame(self, source_index, frame_index, stream_id=0):
        """Return a letterboxed tile, preserving the source's aspect ratio."""
        key = (source_index, frame_index)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        # Each visible bout gets its own sequential decoder. Sharing one
        # decoder across distant bouts would force a costly keyframe seek for
        # every tile on every output frame. The page bounds decoder count.
        decoder_key = (source_index, stream_id)
        if decoder_key not in self.captures:
            path = str(self.sources[source_index].video_path)
            thread_property = getattr(cv2, "CAP_PROP_N_THREADS", None)
            capture = (cv2.VideoCapture(path, cv2.CAP_FFMPEG, [thread_property, 1])
                       if thread_property is not None else cv2.VideoCapture(path))
            if not capture.isOpened():
                capture.release()
                capture = cv2.VideoCapture(path)
            self.captures[decoder_key] = capture
        capture = self.captures[decoder_key]
        next_frame = self.positions.get(decoder_key)
        if next_frame is not None and 0 < frame_index - next_frame <= 32:
            # At lower montage FPS, decode and discard a few intervening
            # frames instead of seeking backwards to a codec keyframe.
            for _ in range(frame_index - next_frame):
                if not capture.grab():
                    raise ValueError("Cannot advance the source decoder.")
        elif next_frame != frame_index:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, image = capture.read()
        if not ok:
            raise ValueError(f"Cannot decode frame {frame_index + 1} of {self.sources[source_index].video_path}")
        self.positions[decoder_key] = frame_index + 1
        width, height = self.config.tile_width, self.config.tile_height
        ratio = min(width / image.shape[1], height / image.shape[0])
        resized = cv2.resize(image, (max(1, round(image.shape[1] * ratio)),
                                    max(1, round(image.shape[0] * ratio))), interpolation=cv2.INTER_AREA)
        tile = np.full((height, width, 3), (15, 19, 24), dtype=np.uint8)
        y, x = (height - resized.shape[0]) // 2, (width - resized.shape[1]) // 2
        tile[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        budget = self.config.cache_megabytes * 1024 * 1024
        while self.cache and self.cache_bytes + tile.nbytes > budget:
            self.cache_bytes -= self.cache.popitem(last=False)[1].nbytes
        if tile.nbytes <= budget:
            self.cache[key] = tile
            self.cache_bytes += tile.nbytes
        return tile


def export_bout_grid(sources, behavior, destination, config=None, progress=None, cancel=None):
    """Write ``bout_grid.mp4`` and ``bouts.csv`` in a new output directory.

    Every bout is included, in source order then start-frame order. Tiles play
    at the source's nominal FPS and loop independently. Each page lasts at least
    page_seconds and extends to show its longest bout in full. Audio is omitted. Source videos and
    annotations are never modified. Progress is a fraction from zero to one.
    """
    config = config or GridConfig()
    config.validate()
    sources = list(sources)
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError(f"Choose a new output folder: {destination}")
    if not behavior or not sources:
        raise ValueError("Choose a behavior and at least one video.")
    _cancelled(cancel)
    records = []
    capacity = config.rows * config.columns
    page_frames = max(1, round(config.page_seconds * config.output_fps))
    page_duration = page_frames / config.output_fps
    for source_index, source in enumerate(sources):
        _cancelled(cancel)
        bouts = extract_bouts(source.annotations, behavior)
        if not bouts:
            continue
        capture = cv2.VideoCapture(str(source.video_path))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if not capture.isOpened() or not math.isfinite(fps) or fps <= 0:
                raise ValueError(f"Cannot read video timing: {source.video_path}")
        finally:
            capture.release()
        for local_index, (start, end) in enumerate(bouts):
            if end >= count:
                raise ValueError(f"Annotation extends past video: {source.video_path}, frame {end + 1}")
            index = len(records)
            records.append(dict(behavior=behavior, source_index=source_index,
                                source_video=str(Path(source.video_path).absolute()),
                                arena=source.arena_label or Path(source.video_path).stem,
                                bout=local_index + 1, start_frame=start + 1, end_frame=end + 1,
                                source_fps=fps, duration_s=(end - start + 1) / fps,
                                page=index // capacity + 1, tile=index % capacity + 1,
                                page_duration_s=page_duration,
                                full_bout_visible=(end - start + 1) / fps <= page_duration))
    if not records:
        raise ValueError(f"No annotated bouts found for {behavior}.")
    pages = math.ceil(len(records) / capacity)
    page_lengths = [max(page_frames, math.ceil(max(r["duration_s"] for r in records[p * capacity:(p + 1) * capacity]) * config.output_fps)) for p in range(pages)]
    for record in records:
        record["page_duration_s"] = page_lengths[record["page"] - 1] / config.output_fps
        record["full_bout_visible"] = True
    total_frames = sum(page_lengths)
    written = 0
    gap, header, caption = 10, 52, 48
    width = gap + config.columns * (config.tile_width + gap)
    height = header + gap + config.rows * (config.tile_height + caption + gap)
    width += width % 2
    height += height % 2
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ethoscore-grid-", dir=destination.parent))
    reader = _Reader(sources, config)
    process = None
    try:
        with tempfile.TemporaryFile() as errors:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen([ffmpeg_executable(), "-hide_banner", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
                "-r", str(config.output_fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(stage / "bout_grid.mp4")],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors, creationflags=flags)
            for page in range(pages):
                # Release prior-page decoders and tiles so handles never grow
                # with the total number of arenas in a large project.
                reader.close()
                page_records = records[page * capacity:(page + 1) * capacity]
                for phase in range(page_lengths[page]):
                    _cancelled(cancel)
                    canvas = np.full((height, width, 3), (25, 21, 18), np.uint8)
                    _text(canvas, f"{behavior}  |  Page {page + 1}/{pages}  |  {len(records)} bouts",
                          (14, 32), width - 28, scale=0.65)
                    for position, record in enumerate(page_records):
                        _cancelled(cancel)
                        row, column = divmod(position, config.columns)
                        x, y = gap + column * (config.tile_width + gap), header + gap + row * (config.tile_height + caption + gap)
                        start, end = record["start_frame"] - 1, record["end_frame"] - 1
                        offset = int(math.floor(phase * record["source_fps"] / config.output_fps + 1e-9)) % (end - start + 1)
                        canvas[y:y + config.tile_height, x:x + config.tile_width] = reader.frame(record["source_index"], start + offset, start)
                        cv2.rectangle(canvas, (x, y), (x + config.tile_width - 1, y + config.tile_height - 1), (170, 207, 90), 1)
                        _text(canvas, f'Bout {record["bout"]} | {record["arena"]}', (x + 5, y + config.tile_height + 18), config.tile_width - 10)
                        _text(canvas, f'Frames {start + 1}-{end + 1} | {record["duration_s"]:.2f}s',
                              (x + 5, y + config.tile_height + 37), config.tile_width - 10, (160, 170, 180), 0.38)
                    process.stdin.write(canvas.tobytes())
                    if progress:
                        progress((written + 1) / (total_frames + 1))
                    written += 1
            process.stdin.close()
            while process.poll() is None:
                _cancelled(cancel)
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            errors.seek(0)
            if process.returncode:
                raise RuntimeError(errors.read().decode("utf-8", errors="replace")[-4000:])
        # Verify actual decoding, not only container frame-count metadata.
        verification = cv2.VideoCapture(str(stage / "bout_grid.mp4"))
        decoded = 0
        try:
            while True:
                _cancelled(cancel)
                ok, frame = verification.read()
                if not ok:
                    break
                if frame.shape[:2] != (height, width):
                    raise RuntimeError("Grid movie has unexpected dimensions.")
                decoded += 1
        finally:
            verification.release()
        if decoded != total_frames:
            raise RuntimeError(f"Grid export decoded {decoded} frames; expected {total_frames}.")
        with (stage / "bouts.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        _cancelled(cancel)
        if destination.exists():
            raise FileExistsError(f"Output folder was created during export: {destination}")
        os.rename(stage, destination)
        if progress:
            progress(1.0)
        return dict(output=str(destination / "bout_grid.mp4"), manifest=str(destination / "bouts.csv"),
                    bouts=len(records), pages=pages, frames=total_frames, fps=config.output_fps,
                    duration_s=total_frames / config.output_fps)
    finally:
        reader.close()
        if process and process.poll() is None:
            process.kill()
            process.wait()
        if process and process.stdin and not process.stdin.closed:
            try:
                process.stdin.close()
            except BrokenPipeError:
                # Do not replace an earlier cancellation/encoder error with a
                # secondary flush failure after terminating the subprocess.
                pass
        if stage.exists():
            shutil.rmtree(stage)

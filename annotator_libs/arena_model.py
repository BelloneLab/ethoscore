"""Validated arena geometry, source identity, detection, and project persistence.

Coordinates always refer to the full resolution source image. Rectangles use
integer half-open pixel bounds: ``frame[y:y + height, x:x + width]``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json
import os
import re
import tempfile

import cv2
import numpy as np


STATUSES = ("unlabeled", "ongoing", "completed")
STATUS_COLORS = {"unlabeled": "#778294", "ongoing": "#f5b942", "completed": "#36c993"}
MANIFEST_NAME = "arenas.json"


@dataclass
class Arena:
    """A named crop and its independent annotation progress."""

    id: str
    label: str
    x: int
    y: int
    width: int
    height: int
    status: str = "unlabeled"
    last_frame: int = 0

    def __post_init__(self):
        """Reject unsafe folder names and malformed source coordinates."""
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", self.id):
            raise ValueError("Arena ID must be a safe alphanumeric folder name.")
        if self.id.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError("Arena ID is reserved by Windows.")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Every arena needs a nonempty label.")
        if any(type(v) is not int for v in (self.x, self.y, self.width, self.height, self.last_frame)):
            raise ValueError("Arena coordinates and last frame must be integers.")
        if min(self.x, self.y, self.last_frame) < 0 or min(self.width, self.height) < 2:
            raise ValueError("Arena bounds must be positive and at least 2 pixels wide and tall.")
        if self.status not in STATUSES:
            raise ValueError(f"Unknown arena status: {self.status}")

    @property
    def rect(self):
        """Return the source-space rectangle as x, y, width, height."""
        return self.x, self.y, self.width, self.height

    def validate_bounds(self, width, height):
        """Reject rectangles extending beyond the original video."""
        self.__post_init__()
        if self.x + self.width > width or self.y + self.height > height:
            raise ValueError(f"Arena {self.label!r} extends outside the source video.")

    def folder(self, project_dir):
        """Resolve the arena folder, rejecting symlink escapes."""
        self.__post_init__()
        base = Path(project_dir).resolve()
        folder = (base / self.id).resolve()
        if folder.parent != base:
            raise ValueError("Arena folder escapes its project directory.")
        return folder

    def video_path(self, project_dir):
        """Return the crop path used by the player."""
        return self.folder(project_dir) / "video.mkv"

    def annotations_path(self, project_dir):
        """Match the application's existing same-stem CSV convention."""
        return self.folder(project_dir) / "video.csv"


def default_project_dir(source):
    """Keep a video's arena project in a dedicated neighboring folder."""
    source = Path(source).resolve()
    return source.parent / f"{source.stem}_arenas"


def source_identity(source):
    """Fingerprint the source without modifying it or scanning entire movies.

    Size, modification time, and a hash of the first and last 1 MiB detect the
    common accidental replacement cases. This is not a whole-file content hash.
    """
    source = Path(source).resolve(strict=True)
    stat = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            handle.seek(max(0, stat.st_size - 1024 * 1024))
            digest.update(handle.read(1024 * 1024))
    return {"path": str(source), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sample_sha256": digest.hexdigest()}


def atomic_json(path, data):
    """Write complete JSON before replacing a manifest in the same directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".arena-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class ArenaProject:
    """Versioned source identity and ordered arena metadata."""

    source_path: str
    arenas: list[Arena]
    source_metadata: dict = field(default_factory=dict)
    schema_version: int = 1

    @classmethod
    def create(cls, source, arenas):
        """Capture original source identity and validate geometry immediately."""
        source = str(Path(source).resolve(strict=True))
        capture = cv2.VideoCapture(source)
        try:
            if not capture.isOpened():
                raise ValueError("Cannot open the source video.")
            metadata = source_identity(source)
            metadata.update(width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                            frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
                            fps=float(capture.get(cv2.CAP_PROP_FPS)))
        finally:
            capture.release()
        project = cls(source, list(arenas), metadata)
        project.validate()
        return project

    def validate(self):
        """Reject duplicate identifiers, malformed metadata, and invalid bounds."""
        if self.schema_version != 1:
            raise ValueError("Unsupported arena project version.")
        if len({arena.id.casefold() for arena in self.arenas}) != len(self.arenas):
            raise ValueError("Arena IDs must be unique, including letter case.")
        width, height = self.source_metadata.get("width"), self.source_metadata.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or min(width, height) < 2:
            raise ValueError("Source dimensions are missing or invalid.")
        for arena in self.arenas:
            arena.validate_bounds(width, height)

    def save(self, project_dir=None):
        """Atomically persist metadata; never touch videos or annotation CSVs."""
        self.validate()
        project_dir = Path(project_dir or default_project_dir(self.source_path)).resolve()
        if project_dir == Path(self.source_path).resolve():
            raise ValueError("The project folder cannot replace the source video.")
        for arena in self.arenas:
            arena.folder(project_dir)
        atomic_json(project_dir / MANIFEST_NAME, asdict(self))
        return project_dir

    @classmethod
    def load(cls, project_dir, verify_source=True):
        """Load a project and detect source replacements before annotations mix."""
        project_dir = Path(project_dir).resolve()
        with (project_dir / MANIFEST_NAME).open(encoding="utf-8") as handle:
            data = json.load(handle)
        data["arenas"] = [Arena(**item) for item in data["arenas"]]
        project = cls(**data)
        project.validate()
        for arena in project.arenas:
            arena.folder(project_dir)
        if verify_source:
            identity = source_identity(project.source_path)
            if any(identity[key] != project.source_metadata.get(key) for key in ("size_bytes", "mtime_ns", "sample_sha256")):
                raise ValueError("The source video changed since this project was created.")
        return project


def sample_video_frame(source, samples=7):
    """Return a temporal-median BGR image to suppress moving animals.

    Run in a background worker for long or remote movies. The source is opened
    read-only; at most seven sample images are retained by default.
    """
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError("Cannot open source video.")
        total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        frames = []
        for index in np.linspace(0, total - 1, max(1, int(samples)), dtype=int):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ok, frame = capture.read()
            if ok:
                frames.append(frame)
        if not frames:
            raise ValueError("No readable video frames.")
        return np.median(np.stack(frames), axis=0).astype(np.uint8)
    finally:
        capture.release()


def grid_arenas(width, height, rows=2, columns=2):
    """Provide an explicit, user-requested grid fallback without lost pixels."""
    if min(rows, columns) < 1 or width // columns < 2 or height // rows < 2:
        raise ValueError("Grid cells must be at least 2 pixels wide and tall.")
    xs = np.linspace(0, width, columns + 1, dtype=int)
    ys = np.linspace(0, height, rows + 1, dtype=int)
    return [Arena(f"arena_{r * columns + c + 1}", f"Arena {r * columns + c + 1}",
                  int(xs[c]), int(ys[r]), int(xs[c + 1] - xs[c]), int(ys[r + 1] - ys[r]))
            for r in range(rows) for c in range(columns)]


def _divider_positions(gray, vertical):
    """Find dark or light narrow dividers, avoiding broad illumination steps."""
    image = gray if vertical else gray.T
    height, width = image.shape
    if width < 32 or height < 32:
        return []
    # Compare each line against nearby background; a divider must contrast
    # for most of its length, unlike an animal or a local marking.
    radius = max(5, int(width * 0.018))
    blurred = cv2.GaussianBlur(image, (0, 0), 0.8)
    left = np.roll(blurred, radius, axis=1)
    right = np.roll(blurred, -radius, axis=1)
    # Require consistent contrast on both sides. A single illumination step at
    # an outer wall can otherwise masquerade as an additional interior divider.
    contrast = np.maximum(np.minimum(left, right) - blurred,
                          blurred - np.maximum(left, right))
    usable = contrast[int(height * 0.08):int(height * 0.92)]
    strength = np.mean(usable > 8, axis=0)
    candidates = np.flatnonzero(strength > 0.66)
    candidates = candidates[(candidates > width * 0.14) & (candidates < width * 0.86)]
    if not len(candidates):
        return []
    groups = np.split(candidates, np.flatnonzero(np.diff(candidates) > max(2, radius // 2)) + 1)
    return [int(group[np.argmax(strength[group])]) for group in groups
            if len(group) < width * 0.045][:7]


def _floor_interval(profile):
    """Trim sustained exterior bands whose tone differs from the central floor.

    Median line profiles suppress animals and small marks. Each edge is tested
    independently, so a bright floor may have only one dark outer wall. Requiring
    a localized transition avoids treating gradual lighting falloff as a wall.
    The signed comparison is invariant under intensity inversion.
    """
    size = len(profile)
    if size < 32:
        return 0, size
    smooth = cv2.GaussianBlur(profile.reshape(1, -1).astype(np.float32),
                              (0, 0), max(0.8, size * 0.003)).ravel()
    center = float(np.median(smooth[int(size * 0.35):int(size * 0.65)]))

    def boundary(values):
        """Locate the first sustained floor transition from one exterior edge."""
        edge = float(np.median(values[:max(3, int(size * 0.08))]))
        difference = center - edge
        if abs(difference) < 18:
            return 0
        # Normalize to the observed background/floor contrast, for either polarity.
        membership = (values - edge) / difference
        # A wall can contain several tones (black margin, shadow, then floor).
        # Seek the floor plateau rather than stopping at the first gray ledge.
        candidates = np.flatnonzero(membership[:int(size * 0.45)] >= 0.85)
        if not len(candidates):
            return 0
        position = int(candidates[0])
        radius = max(2, int(size * 0.015))
        if position < max(2, int(size * 0.025)):
            return 0
        before = np.median(membership[max(0, position - 2 * radius):position - radius + 1])
        after = np.median(membership[position + radius:position + 2 * radius + 1])
        if after - before < 0.15:
            return 0
        return position

    return boundary(smooth), size - boundary(smooth[::-1])


def _trim_arena_floor(gray, left, top, right, bottom):
    """Refine a divider cell to its floor, retaining unambiguous source pixels."""
    cell = gray[top:bottom, left:right]
    height, width = cell.shape
    # Ignore cell-edge separators while estimating the dominant floor profiles.
    xprofile = np.median(cell[int(height * 0.15):max(int(height * 0.85), 1)], axis=0)
    x0, x1 = _floor_interval(xprofile)
    # Interior dividers are already established; trim only exterior cell sides.
    x0 = x0 if left == 0 else 0
    x1 = x1 if right == gray.shape[1] else width
    inner_width = x1 - x0
    yprofile = np.median(cell[:, x0 + int(inner_width * 0.15):x0 + max(int(inner_width * 0.85), 1)], axis=1)
    y0, y1 = _floor_interval(yprofile)
    y0 = y0 if top == 0 else 0
    y1 = y1 if bottom == gray.shape[0] else height
    return left + x0, top + y0, left + x1, top + y1


def detect_arenas(frame):
    """Suggest rectangles only when sustained divider evidence is present.

    Contrasting exterior walls are trimmed independently for each arena, with
    equal treatment of light and dark floors. Automatic proposals remain editable.
    Blank images and animal-sized contours
    deliberately return an empty list, allowing the UI to offer a manual grid.
    """
    if frame is None or frame.ndim not in (2, 3):
        raise ValueError("Expected a grayscale or BGR image.")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gray = gray.astype(np.float32)
    height, width = gray.shape
    xs, ys = _divider_positions(gray, True), _divider_positions(gray, False)
    if not xs and not ys:
        return []
    xs, ys = [0, *xs, width], [0, *ys, height]
    # Reject close proposals: they usually describe two edges of one divider.
    if min(np.diff(xs)) < width * 0.12 or min(np.diff(ys)) < height * 0.12:
        return []
    arenas = []
    for top, bottom in zip(ys, ys[1:]):
        for left, right in zip(xs, xs[1:]):
            index = len(arenas) + 1
            x0, y0, x1, y1 = _trim_arena_floor(gray, left, top, right, bottom)
            arenas.append(Arena(f"arena_{index}", f"Arena {index}", x0, y0, x1 - x0, y1 - y0))
    return arenas

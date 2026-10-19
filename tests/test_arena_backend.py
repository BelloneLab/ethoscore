"""End-to-end arena integrity checks using disposable generated movies.

Run with ``python -m unittest discover -s tests -p test_arena_backend.py -v``.
No recording, metadata, or annotation from a user is opened or modified.
"""

from pathlib import Path
import subprocess
import tempfile
import csv
import time
import unittest

import cv2
import numpy as np

from annotator_libs.arena_model import Arena, ArenaProject, detect_arenas, grid_arenas, source_identity
from annotator_libs.arena_export import ExportCancelled, export_arenas, ffmpeg_executable, probe_video


class ArenaTests(unittest.TestCase):
    """Exercise coordinate, manifest, cancellation, and frame integrity rules."""

    def setUp(self):
        """Give each check a private source and export directory."""
        self.temporary = tempfile.TemporaryDirectory(prefix="ethoscore-arena-test-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.mkv"
        self.frames = []
        for frame_index in range(17):
            image = np.zeros((72, 96, 3), np.uint8)
            image[:] = (30, 100, 170)
            image[:, :48] = (150, 50, 30)
            image[frame_index:frame_index + 5, :] = (210, 210, 210)
            self.frames.append(image)
        flags = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0
        result = subprocess.run([ffmpeg_executable(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                 "-s", "96x72", "-r", "30000/1001", "-i", "pipe:0", "-c:v", "ffv1", str(self.source)],
                                input=b"".join(frame.tobytes() for frame in self.frames), capture_output=True, creationflags=flags)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())

    def tearDown(self):
        """Remove only the disposable test directory."""
        self.temporary.cleanup()

    def test_detection_and_no_evidence(self):
        """A long cross supports four crops; blank scenes do not."""
        image = np.full((320, 400, 3), 160, np.uint8)
        image[:, 198:202] = 20
        image[158:162] = 20
        self.assertEqual(len(detect_arenas(image)), 4)
        self.assertEqual(detect_arenas(np.full_like(image, 100)), [])
        # A wide outer illumination step must not create an extra column.
        image[:, :75] = 80
        self.assertEqual(len(detect_arenas(image)), 4)

    def test_manifest_and_traversal(self):
        """Round-trip all progress while rejecting unsafe identifiers."""
        arena = Arena("arena_1", "Mouse A", 1, 2, 31, 35, "ongoing", 11)
        project = ArenaProject.create(self.source, [arena])
        folder = project.save(self.root / "project")
        self.assertEqual(ArenaProject.load(folder).arenas[0], arena)
        for unsafe in ("../source", "/source", "CON", "a/b", "a\\b", ".."):
            with self.assertRaises(ValueError):
                Arena(unsafe, "Bad", 0, 0, 10, 10)
        with self.assertRaises(ValueError):
            ArenaProject.create(self.source, [Arena("a", "A", 80, 0, 30, 20)])
        self.source.touch()
        with self.assertRaises(ValueError):
            ArenaProject.load(folder)

    def test_export_odd_bounds_exact_frames_and_annotation_safety(self):
        """Odd crops keep every frame and do not touch pre-existing CSVs."""
        arenas = [Arena("left", "Left", 1, 3, 35, 33), Arena("right", "Right", 49, 2, 45, 49)]
        folder = self.root / "export"
        (folder / "left").mkdir(parents=True)
        annotations = folder / "left" / "video.csv"
        annotations.write_text("original annotations\n")
        before = source_identity(self.source)
        updates = []
        outputs = export_arenas(self.source, arenas, folder, updates.append, lossless=True)
        self.assertEqual(source_identity(self.source), before)
        self.assertEqual(annotations.read_text(), "original annotations\n")
        self.assertEqual(updates[-1], 1.0)
        for arena in arenas:
            info = probe_video(outputs[arena.id], exact_count=True)
            self.assertEqual(info["frame_count"], len(self.frames))
            self.assertEqual((info["fps_num"], info["fps_den"]), (30000, 1001))
            capture = cv2.VideoCapture(str(outputs[arena.id]))
            for original in self.frames:
                ok, measured = capture.read()
                self.assertTrue(ok)
                expected = original[arena.y:arena.y + arena.height, arena.x:arena.x + arena.width]
                self.assertEqual(measured.shape, expected.shape)
                # H.264 is lossless in YUV; RGB conversion can differ by 2 levels.
                self.assertLessEqual(np.abs(measured.astype(int) - expected.astype(int)).max(), 3)
            self.assertFalse(capture.read()[0])
            capture.release()
        with self.assertRaises(FileExistsError):
            export_arenas(self.source, arenas, folder)
        self.assertTrue(all(path.exists() for path in outputs.values()))

    def test_cancel_preserves_existing_files(self):
        """Cancellation never publishes partial files or deletes annotations."""
        folder = self.root / "cancel"
        arena = Arena("a", "A", 0, 0, 48, 72)
        arena.folder(folder).mkdir(parents=True)
        arena.annotations_path(folder).write_text("keep\n")
        cancel_requested = [False]

        def progress(value):
            """Request cancellation once FFmpeg has started writing output."""
            cancel_requested[0] = value > 0

        with self.assertRaises(ExportCancelled):
            export_arenas(self.source, [arena], folder, progress, lambda: cancel_requested[0])
        self.assertFalse(arena.video_path(folder).exists())
        self.assertEqual(arena.annotations_path(folder).read_text(), "keep\n")
        self.assertFalse(list(folder.glob(".arena-export-*")))

    def test_variable_frame_rate(self):
        """Irregular timestamps must not introduce duplicate or missing frames."""
        vfr = self.root / "variable.mkv"
        flags = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0
        result = subprocess.run([ffmpeg_executable(), "-v", "error", "-i", str(self.source), "-vf",
                                 "setpts='if(lt(N,8),N/(30*TB),(8+(N-8)*2)/(30*TB))'",
                                 "-fps_mode", "vfr", "-c:v", "ffv1", str(vfr)], capture_output=True, creationflags=flags)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        source_info = probe_video(vfr, exact_count=True)
        paths = export_arenas(vfr, [Arena("a", "A", 1, 1, 45, 61)], self.root / "vfr_export")
        output_info = probe_video(paths["a"], exact_count=True)
        self.assertEqual(source_info["frame_count"], output_info["frame_count"])
        self.assertEqual(source_info["frame_count"], 17)


def benchmark_exports(output_path, repeats=3):
    """Compare validated shared-decoder exports against independent exports.

    This is an engineering benchmark, not an inferential biological analysis.
    CSV rows retain paired raw timings, exact frame counts, FPS, and geometry so
    another machine can reproduce the workload and compare measured speedups.
    The short synthetic clip includes noise and motion rather than flat frames.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ethoscore-arena-benchmark-") as temporary:
        root = Path(temporary)
        source = root / "benchmark.mkv"
        flags = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0
        generated = subprocess.run([ffmpeg_executable(), "-v", "error", "-f", "lavfi", "-i",
                                    "testsrc2=size=640x480:rate=30000/1001", "-frames:v", "180",
                                    "-c:v", "libx264", "-preset", "fast", str(source)],
                                   capture_output=True, creationflags=flags)
        if generated.returncode:
            raise RuntimeError(generated.stderr.decode())
        arenas = grid_arenas(640, 480)
        rows = []
        for repeat in range(repeats):
            # Alternate order to reduce systematic cache/order bias.
            methods = ("shared_decode", "sequential") if repeat % 2 == 0 else ("sequential", "shared_decode")
            for method in methods:
                start = time.perf_counter()
                if method == "shared_decode":
                    outputs = export_arenas(source, arenas, root / f"shared_{repeat}")
                else:
                    outputs = {}
                    for arena in arenas:
                        outputs.update(export_arenas(source, [arena], root / f"sequential_{repeat}_{arena.id}"))
                elapsed = time.perf_counter() - start
                counts = [probe_video(path, exact_count=True)["frame_count"] for path in outputs.values()]
                if counts != [180] * 4:
                    raise AssertionError(f"Benchmark produced incorrect frame counts: {counts}")
                rows.append({"repeat": repeat + 1, "method": method, "elapsed_seconds": elapsed,
                             "source_frames": 180, "source_width": 640, "source_height": 480,
                             "fps_num": 30000, "fps_den": 1001, "arenas": 4,
                             "output_frames_each": 180, "validated": True})
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--benchmark":
        benchmark_path = Path(__file__).parent / "artifacts" / "arena_export_benchmark.csv"
        print(benchmark_exports(benchmark_path))
        print(f"Saved benchmark: {benchmark_path}")
    else:
        unittest.main()

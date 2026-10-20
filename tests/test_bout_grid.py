"""Exercise real montage encoding using disposable, uniquely coloured frames."""
from copy import deepcopy
from pathlib import Path
import csv
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from annotator_libs.arena_export import ExportCancelled, ffmpeg_executable
from annotator_libs.bout_grid import GridConfig, GridSource, export_bout_grid, extract_bouts


class BoutGridTests(unittest.TestCase):
    """Check annotation semantics, independent loops, and publication safety."""
    def setUp(self):
        """Encode a small lossless source with identifiable grey frame values."""
        self.temp = tempfile.TemporaryDirectory(prefix="ethoscore-grid-test-")
        self.root = Path(self.temp.name)
        self.video = self.root / "source.mkv"
        self.images = [np.full((72, 96, 3), 20 + 20 * i, np.uint8) for i in range(10)]
        flags = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0
        subprocess.run([ffmpeg_executable(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                        "-s", "96x72", "-r", "4", "-i", "pipe:0", "-c:v", "ffv1", str(self.video)],
                       input=b"".join(image.tobytes() for image in self.images), capture_output=True,
                       check=True, creationflags=flags)
        self.config = GridConfig(rows=1, columns=2, tile_width=96, tile_height=72,
                                 output_fps=4, page_seconds=1, cache_megabytes=1)

    def tearDown(self):
        """Clean only this test's private generated files."""
        self.temp.cleanup()

    def test_contiguous_and_gaps(self):
        """A missing frame splits bouts even when adjacent rows match."""
        self.assertEqual(extract_bouts({5: ["rear"], 0: ["rear"], 1: ["rear", "sniff"],
                                       3: ["rear"], 4: []}, "rear"), [(0, 1), (3, 3), (5, 5)])
        with self.assertRaises(ValueError):
            extract_bouts({-1: ["rear"]}, "rear")
        self.assertEqual(extract_bouts({0: "rearing", 1: "rear", 2: ["rear"]}, "rear"), [(1, 2)])

    def test_multiarena_pages_loops_and_annotations_unchanged(self):
        """Every bout appears; tiles loop independently and output count is exact."""
        annotations = {0: ["rear"], 1: ["rear"], 4: ["rear"]}
        before = deepcopy(annotations)
        sources = [GridSource(self.video, annotations, "Arena 1"),
                   GridSource(self.video, {6: ["rear"], 7: ["rear"], 8: ["rear"]}, "Arena 2")]
        result = export_bout_grid(sources, "rear", self.root / "grid", self.config)
        self.assertEqual(annotations, before)
        self.assertEqual((result["bouts"], result["pages"], result["frames"]), (3, 2, 8))
        with open(result["manifest"], encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([(r["arena"], r["start_frame"], r["end_frame"], r["page"], r["tile"])
                          for r in rows], [("Arena 1", "1", "2", "1", "1"),
                                           ("Arena 1", "5", "5", "1", "2"),
                                           ("Arena 2", "7", "9", "2", "1")])
        capture = cv2.VideoCapture(result["output"])
        first, second = [], []
        try:
            for i in range(8):
                ok, frame = capture.read()
                self.assertTrue(ok)
                if i < 4:
                    first.append(float(frame[90:110, 40:60].mean()))
                    second.append(float(frame[90:110, 146:166].mean()))
            self.assertFalse(capture.read()[0])
        finally:
            capture.release()
        np.testing.assert_allclose(first, [20, 40, 20, 40], atol=5)
        np.testing.assert_allclose(second, [100] * 4, atol=5)

    def test_longest_bout_extends_page(self):
        """Long bouts are shown entirely rather than cut at minimum duration."""
        result = export_bout_grid([GridSource(self.video, {i: ["rear"] for i in range(10)})],
                                  "rear", self.root / "long", self.config)
        self.assertEqual(result["frames"], 10)
        self.assertEqual(result["duration_s"], 2.5)

    def test_cancel_cleans_staging(self):
        """Cancellation during composition publishes no partial result."""
        progressed = []
        with self.assertRaises(ExportCancelled):
            export_bout_grid([GridSource(self.video, {0: ["rear"]})], "rear", self.root / "cancel",
                             self.config, progress=progressed.append, cancel=lambda: bool(progressed))
        self.assertFalse((self.root / "cancel").exists())
        self.assertEqual(list(self.root.glob(".ethoscore-grid-*")), [])

    def test_existing_destination_and_out_of_bounds(self):
        """Existing files survive and invalid annotations fail before export."""
        folder = self.root / "existing"
        folder.mkdir()
        sentinel = folder / "precious.txt"
        sentinel.write_text("preserve")
        source = GridSource(self.video, {0: ["rear"]})
        with self.assertRaises(FileExistsError):
            export_bout_grid([source], "rear", folder, self.config)
        self.assertEqual(sentinel.read_text(), "preserve")
        with self.assertRaises(ValueError):
            export_bout_grid([GridSource(self.video, {10: ["rear"]})], "rear", self.root / "invalid", self.config)
        self.assertFalse((self.root / "invalid").exists())


if __name__ == "__main__":
    unittest.main()

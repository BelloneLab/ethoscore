"""GUI regression checks for cached versus direct frame identity.

Run in the application's Python environment with unittest discovery. Offscreen
Qt and dummy SDL drivers keep this test independent of the user's live window.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from annotator_libs.arena_export import ffmpeg_executable
from annotator_libs.video_handling import FrameCache, FramePreloader, VideoPlayer


class VideoFrameIntegrityTests(unittest.TestCase):
    """Protect frame-index identity while background decoding and seeking."""

    @classmethod
    def setUpClass(cls):
        """One GUI application serves all disposable video player tests."""
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        """Generate uniquely colored lossless frames in a private directory."""
        self.temporary = tempfile.TemporaryDirectory(prefix="ethoscore-frame-test-")
        self.source = Path(self.temporary.name) / "numbered.mkv"
        self.frames = []
        for index in range(45):
            frame = np.empty((72, 96, 3), np.uint8)
            frame[:] = (index * 5, 240 - index * 4, 40 + index * 3)
            cv2.putText(frame, str(index), (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255))
            self.frames.append(frame)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run([ffmpeg_executable(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                 "-s", "96x72", "-r", "30", "-i", "pipe:0", "-c:v", "ffv1", str(self.source)],
                                input=b"".join(frame.tobytes() for frame in self.frames), capture_output=True, creationflags=flags)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.player = VideoPlayer()
        self.player.available_behaviors = []

    def tearDown(self):
        """Join every decoder before deleting its temporary source."""
        self.player.shutdown()
        self.player.close()
        self.application.processEvents()
        self.temporary.cleanup()

    @staticmethod
    def image_array(image):
        """Read RGB pixels while respecting QImage row padding."""
        image = image.convertToFormat(QImage.Format_RGB888)
        rows = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
        return rows[:, :image.width() * 3].reshape(image.height(), image.width(), 3).copy()

    def assert_display_frame(self, index):
        """Compare the actual unscaled display image to the indexed source."""
        self.player.current_frame = index
        self.player.update_frame_display()
        expected = cv2.cvtColor(self.frames[index], cv2.COLOR_BGR2RGB)
        actual = self.image_array(self.player.original_pixmap.toImage())
        np.testing.assert_array_equal(actual, expected)

    def test_preloader_does_not_seek_foreground_capture(self):
        """A worker remains active while foreground cached/direct reads agree."""
        self.assertTrue(self.player.load_video(str(self.source), total_frames=45))
        self.player.preloader.stop()
        self.player.preloader.wait()
        self.player.frame_cache.clear()
        initial_position = self.player.video_capture.get(cv2.CAP_PROP_POS_FRAMES)
        blocked = threading.Event()
        release = threading.Event()
        original_put = self.player.frame_cache.put

        def delayed_worker_put(frame_number, image):
            """Hold only background puts to force deterministic concurrency."""
            if threading.current_thread() is not threading.main_thread():
                blocked.set()
                release.wait(timeout=5)
            original_put(frame_number, image)

        self.player.frame_cache.put = delayed_worker_put
        worker = FramePreloader(str(self.source), self.player.frame_cache, 20, 20, 45)
        self.player.preloader = worker
        worker.start()
        try:
            self.assertTrue(blocked.wait(timeout=5))
            self.assertTrue(worker.isRunning())
            self.assertEqual(self.player.video_capture.get(cv2.CAP_PROP_POS_FRAMES), initial_position)
            for index in (1, 2, 30, 7, 8, 0, 44, 12):
                self.assert_display_frame(index)
            release.set()
            worker.wait()
            for index in (20, 21, 25, 39, 3, 4, 44, 0):
                self.assert_display_frame(index)
            # Force misses after cache hits, exercising the sequential hint.
            self.player.frame_cache.clear()
            for index in (1, 2, 43, 42, 0, 1):
                self.assert_display_frame(index)
        finally:
            release.set()
            worker.stop()
            worker.wait()

    def test_exact_count_state_reset_and_bounded_cache(self):
        """New arenas inherit no held labels, timers, or stale cache memory."""
        self.player.range_labeling_active["behavior"] = True
        self.player.range_labeling_start["behavior"] = 12
        self.player.left_key_held = True
        self.player.navigation_timer.start(100)
        self.assertTrue(self.player.load_video(str(self.source), total_frames=45))
        self.assertEqual(self.player.total_frames, 45)
        self.assertEqual(self.player.progress_bar.maximum(), 45)
        self.assertFalse(self.player.left_key_held)
        self.assertFalse(self.player.navigation_timer.isActive())
        self.assertEqual(self.player.range_labeling_active, {})
        self.assertEqual(self.player.range_labeling_start, {})
        cache = FrameCache(max_size=20, max_bytes=1000)
        for index in range(20):
            cache.put(index, QImage(10, 10, QImage.Format_RGB888))
        self.assertLessEqual(cache.current_bytes, 1000)
        self.assertLessEqual(len(cache.cache), 3)
        with self.assertRaises(TypeError):
            cache.put(1, self.player.original_pixmap)
        self.player.shutdown()
        self.assertIsNone(self.player.video_capture)
        self.assertIsNone(self.player.preloader)
        self.assertEqual(self.player.frame_cache.current_bytes, 0)


if __name__ == "__main__":
    unittest.main()

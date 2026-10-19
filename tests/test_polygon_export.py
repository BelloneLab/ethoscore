"""Polygon persistence, invalid geometry, and real FFmpeg mask integrity tests."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from annotator_libs.arena_model import Arena, ArenaProject
from annotator_libs.arena_export import export_arenas, ffmpeg_executable, probe_video


class PolygonTests(unittest.TestCase):
    """Use only disposable synthetic recordings; never access research data."""

    def test_validation_and_atomic_setter(self):
        """Reject crossings, overlapping edges, repeated and noninteger points."""
        arena = Arena('a', 'A', 0, 0, 40, 40)
        valid = [[2, 3], [30, 3], [30, 28], [15, 15], [2, 28]]
        arena.set_polygon(valid)
        self.assertEqual(arena.rect, (2, 3, 28, 25))
        self.assertEqual(Arena(**asdict(arena)), arena)
        for points in ([[0,0],[20,20],[0,20],[20,0]], [[0,0],[10,0],[5,0],[5,10]],
                       [[0,0],[10,0],[10,10],[0,0]], [[0,0],[1,1],[2,2]],
                       [[0,0],[10.0,0],[10,10]], [[-1,0],[10,0],[10,10]]):
            with self.assertRaises(ValueError):
                arena.set_polygon(points)
            self.assertEqual(arena.polygon, valid)
        with self.assertRaises(ValueError):
            Arena('b', 'B', 0, 0, 40, 40, polygon=valid)
        with self.assertRaises(ValueError):
            arena.validate_bounds(20, 20)
        arena.set_polygon(None)
        self.assertIsNone(arena.polygon)
        self.assertEqual(arena.rect, (2, 3, 28, 25))

    def test_export_and_manifest(self):
        """Mixed rectangle/polygon exports keep frame identity and black exterior."""
        with tempfile.TemporaryDirectory(prefix='ethoscore-polygon-') as directory:
            root = Path(directory)
            source = root / 'source.mkv'
            frames = [np.full((48,64,3), (30+i*5, 120, 210), np.uint8) for i in range(13)]
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run([ffmpeg_executable(), '-v','error','-f','rawvideo','-pix_fmt','bgr24',
                                     '-s','64x48','-r','30000/1001','-i','pipe:0','-c:v','ffv1',str(source)],
                                    input=b''.join(f.tobytes() for f in frames), capture_output=True, creationflags=flags)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            arena = Arena('poly', 'Polygon', 0, 0, 10, 10)
            arena.set_polygon([[2,3],[45,3],[2,38]])
            rectangle = Arena('rect', 'Rectangle', 48, 0, 16, 48)
            folder = root / 'export'
            outputs = export_arenas(source, [arena,rectangle], folder, lossless=True)
            self.assertEqual(ArenaProject.load(folder).arenas[0], arena)
            info = probe_video(outputs['poly'], exact_count=True)
            self.assertEqual(info['frame_count'], len(frames))
            self.assertEqual((info['fps_num'], info['fps_den']), (30000,1001))
            capture = cv2.VideoCapture(str(outputs['poly']))
            try:
                for original in frames:
                    ok, decoded = capture.read()
                    self.assertTrue(ok)
                    self.assertEqual(decoded.shape[:2], (35,43))
                    self.assertLessEqual(int(decoded[-5:,-5:].max()), 2)
                    self.assertLessEqual(np.abs(decoded[4,4].astype(int)-original[7,6].astype(int)).max(), 3)
                self.assertFalse(capture.read()[0])
            finally:
                capture.release()
            # A single polygon uses the same source clock even with irregular
            # timestamps; a finite static mask must never truncate the movie.
            variable = root / 'variable.mkv'
            result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(source),
                                     '-vf', "setpts='if(lt(N,6),N/(30*TB),(6+(N-6)*2)/(30*TB))'",
                                     '-fps_mode', 'vfr', '-c:v', 'ffv1', str(variable)],
                                    capture_output=True, creationflags=flags)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            variable_paths = export_arenas(variable, [arena], root / 'vfr_export')
            variable_info = probe_video(variable_paths['poly'], exact_count=True)
            self.assertEqual(variable_info['frame_count'], len(frames))
            # Existing rectangular manifests remain loadable without the field.
            manifest = folder / 'arenas.json'
            data = json.loads(manifest.read_text())
            del data['arenas'][1]['polygon']
            manifest.write_text(json.dumps(data))
            self.assertIsNone(ArenaProject.load(folder).arenas[1].polygon)


if __name__ == '__main__':
    unittest.main()

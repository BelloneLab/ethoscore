"""Installer contract tests: updates preserve data and archives cannot escape."""

from __future__ import annotations

import io
import hashlib
import json
import os
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from installer import backend


class InstallationTests(unittest.TestCase):
    """Exercise fresh install, update, failure recovery, locking, and path security."""

    def setUp(self):
        """Use an isolated installation tree, never the user's actual app or files."""
        self.temporary = tempfile.TemporaryDirectory(prefix="ethoscore-installer-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / "installed application"

    def payload(self, version="one", extra=None, platform=None):
        """Create a tiny application-shaped tarball with optional hostile entries."""
        path = self.root / f"payload-{version}.tar.gz"
        executable = "Ethoscore.app/Contents/MacOS/Ethoscore" if sys.platform == "darwin" else "app/Ethoscore.exe"
        metadata = {"application": "Ethoscore", "version": version,
                    "platform": platform or backend.platform_key(), "executable": executable}
        with tarfile.open(path, "w:gz") as archive:
            for name, data in (("payload.json", json.dumps(metadata).encode()), (executable, version.encode())):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o755
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b"bad") if extra.isfile() else None)
        return path

    def install(self, archive, **kwargs):
        """Disable real shortcuts so test runs cannot modify OS integration."""
        return backend.install_payload(archive, self.destination, shortcuts=False, **kwargs)

    def test_install_update_preserves_data_and_prior_version(self):
        """An update changes active code while every user file and old build remain."""
        first = self.install(self.payload())
        old_executable = backend.installed_executable(self.destination, first)
        annotations = self.destination / "user-data/annotations.csv"
        annotations.write_text("frame,label\n1,nose-to-nose\n", encoding="utf-8")
        original = annotations.read_bytes()
        second = self.install(self.payload("two"), desktop=False, menu=True)
        self.assertEqual(backend.read_install(self.destination)["version"], "two")
        self.assertEqual(annotations.read_bytes(), original)
        self.assertEqual(old_executable.read_bytes(), b"one")
        self.assertEqual(backend.installed_executable(self.destination, second).read_bytes(), b"two")
        self.assertNotEqual(first["directory"], second["directory"])
        self.assertFalse(second["desktop"])

    def test_bad_update_leaves_previous_active_manifest(self):
        """A failed extraction does not alter the active application or leave a lock."""
        self.install(self.payload())
        before = (self.destination / backend.MARKER).read_bytes()
        with self.assertRaises(ValueError):
            self.install(self.payload("wrong-platform", platform="unsupported"))
        self.assertEqual((self.destination / backend.MARKER).read_bytes(), before)
        self.assertFalse((self.destination / ".install-lock").exists())
        self.assertEqual(len(list((self.destination / "versions").iterdir())), 1)

    def test_stable_launcher_tracks_update_without_shortcut_recreation(self):
        """A previously created shortcut follows the rewritten stable launcher."""
        first = self.install(self.payload())
        launcher = self.destination / ("Launch Ethoscore.vbs" if os.name == "nt" else "Launch Ethoscore")
        self.assertIn(str(backend.installed_executable(self.destination, first)), launcher.read_text(encoding="utf-8"))
        second = self.install(self.payload("two"), desktop=False, menu=False)
        self.assertIn(str(backend.installed_executable(self.destination, second)), launcher.read_text(encoding="utf-8"))
        self.assertNotIn(first["directory"].split("/")[-1], launcher.read_text(encoding="utf-8"))

    def test_failed_fresh_install_can_retry(self):
        """Failed new installs leave a destination that can immediately be retried."""
        with self.assertRaises(ValueError):
            self.install(self.payload("wrong-platform", platform="unsupported"))
        self.install(self.payload())
        self.assertEqual(backend.read_install(self.destination)["version"], "one")

    def test_unrelated_nonempty_directory_is_rejected(self):
        """Installing into a checkout or a data folder cannot overwrite its files."""
        self.destination.mkdir()
        sentinel = self.destination / "ethoscore.py"
        sentinel.write_text("user source", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.install(self.payload())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user source")

    def test_archive_traversal_and_external_symlink_are_rejected(self):
        """Both ordinary traversal and link traversal fail without outside writes."""
        for kind in ("path", "symlink"):
            with self.subTest(kind=kind):
                member = tarfile.TarInfo("../escaped" if kind == "path" else "app/external")
                if kind == "symlink":
                    member.type, member.linkname = tarfile.SYMTYPE, "../../escaped"
                else:
                    member.size = 3
                with self.assertRaises((ValueError, tarfile.FilterError)):
                    self.install(self.payload(kind, member))
                self.assertFalse((self.root / "escaped").exists())

    def test_concurrent_install_lock_is_respected(self):
        """A second installer cannot write while another operation owns the lock."""
        self.install(self.payload())
        (self.destination / ".install-lock").touch()
        with self.assertRaises(RuntimeError):
            self.install(self.payload("two"))
        self.assertEqual(backend.read_install(self.destination)["version"], "one")

    def test_untrusted_release_download_url_is_rejected(self):
        """Network release metadata cannot direct downloads to arbitrary servers."""
        for url in ("http://github.com/BelloneLab/ethoscore/releases/download/v1/app", "https://evil.example/file", "https://github.com/other/repo/releases/download/v1/app"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                backend.download(url, self.root / "download")

    def test_download_checksum_detects_corruption(self):
        """A corrupt release package never reaches the installation transaction."""
        content = b"official application payload"
        release = {"name": "application.tar.gz", "url": "archive", "checksum_url": "checksum"}

        def fake_download(url, target, progress):
            """Supply a deterministic local stand-in for each network response."""
            target.write_bytes((hashlib.sha256(content).hexdigest() + "  application.tar.gz\n").encode() if url == "checksum" else b"corrupted payload")

        with patch.object(backend, "download", side_effect=fake_download), self.assertRaisesRegex(ValueError, "SHA-256"):
            backend.download_release(release, self.root, lambda _: None)

    def test_online_update_prefers_continuous_release(self):
        """Main builds use the rolling release even when a stable tag also exists."""
        name = f"Ethoscore-{backend.platform_key()}.tar.gz"
        response = {"tag_name": "latest", "assets": [
            {"name": name, "browser_download_url": "https://github.com/BelloneLab/ethoscore/releases/download/latest/" + name},
            {"name": name + ".sha256", "browser_download_url": "https://github.com/BelloneLab/ethoscore/releases/download/latest/" + name + ".sha256"}]}
        with patch.object(backend.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as request:
            self.assertEqual(backend.latest_release()["version"], "latest")
        self.assertEqual(request.call_count, 1)
        self.assertTrue(request.call_args.args[0].full_url.endswith("/releases/tags/latest"))

    def test_shortcut_failure_keeps_successful_application_install(self):
        """OS shortcut errors report a warning without invalidating installed code."""
        with patch.object(backend, "create_shortcuts", side_effect=OSError("denied")):
            state = backend.install_payload(self.payload(), self.destination)
        self.assertIn("denied", state["shortcut_warning"])
        self.assertEqual(backend.read_install(self.destination)["version"], "one")

    def test_installed_executable_rejects_modified_outside_path(self):
        """A tampered control file cannot make the launcher execute outside versions."""
        state = self.install(self.payload())
        state["executable"] = "../../../../foreign.exe"
        with self.assertRaises(ValueError):
            backend.installed_executable(self.destination, state)


if __name__ == "__main__":
    unittest.main()

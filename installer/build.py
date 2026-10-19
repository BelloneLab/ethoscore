"""Build a native application archive and self-contained graphical installer.

Run in a Python 3.12 environment containing requirements.txt and PyInstaller.
Builds must run natively on each supported target OS and CPU architecture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from installer.backend import platform_key


def run_build(spec: Path, root: Path) -> None:
    """Execute PyInstaller in a checked subprocess with deterministic output paths."""
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)], cwd=root, check=True)


def write_checksum(artifact: Path) -> None:
    """Write the SHA-256 sidecar consumed by the graphical updater."""
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    artifact.with_name(artifact.name + ".sha256").write_text(f"{digest.hexdigest()}  {artifact.name}\n", encoding="utf-8")


def build(version: str, skip_application: bool = False) -> None:
    """Package application, metadata, checksum, and setup into release-ready files."""
    root = Path(__file__).resolve().parents[1]
    if not skip_application:
        run_build(root / "installer/application.spec", root)
    payload = root / "build/installer_payload"
    payload.mkdir(parents=True, exist_ok=True)
    metadata = {"application": "Ethoscore", "version": version, "platform": platform_key(),
                "executable": "Ethoscore.app/Contents/MacOS/Ethoscore" if sys.platform == "darwin" else
                              "Ethoscore/Ethoscore.exe" if sys.platform == "win32" else "Ethoscore/Ethoscore"}
    metadata_path = payload / "payload.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    application = root / "dist" / ("Ethoscore.app" if sys.platform == "darwin" else "Ethoscore")
    archive = payload / "application.tar.gz"
    with tarfile.open(archive, "w:gz", compresslevel=3, dereference=False) as bundle:
        bundle.add(metadata_path, arcname="payload.json")
        bundle.add(application, arcname=application.name)
    release = root / "dist/releases"
    release.mkdir(parents=True, exist_ok=True)
    target = release / f"Ethoscore-{platform_key()}.tar.gz"
    shutil.copy2(archive, target)
    write_checksum(target)
    run_build(root / "installer/setup.spec", root)
    if sys.platform == "darwin":
        # ditto preserves the application bundle metadata in the distributed ZIP.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(root / "dist/Ethoscore-Setup.app"),
                        str(release / f"Ethoscore-Setup-{platform_key()}.zip")], check=True)
    else:
        suffix = ".exe" if sys.platform == "win32" else ""
        target = release / f"Ethoscore-Setup-{platform_key()}{suffix}"
        shutil.copy2(root / f"dist/Ethoscore-Setup{suffix}", target)
        if os.name != "nt":
            target.chmod(0o755)
    print(f"Native installer and application package: {release}")


def main() -> None:
    """Expose a short reproducible command for developers and release CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="development", help="Version shown in Setup and installation manifests")
    parser.add_argument("--skip-application", action="store_true", help="Reuse the existing native application build")
    args = parser.parse_args()
    build(args.version, args.skip_application)


if __name__ == "__main__":
    main()

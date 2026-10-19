"""Transactional application installation, verified downloads, and OS shortcuts.

Only fresh version directories are written. Existing versions and user files are
never removed, so updating an application that is still open is safe.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from typing import Callable
import urllib.request
import uuid
from branding import asset_path

REPOSITORY = "BelloneLab/ethoscore"
MARKER = ".ethoscore-install.json"
MAX_DOWNLOAD = 3 * 1024**3
MAX_UNPACKED = 6 * 1024**3


def platform_key() -> str:
    """Return the release artifact identifier for this operating system/CPU."""
    system = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if not system or not arch:
        raise RuntimeError("This system architecture is not supported by this installer.")
    return f"{system}-{arch}"


def default_destination() -> Path:
    """Choose a writable per-user installation directory without administrator rights."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs/Ethoscore"
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/Ethoscore"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ethoscore"


def read_install(destination: Path) -> dict | None:
    """Read a managed install, rejecting corrupt or unrelated installation markers."""
    marker = destination / MARKER
    if not marker.exists():
        return None
    state = json.loads(marker.read_text(encoding="utf-8"))
    if state.get("application") != "Ethoscore" or state.get("schema") != 1:
        raise ValueError("The destination contains an unsupported installation manifest.")
    return state


def atomic_text(path: Path, text: str) -> None:
    """Replace a small control file atomically, keeping partial writes invisible."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _trusted_release_url(url: str) -> None:
    """Allow application downloads only from this project's GitHub release assets."""
    if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
        raise ValueError("The release asset URL does not belong to the official repository.")


def download(url: str, target: Path, progress: Callable[[str], None] = lambda _: None) -> None:
    """Stream an HTTPS download with a bounded size and no shell interpretation."""
    _trusted_release_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Ethoscore-Installer"})
    with urllib.request.urlopen(request, timeout=45) as response, target.open("wb") as output:
        total = int(response.headers.get("Content-Length", 0))
        if total > MAX_DOWNLOAD:
            raise ValueError("The application download exceeds the supported size.")
        received = 0
        next_report = 0
        while chunk := response.read(1024 * 1024):
            received += len(chunk)
            if received > MAX_DOWNLOAD:
                raise ValueError("The application download exceeds the supported size.")
            output.write(chunk)
            if received >= next_report:
                progress(f"Downloading application: {received // (1024 * 1024)} MB" +
                         (f" / {total // (1024 * 1024)} MB" if total else ""))
                next_report = received + 8 * 1024**2


def latest_release() -> dict:
    """Find the continuous release first, falling back to the latest stable tag."""
    last_error = None
    for endpoint in ("tags/latest", "latest"):
        try:
            request = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/{endpoint}",
                                             headers={"User-Agent": "Ethoscore-Installer", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=25) as response:
                release = json.load(response)
            name = f"Ethoscore-{platform_key()}.tar.gz"
            assets = {asset["name"]: asset for asset in release["assets"]}
            if name not in assets or name + ".sha256" not in assets:
                raise RuntimeError(f"This release has no {platform_key()} application package yet.")
            return {"version": release["tag_name"], "name": name,
                    "url": assets[name]["browser_download_url"],
                    "checksum_url": assets[name + ".sha256"]["browser_download_url"]}
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Cannot find a compatible official release: {last_error}")


def download_release(release: dict, directory: Path, progress: Callable[[str], None]) -> Path:
    """Download the platform payload and verify it against the published SHA-256."""
    archive, checksum = directory / release["name"], directory / "checksum.txt"
    download(release["checksum_url"], checksum, progress)
    expected = checksum.read_text(encoding="utf-8").split()[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("The release checksum is invalid.")
    download(release["url"], archive, progress)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("The downloaded application failed its SHA-256 integrity check.")
    return archive


def extract_payload(archive: Path, destination: Path) -> dict:
    """Validate and extract a native payload without permitting archive traversal."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if sum(member.size for member in members) > MAX_UNPACKED:
            raise ValueError("The unpacked application exceeds the supported size.")
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or member.isdev() or member.isfifo():
                raise ValueError("The application archive contains an unsafe path or device.")
        # Python's data filter also rejects links pointing outside the payload.
        bundle.extractall(destination, filter="data")
    metadata = json.loads((destination / "payload.json").read_text(encoding="utf-8"))
    executable = (destination / metadata["executable"]).resolve()
    if metadata.get("application") != "Ethoscore" or metadata.get("platform") != platform_key():
        raise ValueError("The payload does not match this platform or application.")
    if not executable.is_relative_to(destination.resolve()) or not executable.is_file():
        raise ValueError("The payload has no valid application executable.")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    return metadata


def install_payload(archive: Path, destination: Path, desktop: bool = True, menu: bool = True,
                    progress: Callable[[str], None] = lambda _: None,
                    shortcuts: bool = True) -> dict:
    """Stage a complete version, then atomically activate it and refresh shortcuts.

    The current application and user-data folder remain intact on any extraction
    failure. A new immutable version folder also allows an old app to stay open.
    """
    destination = destination.expanduser().resolve()
    state = read_install(destination)
    if destination.exists() and any(destination.iterdir()) and not state:
        raise ValueError("Choose an empty folder or an existing managed Ethoscore installation. Your source checkout is not an installation folder.")
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / ".install-lock"
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError("Another installation is active. If it was interrupted, close Setup and remove .install-lock from this installation folder.") from error
    stage = None
    try:
        os.close(handle)
        versions = destination / "versions"
        versions.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=versions))
        progress("Unpacking a fresh application version...")
        metadata = extract_payload(archive, stage)
        version = str(metadata.get("version", "development"))
        final = versions / ("build-" + uuid.uuid4().hex[:12])
        stage.rename(final)
        stage = None
        user_data = destination / "user-data"
        user_data.mkdir(exist_ok=True)
        state = {"application": "Ethoscore", "schema": 1, "version": version,
                 "platform": platform_key(), "directory": str(final.relative_to(destination)),
                 "executable": metadata["executable"], "desktop": desktop, "menu": menu}
        _install_branding(destination, final)
        atomic_text(destination / MARKER, json.dumps(state, indent=2))
        _write_launcher(destination, state)
        if shortcuts:
            progress("Creating the selected launch shortcuts...")
            try:
                create_shortcuts(destination, state)
            except Exception as error:
                state["shortcut_warning"] = str(error)
                progress(f"Application installed. Some shortcuts could not be created: {error}")
        progress("Ethoscore is ready. Your videos and annotations are preserved.")
        return state
    finally:
        # Only this invocation's newly created staging directory can be removed.
        if stage and stage.parent == destination / "versions" and stage.name.startswith(".staging-"):
            shutil.rmtree(stage)
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()
        with contextlib.suppress(OSError):
            (destination / "versions").rmdir()


def installed_executable(destination: Path, state: dict) -> Path:
    """Resolve the active executable only if it stays inside the managed versions."""
    executable = (destination / state["directory"] / state["executable"]).resolve()
    if not executable.is_relative_to((destination / "versions").resolve()):
        raise ValueError("The installation executable path is invalid.")
    return executable


def _write_launcher(destination: Path, state: dict) -> None:
    """Create a readable, stable launch entry beside the managed user-data folder."""
    executable = installed_executable(destination, state)
    if os.name == "nt":
        # VBScript launches the GUI without flashing a terminal window.
        escaped = str(executable).replace('"', '""')
        cwd = str(destination / "user-data").replace('"', '""')
        atomic_text(destination / "Launch Ethoscore.vbs",
                    f'Set shell = CreateObject("WScript.Shell")\nshell.CurrentDirectory = "{cwd}"\nshell.Run Chr(34) & "{escaped}" & Chr(34), 1, False\n')
    else:
        launcher = destination / "Launch Ethoscore"
        atomic_text(launcher, f"#!/bin/sh\ncd {shlex.quote(str(destination / 'user-data'))} || exit 1\nexec {shlex.quote(str(executable))} \"$@\"\n")
        launcher.chmod(0o755)
        if platform.system() == "Darwin":
            app = next(parent for parent in executable.parents if parent.suffix == ".app")
            link = destination / "Ethoscore.app"
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                raise FileExistsError(f"Cannot replace an existing application at {link}")
            link.symlink_to(app, target_is_directory=True)


def _install_branding(destination: Path, version_directory: Path) -> None:
    """Publish stable shortcut artwork, preferring the downloaded version's brand.

    Older payloads do not contain the shell-artwork directory, so the setup's own
    matching artwork provides compatibility when reinstalling an earlier version.
    """
    target_directory = destination / "assets/branding"
    target_directory.mkdir(parents=True, exist_ok=True)
    for filename in ("ethoscore-icon.svg", "ethoscore-icon.ico", "ethoscore-icon.png",
                     "ethoscore-icon.icns", "ethoscore-logo.svg", "ethoscore-logo-light.svg"):
        source = version_directory / "branding" / filename
        if not source.is_file():
            source = asset_path(filename)
        if source.is_file():
            target = target_directory / filename
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)


def _windows_shortcut(path: Path, executable: Path, cwd: Path, arguments: str = "",
                      icon: Path | None = None) -> None:
    """Use the Windows shell COM API to write a .lnk without command interpolation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:ETHO_LINK);$s.TargetPath=$env:ETHO_TARGET;$s.Arguments=$env:ETHO_ARGUMENTS;$s.WorkingDirectory=$env:ETHO_CWD;$s.IconLocation=$env:ETHO_ICON;$s.Description='Ethoscore behavioral video annotation';$s.Save()"
    env = dict(os.environ, ETHO_LINK=str(path), ETHO_TARGET=str(executable), ETHO_CWD=str(cwd),
               ETHO_ARGUMENTS=arguments, ETHO_ICON=str(icon or executable) + ",0")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), capture_output=True)


def _desktop_directory() -> Path:
    """Find the actual Windows Known Folder or Linux XDG desktop directory."""
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return Path(os.path.expandvars(winreg.QueryValueEx(key, "Desktop")[0]))
    if platform.system() == "Linux":
        try:
            value = subprocess.check_output(["xdg-user-dir", "DESKTOP"], text=True).strip()
            if value:
                return Path(value)
        except (OSError, subprocess.CalledProcessError):
            pass
    return Path.home() / "Desktop"


def create_shortcuts(destination: Path, state: dict) -> None:
    """Create only selected shortcuts using native platform conventions."""
    executable = installed_executable(destination, state)
    desktop = _desktop_directory() if state["desktop"] else None
    if os.name == "nt":
        host = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/wscript.exe"
        icon = destination / "assets/branding/ethoscore-icon.ico"
        arguments = '"' + str(destination / "Launch Ethoscore.vbs") + '"'
        if desktop:
            _windows_shortcut(desktop / "Ethoscore.lnk", host, destination / "user-data", arguments, icon)
        if state["menu"]:
            menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
            _windows_shortcut(menu / "Ethoscore.lnk", host, destination / "user-data", arguments, icon)
    elif platform.system() == "Darwin":
        app = destination / "Ethoscore.app"
        for parent in ([desktop] if desktop else []) + ([Path.home() / "Applications"] if state["menu"] else []):
            parent.mkdir(parents=True, exist_ok=True)
            link = parent / "Ethoscore.app"
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                raise FileExistsError(f"Cannot replace an existing application at {link}")
            link.symlink_to(app, target_is_directory=True)
    else:
        # Desktop Entry quoting follows the freedesktop string escaping rules.
        launch_path = str(destination / "Launch Ethoscore").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        icon_path = str(destination / "assets/branding/ethoscore-icon.svg").replace("\\", "\\\\").replace("\n", "\\n")
        content = f'[Desktop Entry]\nType=Application\nName=Ethoscore\nComment=Behavioral video annotation\nExec="{launch_path}"\nIcon={icon_path}\nTerminal=false\nCategories=Science;Education;\n'
        for parent in ([desktop] if desktop else []) + ([Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"] if state["menu"] else []):
            parent.mkdir(parents=True, exist_ok=True)
            target = parent / "ethoscore.desktop"
            atomic_text(target, content)
            target.chmod(0o755)


def launch(destination: Path) -> subprocess.Popen:
    """Open the active application with user data as its writable working folder."""
    state = read_install(destination)
    if not state:
        raise RuntimeError("Ethoscore has not been installed in this folder.")
    return subprocess.Popen([str(installed_executable(destination, state))], cwd=destination / "user-data",
                            start_new_session=os.name != "nt")

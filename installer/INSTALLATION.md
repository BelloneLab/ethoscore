# Ethoscore installation and updates

Download **Ethoscore-Setup** for your operating system and processor from the
[official releases](https://github.com/BelloneLab/ethoscore/releases).
The graphical installer includes Python, Qt, the video decoder, and all application
dependencies. Git and a separate Python installation are not required.

1. Open Setup and choose an installation folder. The default is a writable folder
   for your account, without administrator privileges.
2. Choose the bundled application for an offline install, or download the latest
   official build. Choose desktop and Start menu / Applications shortcuts.
3. Install, then select **Launch Ethoscore**. The shortcuts open the installed app.

To update, reopen Setup, choose your existing installation folder, then select
**Download the latest official build** and **Update / Reinstall**. Downloaded
application packages are checked against the SHA-256 published with that release.
The bundled option reinstalls that Setup's version and can also restore an older
version. The displayed version identifies what is installed.

Each update stages a fresh application directory and activates it after validation.
It does not modify an already-running version. Relaunch to use the update. Old
application versions are retained for recovery. Your source checkout, original
videos, arena folders, annotation files, and application preferences are not
deleted. A nonempty folder without an Ethoscore install marker is rejected.
Installing over a Git checkout is intentionally unsupported.

Windows shortcuts use the actual Desktop Known Folder and your personal Start
menu. macOS shortcuts appear in `~/Applications` and optionally on the Desktop.
Linux installs a freedesktop launcher under the user Applications menu and
optionally on the Desktop. Some Linux desktops require marking a launcher as
trusted through their file manager before double-clicking it.

## Building native installers

Use Python 3.12 and install `requirements.txt` plus `pyinstaller>=6.11` in a dedicated
environment, then run from the repository root:

```console
python -m installer.build --version 2026.10.19
```

Results appear under `dist/releases`: a setup executable, a native application
archive, and its checksum. Build on Windows for Windows, macOS for macOS, and Linux
for Linux. GitHub Actions builds Windows x86-64, Linux x86-64, and macOS arm64 and
x86-64 using native runners. The macOS Setup is distributed as a ZIP containing its
application bundle. Extract the ZIP before opening Setup. Linux Setup is a native
executable; mark it executable with `chmod +x Ethoscore-Setup-Linux-x86_64`.

From a development checkout, `python -m installer` opens the same interface.
Without a locally built bundled payload, it offers official online release
downloads. Source code is never copied over an arbitrary checkout by Setup.

The build currently creates unsigned packages. Signing certificates and Apple
notarization credentials must be configured by the publisher before distributing
signed releases. SHA-256 checks detect corruption; they do not replace publisher
code signing. Linux binaries target the GitHub runner's glibc baseline. macOS and
Linux release builds require their CI/native smoke checks; Windows testing alone
cannot establish compatibility with those systems.

Packaging follows the maintained
[PyInstaller native build documentation](https://www.pyinstaller.org/en/stable/usage.html).

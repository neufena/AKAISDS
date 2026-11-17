# Building From Source

## Prerequisites

- Python 3.12 or higher
- A C++17 compiler: the build scripts compile the small REX2 reader (`third_party/velociloops`, via `tools/build_velociloops.py`) for your machine
- Other dependencies are in the `pyproject.toml` file which will be installed automatically when running one of the build scripts below

#### macOS

- Xcode Command Line Tools

#### Linux

- `build-essential` and `patchelf` (can be installed with `sudo apt install build-essential patchelf` on Ubuntu-based distributions)

#### Windows

- A C++ compiler: Visual Studio Build Tools (`cl`) or MinGW (`g++`) on `PATH`, for the REX2 reader. Nuitka downloads its own MinGW if it finds no MSVC
- [uv](https://docs.astral.sh/uv/) and Git (uv fetches the pinned `s3ked` from GitHub)
- Optional, for the installer: [Inno Setup 6](https://jrsoftware.org/isinfo.php)

## Setup and Build

1. Clone repository with `git clone https://github.com/martincurkovic/AKAISDS.git`
2. Run the relevant script for your platform (located in the `scripts` folder). Note that running a PowerShell script on Windows for the first time will trigger a warning but it can be mitigated by running `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` before running the build script. On Linux or macOS you _may_ need to run `chmod +x build_xxx.sh` on the relevant script for your platform
3. Final build will land in the `src` directory

#### Linux: devcontainer

`.devcontainer/` has a Debian Trixie container with everything the Linux build needs. Inside it, `scripts/build_linux.sh` builds the app and `.devcontainer/build-linux-appimage.sh` also makes `AKAISDS-linux.AppImage`, as CI does.

#### Windows: build on a Windows machine

Nuitka can't cross-compile, so the Windows build is not done in the devcontainer. On a Windows host (or the `windows-latest` CI job): in PowerShell, from the repository root, run `.\scripts\build_windows.ps1` (the first time, `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`). The app lands in `src\AKAISDS.dist`. For the installer, then run `& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=<version> assets\windows\AKAISDS.iss`, where the version is the one in `src\ui\_version.py`; that produces `AKAISDS-Setup.exe`.

#### macOS: two builds

`scripts/build_macos.sh` makes the regular build (Qt 6.11, macOS 13 and later, `AKAISDS-macos-{arm,intel}.dmg`). `AKAISDS_FLAVOR=legacy scripts/build_macos.sh` makes the legacy one (Qt 6.8, macOS 12 and later, `AKAISDS-macos-{arm,intel}-legacy.dmg`) in its own `.venv-legacy`. `scripts/check_minos.sh 12.0 [app or dmg]` lists anything in a build that needs a newer macOS. Qt is in a dependency group (`qt-current`, installed by default; `qt-legacy`), not in the project's plain dependencies: use `uv sync`, not `pip install .`. Details: [dev_docs/macos12-support-handoff.md](dev_docs/macos12-support-handoff.md).

## Running Without a Sampler

The app, the editors and the demo samplers can all be run from source without any hardware - see "Running the app without a sampler" in [CONTRIBUTING.md](CONTRIBUTING.md) (`uv run python tools/demo.py list`, `AKAISDS_DEMO_SAMPLER=1 uv run python src/main.py`, and `--instant` to skip the MIDI-speed emulation).

## Running Tests

There's a pytest suite in the `tests` directory (about 3-4 minutes) - see [TESTING.md](TESTING.md). Sync the environment first with `uv sync`, then run `uv run pytest tests/ -q`.

# OpenWrench Desktop

A local, open-source automotive workshop application, developed one tested
milestone at a time. Current version: **0.1.0.dev1, desktop foundation**.

This build opens a native desktop window, stores appearance settings in SQLite,
checks database integrity, and saves database backups. It contains no repair
specifications, vehicle editing, VIN decoder, simulated scans, or hardware driver.
Those features belong to later milestones. No server, browser, subscription,
telemetry, account, or network connection runs inside this build.

## Run from source

Development requires Python 3.11–3.13. Python 3.12 is the tested baseline.

Windows PowerShell, from the extracted project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m openwrench
```

Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m openwrench
```

Linux desktop prerequisites include glibc 2.28 or later and Qt's system display
libraries. Ubuntu 22.04 is the CI target. Install `libegl1 libopengl0
libxkbcommon0 libdbus-1-3 libxcb-cursor0 libxcb-icccm4 libxcb-image0
libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1
libxkbcommon-x11-0` through your system package manager when absent.
The offscreen test does not prove X11/Wayland compatibility on your desktop.

## Test and build

Use the virtual environment's Python in these commands:

```sh
python -m pytest -q
python -m build
python scripts/build_desktop.py
```

The native development bundle appears in `dist/OpenWrench`. On Windows, run
`OpenWrench.exe` from this directory. On Linux, run `./OpenWrench`.
Keep the entire directory together. PyInstaller includes the Python runtime
and Qt, so this bundled application does not require a separate Python install.
Build on the target operating system. This is a portable development bundle,
not a tested installer or public release. The Windows build has not run locally.

Smoke-test an isolated workspace:

```sh
python -m openwrench --smoke-test --data-dir ./artifacts/smoke
```

For headless Linux, set `QT_QPA_PLATFORM=offscreen`. The smoke test runs the Qt
event loop, displays the native window through Qt's offscreen platform, checks
SQLite, and exits. `--screenshot ./artifacts/window.png` saves its render.
Never point a test at your real workspace.

## Local data and upgrades

Settings shows the exact database path. Qt chooses a per-user data directory:
typically `%LOCALAPPDATA%/OpenWrench/OpenWrench` on Windows,
`~/.local/share/OpenWrench/OpenWrench` on Linux, and
`~/Library/Application Support/OpenWrench/OpenWrench` on macOS.
`--data-dir PATH` overrides this location.

The database contains settings only in this milestone. Backups use SQLite's
snapshot API and refuse to overwrite existing files. Restore UI arrives in
milestone 2. For this development version, close the application and copy a
known-good backup into a separate workspace as `openwrench.sqlite3`, then launch
with `--data-dir` pointing to it. Preserve the original before doing so.

Schema migration 0 → 1 runs transactionally. Newer schemas cause a clear startup
failure instead of a downgrade. Replacing the application directory leaves
user data intact. No automatic updater exists yet. Logs rotate at 500 KB with
two retained copies. They record application lifecycle events, not VINs or scans.
No installer or uninstaller currently runs.

## Project map

- `src/openwrench`: native UI, storage, lifecycle, provider and adapter contracts
- `tests`: persistence, backup failures, real Qt interaction, and launch tests
- `scripts`: same-platform desktop packaging
- `examples`: four development profiles with unknown fields left null
- `schemas`: data-contribution design boundary for milestone 3
- `docs/ARCHITECTURE.md`: stack decision and component boundaries
- `docs/RESEARCH.md` and `THIRD_PARTY.md`: reuse research and license register
- `ROADMAP.md` and `DEVELOPMENT_STATUS.md`: progress and exact next task

MIT covers original project code. Dependencies retain their own licenses.
See `THIRD_PARTY.md` before distributing a native binary.

## GitHub handoff

No remote repository or public release exists yet. Read `docs/GITHUB_SETUP.md`.
The source handoff includes a Git bundle preserving the local development
branch. GitHub becomes the authoritative progress record after first push.

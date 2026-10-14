# OpenWrench Desktop

A local, open-source automotive workshop application. Current development
version: **0.2.0.dev2, Vehicle Garage**.

Add, view, edit and delete vehicles in the existing native PySide6 application.
Record dated odometer readings and service history, including notes, parts,
optional cost and currency. SQLite stores all records locally. Internet access
is optional and only supports an explicitly requested NHTSA VIN lookup.

The application does not contain repair specifications, simulated scans or a
hardware driver yet. No server, browser, subscription or account is required.

## Use Vehicle Garage

1. Choose **Add vehicle**. Enter year, make and model manually, or select one of
   the four optional starting profiles. Nothing saves until you choose Save.
2. Leave unknown engine/trim fields blank. Tundra and Civic presets supply no
   engine or trim. Other makes and models use the same form.
3. Give each vehicle a distinct Garage name. A blank name defaults to year,
   make and model. VIN is optional, uppercase-normalized and unique when entered.
4. For a VIN lookup, enter the full 17-character VIN and optional year, then
   choose **Decode VIN with NHTSA**. This sends the VIN and year to NHTSA over
   HTTPS. Review the result and choose **Apply returned fields to blanks**.
   Existing typed values remain unchanged. Review them before saving.
5. Select a vehicle to view details. Use **Log mileage** or **Add service** to
   add records. Select a history row to edit or delete it. Deletion asks for
   confirmation. Vehicle deletion also removes its history.
6. Use Settings to export Garage JSON or a ZIP of related CSV files, save a complete
   SQLite backup, or restore a validated backup after confirmation.

VIN lookup uses asynchronous Qt networking, a 15-second deadline and a local
30-day cache. Invalid/partial decodes display NHTSA's message instead of filling
fields automatically. Manual entry works without a network connection.

Mileage is a whole-number odometer reading in mi or km. Distance units lock once
history exists. Backdated records must agree with earlier and later readings.
The summary displays the highest recorded reading. Same-day readings lack time
ordering. Odometer replacement/rollover and unit conversion remain future work.
Cost supports nonnegative values with up to two decimal places and an explicit
three-letter currency code. It does not convert currencies or calculate totals.

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

Schema version 2 adds vehicles, mileage/service history and cached VIN results.
Opening a version-1 database first creates a uniquely named `*.pre-v2-*.sqlite3`
backup beside it, then migrates transactionally. Existing settings survive.
Newer schemas cause a startup failure instead of a downgrade.

Backups use SQLite's snapshot API and refuse to overwrite existing files.
In Settings, **Restore database** accepts unmodified OpenWrench schema 1 or 2
backups up to 256 MiB. Confirmation defaults to No. Restore validates schema,
integrity, foreign keys and record values before saving a unique adjacent
`*.pre-restore-*.sqlite3` safety backup. Replacement runs in one SQLite transaction;
failure rolls back changes. The Garage and theme refresh immediately. Schema-1
backups contain settings only, so restoring one replaces the Garage with an
empty Garage. Newer, unrelated or modified schemas are rejected. Restore the
safety backup through the same interface to undo a successful restoration.

**Export Garage JSON** retains exact text, nulls, UUIDs, ISO dates/timestamps,
mi/km units and integer `cost_cents` with currency. **Export Garage CSV ZIP**
contains `vehicles.csv`, `odometer_readings.csv`, `service_history.csv`, a versioned
manifest and field guidance. Join each record's `vehicle_id` to `vehicles.id`.
CSV uses UTF-8 with BOM, empty cells for absent values and an extra apostrophe
before formula-like text or leading apostrophes. Remove one leading apostrophe
programmatically to recover escaped text. JSON distinguishes null from empty text.
Exports refuse to overwrite existing files. Neither format includes settings or
VIN cache, and neither is an import format; use SQLite backup/restore for recovery.
Backups and exports contain private vehicle information. Store them accordingly.

Replacing the application directory leaves
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

## Repository workflow

Repository: https://github.com/Spacecowboy-28/openwrench-desktop

Milestone 1 merged through PR #1. Milestone 2 uses `dev/milestone-2` and a separate
review pull request. Do not merge automatically. See DEVELOPMENT_STATUS.md and
docs/MILESTONE_2.md for current scope, tests and remaining work.

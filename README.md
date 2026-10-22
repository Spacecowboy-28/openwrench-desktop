# OpenWrench Desktop

A local, open-source automotive workshop application. Current development
version: **0.3.0.dev1, Repair Library**.

Add, view, edit and delete vehicles in the existing native PySide6 application.
Record dated odometer readings and service history, including notes, parts,
optional cost and currency. SQLite stores all records locally. Internet access
is optional. Explicit NHTSA VIN/recall requests and external repair-source links
use the network; imported PDF/HTML manuals and their text search work offline.

The application ships no factory repair specifications, simulated scans or
hardware driver. Users supply lawful manuals and source-backed schedules. No server, browser, subscription or account is required.

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

## Use Repair Library

Choose a Garage vehicle, then **Open Repair Library**, or use the sidebar.

- **Local manuals:** Import a lawful PDF, HTML/HTM entry page or HTML ZIP archive, enter its title/category and provenance,
  and select one or more vehicle associations. Edit details to change associations.
  Leave unknown applicability fields blank. An association is not factory verification.
- Search document titles/descriptions and extracted page text. Results identify
  documents and pages. Categories and the selected vehicle filter results. Choose
  **All vehicles** to browse unassociated documents as well.
- **Open document (PDF):** Change page or zoom, drag to pan diagrams, search extracted text,
  bookmark a page, or open the recovered local file in your system PDF viewer.
- **Rebuild index** re-extracts the selected PDF without replacing metadata. A
  failed/cancelled reindex preserves the previous index. Image-only PDFs report
  no extractable text; OCR is not implemented. Imports reject encrypted/malformed
  files, duplicate hashes, files above 50 MiB, more than 5,000 pages or more than
  20 MiB of extracted text. PDF tasks run in isolated, cancellable processes.
- **Locate original** repairs missing stored bytes only from an exact hash match.
  Missing viewing files recover from SQLite on the next open. Document removal
  confirms first, leaves the original source untouched, removes metadata/index/
  associations/bookmarks, and retains any existing local viewing copy.
- **Online sources:** LEMON and CHARM open browser references only. The UI labels
  catalog evidence and uncertain availability. Lexus AWD/RWD and Ford 2WD/4WD
  references do not become confirmed matches with unknown configuration.
  Tundra/Civic receive catalog links, not invented vehicle-manual coverage.
- **Fetch NHTSA recalls** explicitly sends year/make/model, never a VIN, to the
  official recall endpoint. Results include campaign IDs and source links.
  Manufacturer communications use official portal/dataset references, not full
  factory-manual access or imported TSB contents. A failed connection leaves the
  offline library usable.
- **Maintenance:** Add a user-defined schedule or a manufacturer schedule you
  verified against a cited publication. Enter distance/month intervals, conditions,
  provenance and optional specifications/procedure. Select an actual Garage service
  record or enter an explicit baseline. Dates clamp to month end. Due reminders
  appear inside Repair Library; no background OS notifications run while closed.
  Unknown baseline/current reading or unit mismatch produces a coverage gap.

No factory interval, torque value, fluid capacity or specification is generated.
See [source research](docs/MILESTONE_3_SOURCES.md) and the
[Windows acceptance guide](docs/MILESTONE_3.md).

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

Schema version 2 added vehicles, mileage/service history and cached VIN results.
Schema 3 adds Repair Library records and FTS5. Existing workspaces receive a
verified `*.pre-v3-*.sqlite3` snapshot before the transactional schema-3 migration.
Opening a version-1 database first creates a uniquely named `*.pre-v2-*.sqlite3`
backup beside it, then migrates transactionally. Existing settings survive.
Newer schemas cause a startup failure instead of a downgrade.

Backups use SQLite's snapshot API and refuse to overwrite existing files.
In Settings, **Restore database** accepts unmodified OpenWrench schema 1, 2, 3 or 4
backups up to 1 GiB. Confirmation defaults to No. Restore validates schema,
integrity, foreign keys and record values before saving a unique adjacent
`*.pre-restore-*.sqlite3` safety backup. Replacement runs in one SQLite transaction;
failure rolls back changes. The Garage and theme refresh immediately. Schema-1
backups contain settings only, so restoring one replaces the Garage with an
empty Garage. Schema-2 backups restore Garage records and an empty Repair Library.
Newer, unrelated or modified schemas are rejected. Restore the
safety backup through the same interface to undo a successful restoration.

**Export Garage JSON** retains exact text, nulls, UUIDs, ISO dates/timestamps,
mi/km units and integer `cost_cents` with currency. **Export Garage CSV ZIP**
contains `vehicles.csv`, `odometer_readings.csv`, `service_history.csv`, a versioned
manifest and field guidance. Join each record's `vehicle_id` to `vehicles.id`.
CSV uses UTF-8 with BOM, empty cells for absent values and an extra apostrophe
before formula-like text or leading apostrophes. Remove one leading apostrophe
programmatically to recover escaped text. JSON distinguishes null from empty text.
Export format 3 adds document metadata, vehicle configuration/associations,
bookmarks and schedules. It excludes document bytes and extracted third-party text.
Exports refuse to overwrite existing files. Neither format includes settings or
VIN cache, and neither is an import format; use SQLite backup/restore for recovery.
Backups and exports contain private vehicle information. Store them accordingly.

SQLite backups include PDF bytes, complete imported HTML bundles, page text and all library metadata. They are
private recovery files, not redistribution archives. Viewing copies live in the
adjacent `openwrench.documents` directory, named by SHA-256. The database holds
canonical recovery bytes so backup/restore is self-contained across computers.
Viewing copies materialize on demand. The app retains cached copies after removal
or restore rather than silently deleting files. Close the app before manually
removing unneeded cached copies. A changed local copy triggers an error; move it
aside to preserve it, then open the document again to recover its stored copy.
Backing up/restoring a large SQLite file still runs synchronously in Settings.

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

Milestones 1 and 2 merged through PR #1 and PR #3. Milestone 3 uses
`dev/milestone-3` and references Issue #2. Keep the issue open through acceptance
testing. Do not merge automatically. See DEVELOPMENT_STATUS.md and
docs/MILESTONE_3.md for scope, tests and remaining work.

## Offline HTML manuals (Milestone 3 extension)

Use **Import PDF / HTML / ZIP** in Repair Library for a PDF, an HTML/HTM entry
page, or a ZIP containing a manual. Use **Import HTML Folder** to select an
entire manual folder — the folder tree, nested subfolders, stylesheets, images
and other supporting files are collected automatically, so you do not have to
pick files one at a time. Originals remain untouched; nothing is written into or
deleted from the selected folder.

**Import HTML Folder** walks the selected directory (never following a symlink
or Windows junction) and imports every permitted file with its relative path, so
navigation links, images and stylesheets keep working. Pages that no other page
links to are imported and indexed too, so you can reach the complete manual from
the section list. The entry page is `index.html`/`index.htm` when present,
otherwise `default`/`toc`, otherwise the shallowest page; if the choice is
ambiguous OpenWrench says which page it used and why. After a folder import an
**Import report** explains anything the offline viewer cannot show: missing
files and anchors, external URLs, files that were stored but not displayed
(scripts, web fonts, data files), files the bundle cannot store, and items
skipped for safety. A folder with no HTML pages is rejected with a clear message
rather than importing nothing.

ZIP import applies the same rule: ordinary files a manual ships that the viewer
cannot use (`Thumbs.db`, `desktop.ini`, `.DS_Store`, RTF or extensionless
resources) are skipped and reported rather than failing the whole import, while
unsafe or malicious entries (path traversal, absolute paths, Windows device
names, symlinks, encrypted, duplicated or case-aliased entries) are still
rejected. macOS `__MACOSX/` sidecars and AppleDouble `._*` forks are ignored as
metadata, so they can never masquerade as a second `index.html`.

An HTML entry-page import collects reachable files below its parent directory
only; use **Import HTML Folder** for a full supplied folder tree. Enter source,
rights and vehicle associations yourself; a title is not proof of completeness or
vehicle fit.

**Open document** provides static HTML navigation, Back/Forward/Home, section
selection, zoom and section bookmarks. Search results show the document UUID
relationship, file path and section, then open the matching section. The resource
report lists missing files/anchors and blocked external URLs. No missing reference
report proves completeness: absent script-generated navigation is unknowable.

The native QTextBrowser renderer has no JavaScript engine. Scripts, forms,
iframes, active SVG and remote/file URLs are blocked. Basic HTML tables, typography,
CSS and static raster/SVG diagrams work (SVG: UTF-8, up to 1 MiB). Browser layout CSS, script-generated
content/navigation, CSS imports/background images and embedded multimedia are
unsupported. Fonts and other accepted supporting files remain in the stored
bundle but do not gain execution or arbitrary file access. No WebEngine is needed
for this static scope. User manuals are never scraped or included in the repo.

Bundle limits: 128 MiB stored, 100 MiB expanded, 10 MiB per member, 2,000 entries,
5,000 indexed sections and 20 MiB text. A folder import additionally bounds the
walk at 20,000 directory entries and 32 nesting levels. Exceeding any limit stops
the import with a message naming the limit, so no partial manual is stored. A
declared ZIP size above the budget rejects the archive; a header that lies about
its size is caught when the member is read,
so no compression-ratio heuristic is applied and repetitive generated manuals
(torque tables, repeated inline styles) import normally. Unsupported
member extensions reject the archive with a filename. HTML/HTM, CSS, common raster
images, SVG, JS, TXT, font files, JSON/XML/Markdown/source maps are accepted as
stored data; only sanitized HTML/CSS and approved images are rendered. Unsafe
paths, links, special files, Windows aliases, duplicate names and encrypted
entries reject the archive. Imports run in cancellable worker processes; bundle
reading and reference inspection also run in the worker so opening a large manual
never blocks the interface.

Schema 4 adds document format and stable HTML section mappings. Existing PDFs
retain their IDs/bookmarks. Upgrade creates a pre-v4 SQLite backup; complete
backups contain bundles and restore recreates missing managed viewing folders.
JSON and CSV export metadata/section paths only, never manual text or resources.
Resource reports are recomputed from the stored bundle. Large bundle inspection
and page rendering still have bounded synchronous UI work.

See [Milestone 3 acceptance](docs/MILESTONE_3.md) for Windows update instructions
and the offline HTML/PDF acceptance checklist.

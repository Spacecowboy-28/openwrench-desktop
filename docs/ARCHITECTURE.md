# Architecture decision 0001

Status: accepted for milestone 1. Review again before hardware integration.

## Decision

Use Python 3.12, PySide6 Essentials (Qt Widgets), SQLite from Python's standard
library, and PyInstaller directory bundles. Separate UI, storage, source
providers, and diagnostic adapters. No HTTP listener or web renderer exists.

| Option | Advantages | Cost | Decision |
| --- | --- | --- | --- |
| Tauri 2 + React + Python sidecar | Web UI reuse, small host shell, installer tooling | Rust/Node/Python builds, sidecar supervision, IPC authorization, target-specific sidecar packaging | Reconsider for future mobile/web needs |
| Python + PySide6 | One language, native desktop controls, direct Python diagnostics, official Qt bindings | Larger bundles, LGPL obligations, desktop-specific UI | Adopt |
| Python + Tkinter | Small dependency surface | More custom work for document viewing and future plots | Exclude for this project |

Tauri officially supports embedding PyInstaller-built sidecars. It is feasible,
not rejected as impossible. For this beginner-maintained offline project,
removing the extra process and two language toolchains is a useful simplification.
Source: https://v2.tauri.app/develop/sidecar/
Qt deployment: https://doc.qt.io/qtforpython-6/deployment/index.html

## Component boundaries

`app.py` owns lifecycle, platform data paths, logging and startup failures.
`ui.py` renders native widgets and delegates persistence to `Store`.
`storage.py` owns transactions, schema checks and SQLite snapshots.
`providers.py` defines typed vehicle applicability and repair-source boundaries.
`diagnostics.py` defines a read-only adapter contract. The diagnostic contract does not implement a vehicle driver. Repair providers
now expose metadata and external references, without a scraper or content mirror.

Future serial, network, PDF indexing and polling work must use a worker thread
or process with bounded timeouts and Qt signals back to the UI. SQLite connections
remain in their owning thread. Serial reads must never block the GUI event loop.

Later modules use stable local IDs, not make/model strings, for record ownership.
Store measurements with explicit units. Preserve VIN decoding errors and unknown
engine/trim values. Every imported specification needs source, license, exact
applicability and verification metadata. Keep observations separate from causes.

## Licensing boundary

Our original code is MIT. The current application imports no GPL-only automotive
library. Qt is dynamically loaded under applicable LGPLv3 terms. Use replaceable
shared libraries, preserve attribution and license texts, and provide matching
source/build instructions when distributing binary bundles. Do not assume a
sidecar automatically removes copyleft obligations. If python-OBD becomes the
best future option, review its exact license and the entire distributed
combination before integrating it or changing the overall distribution license.

## Packaging and upgrade policy

Development builds use onedir bundles for inspectability and replacement of
shared libraries. No auto-update endpoint, code signing key, release upload, or
installer exists in milestone 1. CI builds on Windows and Linux separately.
Milestone 6 adds a Windows installer, install/upgrade/uninstall validation,
runtime attribution/source inventory, signing decision, and an approved release.
macOS needs a native build runner and testing before claiming support.

Data lives outside the installation directory. Database migrations run before
window construction. Reject newer schema versions. Before future destructive
migrations, create and verify a backup, migrate in a transaction, and retain a
recovery path. Schema 1 to 2 adds Garage tables with a pre-upgrade snapshot.

## Milestone 2 extension

`garage.py` owns validated vehicle/history operations over the existing Store.
`garage_ui.py` owns native forms, tables and delete confirmation. `vpic.py` uses
QtNetwork's asynchronous event loop, so VIN lookups do not block the UI or move
SQLite connections across threads. Closing a form or changing VIN/year aborts
in-flight requests. A reply never applies automatically to a changed vehicle.

Schema 2 adds UUID vehicles, unified dated mileage/service entries and VIN cache.
Foreign keys cascade history on vehicle deletion. VINs and normalized Garage
names have unique indexes. Monetary values use integer cents. Units live on the
vehicle and lock after history starts. Mileage chronology checks run inside an
IMMEDIATE transaction. No unsupported ECU or repair-data functions were added.

`transfers.py` creates a consistent read snapshot for JSON/CSV export and validates
backup schema and records. Restore opens the selected file read-only, snapshots
and migrates it in a temporary workspace, then replaces records transactionally
through the original Store connection. Existing Garage objects keep their valid
connection. A verified safety backup precedes replacement; concurrent commits
from another connection cause cancellation. Strict schema matching rejects extra
triggers, views and tables. No imported schema executes against the live workspace.

## Milestone 3 extension

`library_schema.py` defines transactional schemas 3 and 4. `library.py` validates
provenance and associations, stores documents, manages FTS5 page search and
recovers viewing files. `maintenance.py` owns explicit schedule/baseline rules.
`providers.py` exposes a ReferenceProvider protocol and provider registry, alongside
the original contracts. Plugins return OnlineReference metadata without changing
core UI/storage. Provider exceptions become availability messages.

`library_ui.py` supplies native tabs, forms and a QGraphicsView page viewer.
`library_tasks.py` starts QProcess jobs; `pdf_worker.py` owns per-process SQLite
connections and `pdf_engine.py` performs PDFium extraction/rendering. PDFium is
not called concurrently in GUI threads. Rendering has a 30-second deadline,
other document tasks five minutes. Cancellation terminates the worker. SQLite
transactions preserve either the complete committed import or no partial import.
A cancelled late task might already have committed; the UI refreshes and says so.
No PDF JavaScript, links or embedded attachments execute in the viewer.

Documents have UUIDs and unique SHA-256 hashes. The database holds canonical PDF
bytes and indexed page text, so SQLite backup/restore is an atomic recovery unit.
The adjacent `<database stem>.documents` directory holds content-addressed viewing
copies. Missing copies regenerate offline. Existing changed copies are never
silently overwritten, and removing records leaves cached files for explicit user
cleanup. Original import paths are never deletion targets.

Schema 3 adds vehicle_configuration, documents, document_files, document_vehicles,
document_pages, bookmarks and schedules, plus FTS5 and its shadow tables/indexes.
Foreign keys preserve vehicle ownership and clear removed procedure/service links.
Restoration validates app schema, record metadata, hashes, ownership and size
limits in an isolated copy. It rebuilds FTS from validated page records within the
same replacement transaction, retaining existing Store/Garage handles.
Export format 3 includes user-owned metadata, UUID relationships and provenance,
but omits document bytes and extracted text. Export does not load PDF blobs.

Maintenance uses explicit intervals. It follows a selected service record's date
and odometer, and captures a baseline snapshot when linked. Deleting the service
clears the link but retains the saved baseline; users edit the baseline to remove
it. Schedules never infer completion from similar service titles. A unit mismatch
prevents mileage due comparisons, and time intervals clamp to month end.
Reminders run when the Repair Library refreshes, not as an OS/background service.

`recalls.py` uses asynchronous QtNetwork for explicit year/make/model NHTSA
requests, with deadline/size/redirect bounds and stale-reply cancellation.
LEMON/CHARM remain browser-only providers due unresolved coverage/access rights.
No data from a model response substitutes for manufacturer technical information.


### Static HTML bundles

`html_bundle.py` validates bounded ZIP entries and reachable local HTML resources,
canonicalizes bundles, indexes stable file/anchor sections and audits references.
Schema 4 retains original canonical ZIP bytes in `document_files`; `html_sections`
maps FTS page integers and bookmarks to paths/anchors. Existing schema-3 DDL stays
unchanged so strict restore validation recognizes old backups. Migration adds a
format column (default PDF) and the section table transactionally after a snapshot.
Restore revalidates bundle bytes and recomputes section mappings before replacement.

`html_ui.py` uses QTextBrowser, never Qt WebEngine. An allowlist strips active HTML,
URL-bearing CSS and unsupported SVG features. Custom bundle URLs go through a
resource loader with no superclass/network/local-file fallback; source navigation
is overridden, and static images have decoded-pixel limits. JS remains inert
stored data, never executed. Only links within the imported bundle navigate.
A fresh staging folder plus rename materializes validated files; existing cached
files must match stored bytes. The viewer reads canonical validated database bytes,
not arbitrary cached files. Import/extraction remains in the existing QProcess
worker; sanitized page layout/resource inspection has bounded GUI-thread work.

Qt supports a limited rich-text subset, not general browser layout. This tradeoff
avoids adding a Chromium scripting/network engine for static documentation:
https://doc.qt.io/qt-6/qtextbrowser.html
https://doc.qt.io/qt-6/richtext-html-subset.html

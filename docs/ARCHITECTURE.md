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
`diagnostics.py` defines a read-only adapter contract. Neither contract module
implements a vehicle driver or data service yet.

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

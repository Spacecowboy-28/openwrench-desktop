# Vehicle Garage: review guide

## Functionality

Native forms cover vehicle add/edit/view/delete and mileage/service history
add/edit/delete. Deleting a vehicle requires confirmation and cascades its
history. Fields include optional VIN, engine/trim, notes, distance units and
Garage name. The list shows the highest odometer reading without inventing zero
for an unknown reading. Every record persists in the existing SQLite workspace.

Four optional starting profiles support the initial vehicles. Tundra and Civic
engine/trim stay unknown. The other profiles use only the supplied 3.5L V6/F Sport
and 4.6L V8 details. Arbitrary makes and models use the same interface.

Duplicate protection normalizes VIN case and Garage-name whitespace/case.
Separate vehicles of the same make/model require different Garage names.
Chronology validates backdated odometer and service readings against earlier
and later records. Dates cannot be future dates. Currency is a label, not a
conversion or official currency-code registry. Service costs retain exact cents.

## NHTSA integration

Primary API documentation: https://vpic.nhtsa.dot.gov/api/ .
The provider requests `DecodeVinValues/<VIN>?format=json` and includes modelyear
when entered. The UI explains this disclosure beside the explicit Decode button.
No lookup runs on startup or manual vehicle save.

QtNetwork executes asynchronously on its event loop. Requests refuse redirects,
set a 10-second transfer timeout, enforce a 15-second total deadline and reject
responses over 1 MB. Changing VIN/year or closing the form cancels the request.
Results never overwrite manual values automatically. A successful decode enables
an explicit Apply-to-blanks action. NHTSA errors stay visible in the preview and
cached response. Unknown engine/trim remain empty.

The local cache lasts 30 days per VIN/year. Tests control replies to stay
deterministic and avoid sending private or fabricated owner data to the service.
The user confirmed live VIN decoding on Windows Python 3.12.10 for the baseline.

## Migration and recovery

The version-1 database first receives a unique adjacent `.pre-v2-<id>.sqlite3`
snapshot. All version-2 DDL then runs in one transaction. A failed DDL statement
rolls back tables and schema version. New workspaces migrate without a redundant
backup. Later launches do not re-run the migration. Existing settings remain.
The test suite covers both successful upgrade and injected migration failure.

## Automated validation

Local Linux x86_64 validation, Python 3.12 and PySide6 6.8.3:

- 83 tests passed, including the original 60 regression tests.
- Source distribution and wheel: built with `python -m build --no-isolation`.
- Linux native directory bundle: built with `python scripts/build_desktop.py`.
- Qt offscreen Garage and add-vehicle forms visually inspected.
- Physical Windows display, installer and USB testing remain outside this run.

Coverage includes the previous foundation tests plus migration preservation and
rollback, initial profiles and another make, CRUD/cascade, duplicates, invalid
fields, historical mileage, exact service costs, backups, native forms and
cancellation, preset switching, VIN parsing, mismatched response, offline cache,
network errors, deadline cancellation, stale responses and size limits.

CI runs Windows and Linux tests/builds on the PR. Its results are separate from
local Linux checks. No public binary or installer is published by this branch.

## Manual desktop acceptance

1. Open an existing version-1 workspace. Confirm its theme and adjacent backup.
2. Add a Tundra, Civic, Lexus and F-150 from the presets. Confirm unknown values.
3. Enter a vehicle of another make manually with networking unavailable.
4. Attempt a duplicate name and VIN. Confirm the form stays open with a message.
5. Add/edit a mileage record and service, then close and reopen the application.
6. Backdate a conflicting reading and confirm the rejection. Correct and save it.
7. Request a VIN decode, inspect results, apply blanks, then review before saving.
8. Cancel a decode or edit the VIN during lookup. Confirm no stale field changes.
9. Save a backup. Cancel a deletion, then confirm a deletion on a test vehicle.

No VINs, owner service records, private documents or development databases belong
in the public repository. Use an isolated workspace for acceptance tests.

The bundled Linux executable also launched from outside the source directory
with Qt's offscreen platform. It returned exit 0, `visible: true`, version
`0.2.0.dev2` and schema 2. This validates native startup, not a physical display.

## Export and restore acceptance

The user reported baseline Windows Python 3.12.10 acceptance at commit fb2258c:
startup, persisted vehicles, live VIN decoding, mileage, service creation/editing,
SQLite integrity/backup, both themes and all 60 baseline tests. The new controls
require a separate Windows desktop check; automated Qt tests run offscreen.

The 23 added tests cover JSON/CSV values and joins, Unicode and multiline text,
formula escaping, empty Garage export, refusal to overwrite files, partial-write
cleanup, malformed records/backups, schema incompatibility, unexpected triggers,
orphan records, restoration of UUIDs/settings/cache/history, schema-1 private
migration, failure rollback, safety-backup failure, cancellation, Garage refresh,
theme/integrity controls and singular/plural headings. Existing tests still cover
vehicle/service editing, deletion confirmation and migration rollback.

Use a disposable workspace and synthetic records for these steps:

1. Export JSON and CSV ZIP with vehicles in mi and km, dated readings and service
   records with/without costs. Check IDs, dates, currencies and integer cents.
2. Extract CSV files and join history.vehicle_id to vehicles.id. Check Unicode,
   multiline notes and the documented formula-prefix escaping.
3. Save a SQLite backup, add a test vehicle, cancel Restore and verify no change.
4. Restore the backup and confirm the new vehicle disappears, original IDs and
   history remain, theme refreshes, and the reported safety backup exists.
5. Restore the safety backup to recover the test vehicle; restart and check data.
6. Try a text file, unrelated SQLite database and newer-schema file. All should
   report failure without replacing records. Never edit your real database.
7. Check one-vehicle grammar, edit a service, cancel a delete, change themes and
   run integrity checks after restoration.

Restore supports exact application schemas 1/2 up to 256 MiB and preserves the
selected source. Schema 1 restores settings and an empty Garage. Export is not
an import or full recovery format. JSON preserves null versus empty text; CSV
uses empty cells for both. Large transfers run synchronously. No schema bump is
needed for these features; existing schema-2 records remain unchanged.

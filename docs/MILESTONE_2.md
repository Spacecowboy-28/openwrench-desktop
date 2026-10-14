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
Live service reliability and clean-machine TLS behavior need user acceptance.

## Migration and recovery

The version-1 database first receives a unique adjacent `.pre-v2-<id>.sqlite3`
snapshot. All version-2 DDL then runs in one transaction. A failed DDL statement
rolls back tables and schema version. New workspaces migrate without a redundant
backup. Later launches do not re-run the migration. Existing settings remain.
The test suite covers both successful upgrade and injected migration failure.

## Automated validation

Local Linux x86_64 validation, Python 3.12 and PySide6 6.8.3:

- 60 tests passed in 1.73 seconds.
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
`0.2.0.dev1` and schema 2. This validates native startup, not a physical display.

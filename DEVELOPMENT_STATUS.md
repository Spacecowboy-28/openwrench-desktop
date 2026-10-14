# Development status

Session: 2026-10-14 (UTC). Version: 0.2.0.dev2.
Branch: `dev/milestone-2`, based on merged main
`76c15985a16330b156095a490c8c84da097d8a53`.

## Completed scope

Milestone 1 merged through PR #1. The existing PySide6 shell, SQLite database,
test suite, build pipeline and Git history remain intact.

Vehicle Garage now supports native add/edit/view/delete forms, optional starting
profiles, manual offline entry, optional vPIC VIN decoding, dated mileage and
service records, editable history, costs/currencies, notes and deletion
confirmation. No user records are seeded. Tundra/Civic engine and trim stay blank.

Schema 1 → 2 creates a verified pre-upgrade backup and preserves settings. UUID
records, foreign keys, unique VIN/name constraints and transactional chronology
checks protect local records. Existing backups include Garage data and VIN cache.
VIN lookup is asynchronous, bounded and cancellable. Cache entries expire after
30 days. Returned data requires review before filling blank form fields.

Settings now exports versioned JSON and related CSV tables in a ZIP. Stable UUIDs,
units, dates and integer costs/currency survive export. Validated SQLite restore
supports schema 1/2, confirmation, a mandatory safety backup, transactional rollback
and immediate Garage/theme refresh. The Garage heading uses singular for one vehicle.

## Validation and delivery

Local tests: 83 passed. Source distribution, wheel and Linux native bundle built.
See `docs/MILESTONE_2.md` for evidence and manual review steps.
Changes update existing PR #3 from dev/milestone-2 to main. The user
must review and merge. No installer, release or automatic merge is authorized.
GitHub CI is authoritative for the remote commit's Windows/Linux build status.

## Remaining limitations

- JSON/CSV import is not implemented. Restore accepts only supported OpenWrench
  SQLite schemas up to 256 MiB; CSV represents null and empty text identically.
- Export/restore run synchronously; large workspaces could briefly pause the UI.
- Service attachments, schedules and repair specifications belong to Milestone 3.
- VIN validation checks format, not the checksum. vPIC reports decode issues.
  Partial/invalid results never enable Apply. Older short identifiers need a
  blank VIN and notes. Server availability and regional coverage vary.
- The cache is independent of vehicle deletion and holds VIN responses locally.
- Odometer rollover/replacement and unit conversion are not implemented. Units
  lock after history exists. Same-day readings lack time ordering.
- Costs use integer cents and a three-letter currency label, without conversion.
- No hardware communication, public installer, signing or binary license audit.
- Tests use synthetic VINs and controlled replies, not private owner records.

## Exact next task

Review PR #3 without automatic merge. The user confirmed Windows Python 3.12.10
startup, persistence, live NHTSA decoding, mileage, service editing, integrity,
backup, both themes and all 60 baseline tests at fb2258c. New export/restore
controls still need Windows desktop acceptance using the checklist in
`docs/MILESTONE_2.md`. After review and merge, begin Milestone 3.

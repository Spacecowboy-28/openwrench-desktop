# Development status

Session: 2026-10-13 (America/Chicago). Version: 0.2.0.dev1.
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

## Validation and delivery

Local tests: 60 passed. Source distribution, wheel and Linux native bundle built.
See `docs/MILESTONE_2.md` for evidence and manual review steps.
Changes are prepared for a pull request from dev/milestone-2 to main. The user
must review and merge. No installer, release or automatic merge is authorized.
GitHub CI is authoritative for the remote commit's Windows/Linux build status.

## Remaining limitations

- Restore UI and JSON/CSV export remain original-roadmap follow-ups, outside
  this requested Garage implementation. Manual backup inspection is documented.
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

Review this PR and complete desktop acceptance on Windows: add each initial
profile, reopen the app, edit records, perform an explicitly requested VIN lookup,
save a backup, and check deletion/cancellation. After merge, implement the
remaining Garage restore/export follow-up with validated backup identity,
schema/foreign-key checks, a recovery backup and atomic restore behavior before
starting Milestone 3 data imports. Keep unrelated research out of this branch.

# Development status

Session: 2026-10-13. Version: 0.1.0.dev1. Branch: `dev/milestone-1`.

## Scope

Milestone 1 local implementation exists. GitHub publication and Windows build
verification remain blocked or pending. This is a desktop foundation, not a
repair-data release or a completed garage/diagnostic application.

Implemented: native Qt shell, functional Settings page, persistent dark/light
theme, SQLite schema migration, newer-schema rejection, integrity check, verified
backups with overwrite prevention and failed-write cleanup, rotating logs,
startup failures, isolated native smoke test, provider and read-only diagnostic
interfaces, package metadata, source/wheel build, same-platform PyInstaller
build, Windows/Linux CI workflow, contribution/security/research/license docs.

No simulated data or scan is presented as a real result. No personal VINs,
documents or records are included. Four public development vehicle profiles
retain unknown configurations as null. They do not represent repair coverage.

## Verification

Final results are recorded in docs/TEST_RESULTS.md after the validation pass.
Linux is the only platform available locally. Offscreen Qt rendering proves the
event loop and widget construction, not interaction with a physical display,
clean Windows installation or USB adapter. GitHub Actions has not run yet.

## GitHub

Connected profile lookup succeeded. Accessible repository list was empty.
Available tools offered no repository-creation operation. No remote, pull
request, release or installer was published. Local commits and a Git bundle
preserve the development branch until an accessible repository exists.
See docs/GITHUB_SETUP.md for the concrete next step.

## Exact next implementation task

After connecting the new repository and running its Windows/Linux CI, begin
Milestone 2 with a transactionally migrated `vehicles` table and native
add/edit/delete forms. Add an odometer-event table with units and timestamps,
UUID identifiers, validation, deletion confirmation and reopen/persistence
tests. Exercise the four example profiles and an unrelated vehicle. Do not
seed user data automatically. Then implement a background vPIC provider with
timeouts, caching, retained decode errors and manual fallback, followed by
validated restore and JSON/CSV export. Keep VINs out of logs and public fixtures.

## Remaining gates

- Windows native build and startup checks after repository access.
- Physical-display Linux and clean-machine Windows testing.
- Installer/upgrade/uninstall testing and complete native-bundle license/source
  compliance before binary distribution in milestone 6.
- Actual hardware access for USB testing in milestone 4.
- Source-rights and vehicle-applicability review before technical-data imports.
- Dependency vulnerability review and exact platform lockfiles before release.

Build/run commands are in README.md. Do not infer installer or hardware success
from a source test or an offscreen smoke test.

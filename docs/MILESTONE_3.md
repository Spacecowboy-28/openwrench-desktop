# Milestone 3: Repair Library review and acceptance

Branch: dev/milestone-3. Baseline: main merge 04c9b881 (Milestone 2 PR #3).
Related research/acceptance tracker: https://github.com/Spacecowboy-28/openwrench-desktop/issues/2
Keep Issue #2 open until acceptance finishes. No automatic merge or public release.

## Implemented scope

Native PySide6 library tabs support Garage vehicle selection, document metadata
and multiple associations, local PDF import/viewing, categories, FTS page search,
page bookmarks, external references and maintenance schedules. The original
Garage, vPIC lookup, service editing/deletion, themes, backup/restore and exports
remain covered by the baseline regression suite.

PDFium processes validate/extract/render lawful local files outside the GUI loop.
A five-minute document task timeout and 30-second page-render timeout bound work.
Cancellation preserves existing metadata/indexes and original source files.
Imports commit PDF bytes, metadata, associations and text in one transaction.
A task cancelled after its commit remains visible; the UI explains this outcome.
Encrypted files need an unlocked lawful copy. Image-only documents remain viewable
but unsearchable until OCR becomes a future feature. Per-file limits: 50 MiB,
5,000 pages, 20 MiB total extracted text, 1 million characters per page.
Page rasters cap at 16 million pixels; zoom controls range from 50% to 400%.

## Provider and applicability limits

LEMON lists both 2015 GS 350 F Sport AWD and RWD. The specific manual requests
failed during research, so they remain catalog-listed references with unverified
procedure coverage. CHARM connectivity is intermittent; indexed 2006 Ford 4.6L
VIN W 2WD/4WD references remain conditional. Both providers open external links
only. No scraping, downloads or bundled manuals are implemented.

Tundra/Civic receive source catalog links with unknown coverage. The Lexus
Drivetrain stays unknown until the user enters it. The Ford VIN-engine designation
also stays unknown. Other makes use the same import/search/schedule features.
Comparison uses normalized exact strings, not inferred mechanical equivalence.
Unknown requirements produce Unknown/Partial states; incompatible fields produce
Not applicable. A user association never upgrades verification. Manufacturer
verification is explicitly a user-entered provenance declaration, not independent
validation by OpenWrench. Review the actual manual configuration before use.

NHTSA supplies explicit recall queries, campaign IDs and source links. Manufacturer
communications use official links, without claiming full factory manual access
or automatic TSB indexing. Network tests use synthetic responses, not owner VINs.

## Migration, export and recovery

Schema 2 to 3 receives a verified pre-v3 snapshot and transactional DDL. Tests
inject migration and restore failures and verify rollback/data preservation.
Schemas 1/2/3 restore through validation, safety backup and transactional data
replacement. Schema-1/2 restores replace the Repair Library with empty records.
Schema-3 backups include PDF bytes, metadata, schedules, bookmarks and page text.
Restore reconstructs FTS. Missing viewing files regenerate from recovered bytes.
Backup size limit: 1 GiB. Existing Settings backup/restore remains synchronous,
so large databases briefly pause the interface. Full-library archives/streaming
recovery for larger collections remain future work.

Export format 2 adds document metadata, associations, configuration, bookmarks
and schedules, including stable IDs/provenance. It excludes PDF bytes and extracted
text to avoid accidental third-party content redistribution. Export is not import.
CSV retains the documented null/empty-text and formula-prefix behavior.

## Automated validation

The merged baseline passed 83 tests. The Milestone 3 suite adds native worker,
PDF, provider, schedule, migration and recovery coverage with original synthetic
fixtures only. Run `python -m pytest -q` for the current count.

Coverage includes native import/render/zoom/search/bookmark interactions; metadata
editing, cancellation, dark/light themes, malformed/encrypted/duplicate/oversized
PDF rejection, scanned-page reporting, missing-file recovery and exact-file locate;
source metadata and multiple vehicles, title/category filtering, FTS snippets/page
references, exact/partial/incompatible applicability, provider exceptions, NHTSA
HTTP/network/stale reply behavior, month-end and mileage due calculations, schema-2
preservation, malformed schema-3 rejection, document/index rollback, cascade
relationships, metadata-only exports and portable self-contained restores.

Local source/wheel and native bundles build. CI checks Windows 2022 and Ubuntu
22.04 using Python 3.12, including packaged startup and actual packaged PDF
import, page search and rendering via scripts/check_packaged_library.py.
Offscreen Qt automation does not establish physical desktop acceptance.
No physical Windows test has run in this development session.

## Windows update instructions

1. In the working Milestone 2 app, use Settings to save a SQLite backup outside
   the project directory. Close OpenWrench.
2. Open PowerShell in your existing repository. Check for local edits:

   ```powershell
   git status --short
   ```

   If this lists changes, preserve/review them before switching branches. Do not
   reset or overwrite local work.
3. Fetch the new branch and switch to it:

   ```powershell
   git fetch origin
   git switch --track origin/dev/milestone-3
   ```

   If the local branch already exists, use `git switch dev/milestone-3`, then
   `git pull --ff-only origin dev/milestone-3` instead.
4. Update the existing Python 3.12 environment and run tests:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m openwrench
   ```

   If you do not have the virtual environment, create it first using
   `py -3.12 -m venv .venv`. Your SQLite data lives outside the checkout.
5. Confirm schema 3 in Settings and locate the adjacent pre-v3 backup. All Garage
   vehicles, unknown fields, mileage, service records and theme should remain.

## Manual acceptance checklist

Use an isolated test workspace for destructive checks:
`python -m openwrench --data-dir .\artifacts\m3-acceptance`.

1. Add the four initial profiles and an unrelated make/model. Keep unknown engine,
   trim and drivetrain blank. Open Repair Library from each Garage selection.
2. Import a lawful text PDF with a diagram and at least two pages. Record title,
   category, source/publisher, date if known, rights and applicability. Associate
   it with two test vehicles. Restart and verify all metadata and associations.
3. Search a repair term and a title. Filter by category/vehicle. Open a page result,
   change pages, zoom and drag the diagram. Search within the viewer, bookmark a
   page, then open the bookmark. Check your system PDF viewer opens the local copy.
4. Import an image-only PDF and confirm the no-extractable-text message. Try a
   malformed file, encrypted file and duplicate PDF. Confirm actionable failures
   without changes to existing documents. Cancel a large import and reindex.
5. Disconnect networking. Open/search existing local manuals. Reconnect for source
   links and an explicit recall query. Check campaign IDs and official links.
6. For the Lexus, leave drivetrain blank and inspect both candidate links. Enter
   RWD, confirm AWD shows Not applicable, then clear drivetrain again. Do not
   assume the host's manual is available if the browser fails to load it.
7. Create a user-defined maintenance item with a short test interval. Link a test
   Garage service record and procedure. Check next due values, change mileage,
   and confirm the in-app due reminder. Edit/delete a schedule without affecting
   service history. Do not treat test intervals as manufacturer guidance.
8. Edit metadata/associations. Cancel document deletion. Then confirm deletion on
   a test copy and verify Garage records survive. Original files remain untouched.
9. Back up the database, modify library records, restore and verify PDFs, searches,
   bookmarks, schedules, Garage and theme. Restore the safety backup to undo it.
   Test a schema-2 backup in the disposable workspace, then return to schema 3.
10. Close the app, move a viewing copy from the adjacent .documents directory,
    reopen its record and verify recovery. Test Locate original with the exact
    source and reject a different PDF. Never modify the live SQLite file manually.
11. Export JSON and CSV ZIP. Inspect document/vehicle IDs, references, units and
    schedules. Confirm no PDF bytes or extracted manual pages appear in exports.
12. Check both themes, Garage vehicle/service edits, deletion cancellation and
    database integrity. Record any failures in the review PR. Leave Issue #2 open
    until the acceptance review finishes.

## Deferred work

OCR, online manual downloading/indexing, verified factory-data imports, full TSB
API ingestion, background OS notifications and collections above the current limits
need separate follow-up. No diagnostics, installer, signing or release work starts
in this milestone. Existing Qt and PDFium binary-license review gates still apply.

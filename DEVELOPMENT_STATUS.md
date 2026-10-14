# Development status

Date: 2026-10-14. Version: 0.3.0.dev1. Branch: dev/milestone-3.
Main baseline: `04c9b881c9f73d84e2d5af2b80c740be967bfbc7`.
Milestones 1 and 2 merged through PR #1 and PR #3. The user reported successful
Windows acceptance of Milestone 2, including its export/restore follow-up.

## Implemented Milestone 3 scope

- Native Repair Library linked to existing Garage UUIDs, categories, metadata,
  multi-vehicle associations and configuration/applicability states.
- Lawful local PDF import, duplicate/content validation, isolated cancellable
  workers, offline FTS5 page search, native page/zoom/pan viewer and bookmarks.
- LEMON/CHARM browser references with explicit uncertain coverage/access labels.
  No scraping, automatic downloads or redistribution. Explicit NHTSA recall API
  queries retain campaign identifiers; manufacturer communications use official
  portal/dataset links, not a complete manual or TSB ingestion claim.
- User-defined or user-verified manufacturer schedules, cited provenance,
  conditions/specifications, linked service/procedure records, next-due values
  and in-app reminders. No invented technical values or preloaded factory data.
- Schema 3 with pre-migration snapshots and transactional rollback. SQLite holds
  canonical PDF bytes for self-contained backup/restore. Viewing files recover
  offline in a dedicated adjacent document directory. Restore validates schemas
  1/2/3 and rebuilds FTS. Metadata exports omit PDF bytes and extracted content.

## Validation and commits

Baseline: 83 tests passed before changes. Current local suite: 117 passed.
Source distribution, wheel and Linux native directory bundle built. Packaged
startup plus actual packaged PDF import, FTS search and rendering passed.
Native Repair Library and source-tab layouts were inspected with Qt offscreen.
No physical Windows testing occurred in this session. Windows/Linux CI performs
separate tests/builds/startup and packaged PDF worker checks on the review PR.

Functional checkpoint commits:
- aca7f67: schema, recovery, document/search and maintenance services.
- d92649e: native UI, isolated workers, recall requests and packaging checks.
- The review-completion commit adds regression cases and handoff documentation.

## Remaining limitations

LEMON's listed Lexus pages failed to load during research; CHARM access was
intermittent. Catalog links are not confirmed procedure coverage. Tundra/Civic
engine/trim/drivetrain remain unknown; Lexus drivetrain remains unconfirmed.
Exact-string applicability is conservative and does not infer mechanical aliases.
User verification labels record a declaration, not independent manufacturer review.

No OCR, manual-site downloading/indexing, imported TSB corpus, verified factory
schedule dataset, background OS notifications or diagnostics. PDF limits are
50 MiB/file, 5,000 pages, 20 MiB extracted text and 16 million pixels/render.
SQLite restore accepts files up to 1 GiB. Large Settings backup/restore operations
still run synchronously. Cached viewing copies remain until explicit user cleanup.
Schema-1/2 restores intentionally replace the Repair Library with empty records.

## Exact next step

Review the Milestone 3 PR and run the Windows desktop acceptance steps in
`docs/MILESTONE_3.md`. Keep Issue #2 open until acceptance completes. Do not merge
automatically, publish installers/releases, or begin Milestone 4. Research and
rights evidence lives in `docs/MILESTONE_3_SOURCES.md`; dependency notices live in
THIRD_PARTY.md. The app preserves all original user records and Git history.

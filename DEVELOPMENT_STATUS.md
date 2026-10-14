# Development status

Milestones 1 and 2 merged through PR #1 and PR #3. Main baseline:
`04c9b881c9f73d84e2d5af2b80c740be967bfbc7`. Milestone 2 passed desktop acceptance
reported by the user, including export/restore. The baseline has 83 passing tests.

Milestone 3 implementation is on `dev/milestone-3`, version 0.3.0.dev1.

## Functional checkpoint

Schema 3 adds document metadata/content, vehicle associations/configuration,
page indexing, bookmarks and maintenance schedules. SQLite backups remain
self-contained, including lawful user-imported PDF content. Export format 2 adds
user metadata while excluding document bytes and extracted content. Restore
validates schemas 1/2/3 and rebuilds FTS within its transaction.

Local imports, hash deduplication, PDF validation, page extraction/rendering,
vehicle-filtered FTS search and maintenance calculations are implemented.
Provider catalog links distinguish missing configuration and unverified coverage.
Source research and rights constraints appear in docs/MILESTONE_3_SOURCES.md.

## Exact next step

Finish native UI integration review, boundary/failure tests, documentation,
Windows/Linux package checks and the Milestone 3 pull request. New focused
backend/native tests: 26 passed locally. No physical Windows test has run here.
Do not merge automatically, publish a release, close Issue #2, or start Milestone 4.

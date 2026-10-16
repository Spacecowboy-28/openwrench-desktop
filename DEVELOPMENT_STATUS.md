# Development status

Date: 2026-10-16. Version: 0.3.0.dev1. Branch: dev/milestone-4-openhands.
Main baseline: `04c9b881c9f73d84e2d5af2b80c740be967bfbc7`.
Milestones 1 and 2 merged through PR #1 and PR #3. The user reported successful
Windows acceptance of Milestone 2, including its export/restore follow-up.
Milestone 3 is on `dev/milestone-3` (PR #4). Milestones 4 and 5 are implemented on
`dev/milestone-4-openhands`, which targets `dev/milestone-3`.

## Implemented Milestone 4 scope

- Versioned read-only PID catalog, sample/session status vocabularies and
  diagnostic-code records. No write, actuation or DTC-clearing mode exists.
- Deterministic simulator (`normal`, `misfire`, `electrical`, `comms`) with
  reproducible per-tick values and unsupported/timeout/disconnect behavior.
- Schema 5 sessions, bounded samples and codes, with pre-migration snapshots and
  transactional rollback.
- Off-thread `QThread` acquisition; the GUI thread owns persistence and SQLite
  never crosses a thread boundary.
- Native Diagnostics page with a dependency-free sensor graph, review/delete and
  a Settings opt-in toggle for experimental read-only USB hardware.
- Lazily-imported ELM/STN adapter with capability negotiation, multi-frame DTC
  parsing and a hard refusal of mode 04.

## Implemented Milestone 5 scope

- Schema 6 guided runs recording the decision-tree id/version and chosen path,
  so a diagnosis stays reproducible after a tree is revised.
- Two authored, versioned decision trees (misfire and electrical). They are
  reasoning aids, not manufacturer procedures, and assert no repair value:
  every outcome carries actions and a severity, and any specific test value is
  deferred to official service information.
- Deterministic, explainable guide engine: evidence is derived only from stored
  session data (codes and captured RPM/voltage series) and only *suggests* a
  branch. A user may always choose any option.
- Guided runs participate in export, validated restore and CSV export.

## Validation and commits

Baseline: 143 tests passed before these changes. Current local suite: 191 passed
under `QT_QPA_PLATFORM=offscreen`. Migration/rollback, malformed-restore
rejection, simulator determinism, protocol parsing via a fake transport,
off-thread recording and the guided walk are covered.

## Remaining limitations

No physical adapter or vehicle testing occurred. The USB path is experimental,
disabled by default and unit-tested only through a fake transport; no adapter
compatibility is claimed. Windows/Linux behavior was reviewed by inspection and
offscreen runs, not by packaged Windows acceptance. The decision trees are not
manufacturer procedures and must not be treated as such.

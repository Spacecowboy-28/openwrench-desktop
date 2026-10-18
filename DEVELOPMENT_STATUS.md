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

## Usability and quality pass (post-acceptance)

After physical Windows GUI testing of Milestones 4 and 5, this pass fixes and
improves:

- Diagnostics page is now inside a scroll area, so nothing clips at small window
  sizes or high display scaling; controls, readouts and the graph sit in titled
  cards with a consistent grid.
- The graph plots one selectable sensor at a time with labelled axes, unit and
  elapsed-time ticks; unrelated units are no longer overlaid. Live history is
  bounded per PID (`MAX_LIVE_POINTS`) and saved sessions load into the graph.
- Fixed `on_batch` calling `setText` on `None`: only real readout labels are
  updated, and history is captured for every supported PID.
- Codes now keep their real response mode. The acquisition layer reads modes
  03/07/0A separately, so a pending code is stored as mode 07, not mode 03.
- Guided diagnosis: options are full-width clickable buttons, both trees reach an
  outcome, unfinished runs can be saved and resumed (against their own tree
  revision), a run stays bound to its session, and selecting a guide that does not
  match the evidence shows an informational note without blocking the choice.
- Historical tree revisions are retained in `TREE_VERSIONS`/`get_tree`, so a run
  saved under an older tree version remains valid after a future update.
- Communication failure is distinct end to end: the simulator timeouts, then drops
  the link; the worker reports `disconnected`; the UI stores the session as failed.
  Cancellation and worker cleanup are covered by tests.

## Milestone 3 HTML hardening (found during a read-only audit of PR #4)

An engineering audit of the Milestone 3 offline-HTML code found and fixed:

- A compression-ratio heuristic in `read_zip` rejected legitimate high-ratio
  manuals (repetitive torque tables, repeated inline styles). It was removed; the
  declared per-member and total budgets are now the only contract, and a header
  that understates its size is still caught while the member is read.
- The archive budget was clarified: `MAX_ARCHIVE` (128 MiB stored) must exceed
  `MAX_TOTAL` (100 MiB expanded) so `pack()` always round-trips a legal bundle.
- `read_zip`'s path-conflict check was quadratic in the number of members; a
  parent-is-a-file lookup replaced the nested scan (deep-path case ~2690 ms to
  ~144 ms).
- `inspect()` now reports a page whose content was truncated because a
  `script`/`style`/`iframe` tag was left unclosed, instead of silently dropping
  the remainder. `StaticHTML` and the cheap `_DropScanner` share `DROP_TAGS`.
- GUI-thread blocking while opening a large manual was removed. The
  `materialize` worker operation now also loads the validated bundle directory
  (`read_bundle_dir`) and runs `inspect()` off-thread, returning
  `{root, issues}`; the GUI thread only walks the staged directory. Rendered pages
  are memoized in a bounded 32 MiB cache so Back/Forward/Home do not re-parse.

## Validation and commits

Earlier suite: 191 passed. Current suite: 220 passed under
`QT_QPA_PLATFORM=offscreen`. Migration/rollback, malformed-restore rejection,
simulator determinism, protocol parsing via a fake transport, off-thread recording,
code-mode tracking, bounded history, the guided walk/resume and both decision trees
are covered. The HTML hardening adds tests for high-ratio import/repack, archive
and stored-size budgets, unclosed drop tags, bundle-directory/read_zip parity with
symlink rejection, and a guard that opening a manual never re-reads the bundle on
the GUI thread.

## Remaining limitations

No physical adapter or vehicle testing occurred. The USB path is experimental,
disabled by default and unit-tested only through a fake transport; no adapter
compatibility is claimed. Windows/Linux behavior was reviewed by inspection and
offscreen runs, not by packaged Windows acceptance. The decision trees are not
manufacturer procedures and must not be treated as such.

# Milestone 4/5 GUI acceptance and usability pass

Date: 2026-10-16. Environment: Linux x86_64, Python 3.13, Qt 6.8.3.

Physical Windows GUI testing of Milestones 4 and 5 by the owner exercised the
Normal, Misfire, Electrical and Communication Failure simulator scenarios:
sessions started, stored samples and displayed data. P0301/P0300 and P0562 were
observed. Two defects and several usability issues found in that testing were
fixed here, each with a regression test.

| Check | Result | Scope |
| --- | --- | --- |
| `python -m pytest -q` | 220 passed, ~53 seconds | Full suite including new diagnostics/guide/UI and HTML-hardening tests |
| Diagnostics page scroll + layout | Passed | `QScrollArea` present; cards, grids, no clipping under offscreen rendering |
| Single selectable-sensor graph | Passed | One sensor plotted with axes/unit/time; selector switches sensor |
| Graph reflects saved session | Passed | Reviewed session loads stored points into the graph |
| `on_batch` None label bug | Fixed | Unlabeled PIDs captured in history, no `setText(None)`; regression test |
| Code mode tracking | Fixed | Pending code stored as mode 07, permanent as 0A; stored/pending/permanent tests |
| Guide completion (both trees) | Passed | Every root option reaches an outcome for misfire and electrical |
| Guide resume | Passed | Unfinished runs save, list, and resume against their own tree revision |
| Mismatched guide selection | Passed | Informational note shown; selection not blocked |
| Historical tree version | Passed | Run from an archived revision still validates after the live tree is revised |
| Communication failure | Passed | Timeout then `disconnected`; session stored as failed |
| Cancellation / worker cleanup | Passed | Stop leaves no active thread/recorder; status `interrupted` |
| HTML high-ratio manual import | Fixed | Ratio heuristic removed; repetitive manual imports and repacks; regression test |
| Archive/stored-size budgets | Passed | `MAX_ARCHIVE` > `MAX_TOTAL`; declared-size rejection tested |
| Deep-path archive read | Fixed | Quadratic conflict check replaced; ~2690 ms to ~144 ms on the deep-path case |
| Unclosed drop-tag reporting | Fixed | `inspect()` flags truncated pages; shared `DROP_TAGS`; regression test |
| Large-manual open responsiveness | Fixed | Bundle read + `inspect()` moved to the `materialize` worker; 32 MiB render cache; GUI-thread re-read guard test |
| Windows CI | Pending | Runs on `windows-2022`; this pass was developed and tested on Linux only |
| Physical Windows acceptance | Pending | Owner to re-verify the redesigned Diagnostics page and guides on Windows |

Offscreen Qt rendering is not a visual review; a packaged Windows launch and
physical inspection remain the acceptance step. Binary publication stays deferred
to the milestone-6 license/source audit.

# Milestone 1 validation

Date: 2026-10-13. Environment: Linux x86_64, Python 3.12.14, Qt 6.8.3.
See BUILD_ENVIRONMENT.json for the observed dependency and SQLite versions.

| Check | Result | Scope |
| --- | --- | --- |
| `python -m pytest -q` | 18 passed, 1.16 seconds | Persistence, migrations, failure handling, backups, native Qt interactions, subprocess launch |
| Editable package install | Passed | Python packaging and entry module |
| `python -m build` | Passed | Source distribution and Python wheel |
| `python scripts/build_desktop.py` | Passed | Bundled Linux native executable |
| Bundled executable `--smoke-test` from `/tmp` | Exit 0, status ok, visible true, schema 1 | Frozen executable starts outside source directory and enters Qt event loop |
| Source window render | Passed | Dark Garage and light Settings visually inspected at 1060×720 |
| Windows build / install | Not run | No Windows runner available locally; workflow prepared |
| Physical-display interaction | Not run | Qt offscreen rendering only |
| USB hardware | Not run | No adapter access; no driver implemented |

The final test suite covers first-run migration, theme persistence across reopen,
four invalid setting inputs, newer-schema rejection, preservation of unrelated
and corrupt databases, independent readable backup snapshots, overwrite
protection, missing-directory and failed-flush recovery, UI navigation/theme,
backup success/cancel/error interactions, repeated subprocess startup, and
non-hanging startup failure.

The packaged launch returned:

```json
{"status":"ok","version":"0.1.0.dev1","schema":1,"visible":true,"theme":"dark"}
```

Native build and rendered-window checks use Qt's offscreen platform. They are
not Windows installer acceptance tests, X11/Wayland certification, hardware
tests, or evidence of implemented repair coverage. Binary publication remains
deferred to milestone 6. GitHub Actions has not executed yet.

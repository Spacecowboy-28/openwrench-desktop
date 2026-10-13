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

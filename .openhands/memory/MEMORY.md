# Project memory index — openwrench-desktop

PySide6 + SQLite desktop app (Windows/Linux). Branch flow: feature -> dev/milestone-N -> main.

## Environment (this sandbox resets between sessions)
- If `import pytest`/`PySide6` or `libEGL.so.1` fails, the container was reset. Run:
  `pip install -q -r requirements-dev.txt` then
  `sudo apt-get update -qq && sudo apt-get install -y -qq libegl1 libopengl0 libxkbcommon0 libdbus-1-3`.
- Run GUI tests with `QT_QPA_PLATFORM=offscreen`; add `-p no:cacheprovider` to avoid cache churn.

## Git / PRs
- `origin` remote URL holds a STALE token. Push with the live env token:
  `git push "https://${GITHUB_TOKEN}@github.com/Spacecowboy-28/openwrench-desktop.git" <branch>`. 
- PR #4 = dev/milestone-3 -> main. PR #5 = dev/milestone-4-openhands -> dev/milestone-3 (draft).

## Architecture notes
- Offline HTML: `html_bundle.py` (bounded ZIP), `html_ui.py` (QTextBrowser, no WebEngine),
  `pdf_worker.py`/`library_tasks.py` (QProcess workers, SQLite never crosses threads).
- Archive budgets are declared-size based; MAX_ARCHIVE (128 MiB) > MAX_TOTAL (100 MiB).
  No compression-ratio heuristic (it rejected legitimate repetitive manuals).
- Heavy document work belongs in the QProcess worker, never the GUI thread.

## Details
- See `2026-10-16.md` for the M3 audit (bugs B1-B7), perf measurements, and verification notes.

# Third-party components register

Original OpenWrench code: MIT, copyright OpenWrench contributors.
No upstream automotive source or manual content is included in the source tree.
Reviewed 2026-10-13. Versions below are intentional baseline pins, not claims
about the latest upstream versions or long-term support.

## Direct runtime and build components

| Component | Version | License | Source | Integration / maintenance evidence |
| --- | --- | --- | --- | --- |
| CPython | 3.12 baseline; local 3.12.14 | PSF-2.0 plus bundled notices | https://github.com/python/cpython | Runtime; maintained CPython line, patch updates needed |
| SQLite | Python runtime dependent; record exact build in test report | Public domain | https://sqlite.org/src | Standard-library sqlite3; maintained upstream, tied to Python distribution |
| PySide6-Essentials / Qt | 6.8.3 | LGPLv3/GPL/commercial choices, LGPLv3 selected for included modules | https://code.qt.io/pyside/pyside-setup.git | Dynamic QtCore/QtGui/QtWidgets bindings; official Qt project; tested older baseline, no current support guarantee |
| shiboken6 | 6.8.3 | LGPLv3/GPL/commercial choices | https://code.qt.io/pyside/pyside-setup.git | Required binding runtime, same Qt maintenance caveat |
| PyInstaller | 6.16.0 | GPL-2.0-or-later with bootloader exception | https://github.com/pyinstaller/pyinstaller | Build-only; bootloader in native bundle; active upstream, pinned baseline |
| pyinstaller-hooks-contrib | 2026.8 | GPL-2.0-or-later with stated exception / per-file terms | https://github.com/pyinstaller/pyinstaller-hooks-contrib | Build hooks; audit copied runtime hooks before release |
| altgraph | 0.17.5 | MIT | https://github.com/ronaldoussoren/altgraph | PyInstaller graph analysis, build-only |
| setuptools | 80.9.0 | MIT | https://github.com/pypa/setuptools | Build backend; maintained upstream |
| build | 1.3.0 | MIT | https://github.com/pypa/build | Source/wheel build frontend; maintained upstream |
| pytest | 8.4.2 | MIT | https://github.com/pytest-dev/pytest | Test-only; maintained upstream |

Transitive development dependencies resolve through pip. The build environment
inventory is recorded in `docs/BUILD_ENVIRONMENT.json`. It is not a complete,
hash-locked cross-platform SBOM. Windows-only dependency versions require the
Windows CI run. Pinning the selected direct components does not fully reproduce
every system library or Python distribution.

## Qt binary-distribution gate

This handoff distributes original source, not the locally built Qt binary bundle.
Before publishing installers or native archives:

1. Audit every included module and system/runtime library from the build inventory.
2. Include LGPL/GPL texts, upstream copyright notices and per-library licenses.
3. Supply matching Qt/PySide/Shiboken source and build/relink instructions under
   the applicable terms. Do not rely on an unversioned homepage as a source offer.
4. Keep shared libraries replaceable. Do not impose restrictions on debugging
   modifications to LGPL components.
5. Verify packaged artifact contents and corresponding source availability.

Qt overview: https://doc.qt.io/qtforpython-6/
PyInstaller exception: https://pyinstaller.org/en/stable/license.html
SQLite license: https://sqlite.org/copyright.html

The MIT project license does not relicense dependencies. No GPL-only OBD library
is included. Optional plugins and sidecars still need whole-distribution review.
Future automotive candidates and adoption decisions appear in `docs/RESEARCH.md`.

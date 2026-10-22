"""Build a same-platform development bundle. No cross-compilation or publishing."""

from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'build' / 'assets'


def generate_icon():
    """Render the application icon set before freezing so the bundle embeds it."""
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    sys.path.insert(0, str(ROOT / 'scripts'))
    from make_icon import build, render, ICO_SIZES
    build(ASSETS)
    # Linux hicolor themes need standalone PNGs at each declared size.
    for size in ICO_SIZES:
        render(size).save(str(ASSETS / f'openwrench-{size}.png'), 'PNG')
    return ASSETS


def main():
    generate_icon()
    # Keep the Windows version resource in lockstep with the icon; both are derived
    # from openwrench.__version__ so a release bump cannot leave one stale.
    version_file = ROOT / 'build' / 'version_info.txt'
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'write_version_info.py'),
                    '--check', '--version-file', str(version_file)], check=True, cwd=ROOT)
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onedir', '--name', 'OpenWrench', '--paths', str(ROOT / 'src'),
        '--specpath', str(ROOT / 'build'), '--distpath', str(ROOT / 'dist'),
        '--workpath', str(ROOT / 'build' / 'pyinstaller'),
        '--collect-all', 'pypdfium2', '--collect-all', 'pypdfium2_raw',
        '--add-data', f'{ASSETS}{os.pathsep}assets',
        '--icon', str(ASSETS / 'openwrench.ico'),
        '--version-file', str(version_file),
        # Keep stdout for worker JSON and smoke tests while hiding a console owned
        # by this GUI application. --windowed would set the worker's stdout to None.
        *(['--hide-console', 'hide-early'] if sys.platform == 'win32' else []),
        '--exclude-module', 'PySide6.QtQml', '--exclude-module', 'PySide6.QtQuick',
        str(ROOT / 'scripts' / 'desktop_entry.py'),
    ], check=True, cwd=ROOT)
    destination = ROOT / 'dist' / 'OpenWrench'
    for filename in ('LICENSE', 'THIRD_PARTY.md', 'README.md'):
        shutil.copy2(ROOT / filename, destination / filename)
    from importlib.metadata import distribution
    notices = destination / 'licenses' / 'pypdfium2'
    for entry in distribution('pypdfium2').files or []:
        if any('license' in str(part).lower() or 'notice' in str(part).lower() for part in entry.parts):
            source = Path(distribution('pypdfium2').locate_file(entry))
            if source.is_file():
                target = notices.joinpath(*entry.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    print(f'Development bundle: {destination}')


if __name__ == '__main__':
    main()

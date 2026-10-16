"""Build a same-platform development bundle. No cross-compilation or publishing."""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onedir', '--name', 'OpenWrench', '--paths', str(ROOT / 'src'),
        '--specpath', str(ROOT / 'build'), '--distpath', str(ROOT / 'dist'),
        '--workpath', str(ROOT / 'build' / 'pyinstaller'),
        '--collect-all', 'pypdfium2', '--collect-all', 'pypdfium2_raw',
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

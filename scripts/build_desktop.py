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
        '--exclude-module', 'PySide6.QtQml', '--exclude-module', 'PySide6.QtQuick',
        str(ROOT / 'scripts' / 'desktop_entry.py'),
    ], check=True, cwd=ROOT)
    destination = ROOT / 'dist' / 'OpenWrench'
    for filename in ('LICENSE', 'THIRD_PARTY.md', 'README.md'):
        shutil.copy2(ROOT / filename, destination / filename)
    print(f'Development bundle: {destination}')


if __name__ == '__main__':
    main()

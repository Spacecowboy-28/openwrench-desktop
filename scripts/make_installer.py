"""Build the Windows installer from an existing PyInstaller bundle.

Locates the Inno Setup compiler (``ISCC.exe``), then compiles
``installer/openwrench.iss`` with the product version and bundle directory. Inno
Setup is a Windows tool; on Linux/macOS this script can drive it through Wine when
``ISCC.exe`` is reachable, otherwise it exits with a clear, actionable message and
non-zero status so CI fails loudly rather than silently skipping packaging.

Usage:
    python scripts/make_installer.py --source-dir dist/OpenWrench --output-dir dist
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / 'installer' / 'openwrench.iss'
# Standard Inno Setup 6 install locations, newest first.
ISCC_CANDIDATES = (
    r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    r'C:\Program Files\Inno Setup 6\ISCC.exe',
    r'C:\Program Files (x86)\Inno Setup 5\ISCC.exe',
)


def find_iscc(explicit=None):
    """Return a path to ISCC.exe, or None when it cannot be found."""
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    on_path = shutil.which('ISCC') or shutil.which('iscc')
    if on_path:
        return Path(on_path)
    for candidate in ISCC_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    return None


def compile_installer(iscc, source_dir, output_dir, version, extra=()):
    """Run ISCC with the version/source defines. Returns the completed process."""
    command = [
        str(iscc),
        f'/DAppVersion={version}',
        f'/DSourceDir={source_dir}',
        f'/DOutputDir={output_dir}',
        *extra,
        str(ISS),
    ]
    return subprocess.run(command, check=True, text=True, capture_output=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the OpenWrench Windows installer')
    parser.add_argument('--source-dir', type=Path, default=ROOT / 'dist' / 'OpenWrench',
                        help='PyInstaller onedir bundle to package')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--iscc', type=Path, help='Explicit path to ISCC.exe')
    parser.add_argument('--version', help='Override the product version')
    arguments = parser.parse_args(argv)

    source_dir = arguments.source_dir.resolve()
    if not (source_dir / 'OpenWrench.exe').exists():
        print(f'No OpenWrench.exe in {source_dir}; run scripts/build_desktop.py on Windows first.',
              file=sys.stderr)
        return 2

    sys.path.insert(0, str(ROOT / 'scripts'))
    from write_version_info import package_version
    version = arguments.version or package_version()

    iscc = find_iscc(arguments.iscc)
    if iscc is None:
        print('Inno Setup (ISCC.exe) was not found. Install Inno Setup 6 on Windows, or set',
              file=sys.stderr)
        print('--iscc to a Wine-hosted ISCC.exe. The installer cannot be built here.', file=sys.stderr)
        return 3

    # Inno writes relative to the .iss by default; make the output absolute so the
    # artifact lands in --output-dir regardless of the working directory.
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    result = compile_installer(iscc, source_dir, arguments.output_dir.resolve(), version)
    if result.stdout:
        print(result.stdout)
    expected = arguments.output_dir / f'OpenWrench-{version}-setup.exe'
    if not expected.exists():
        print(f'ISCC succeeded but {expected} is missing.', file=sys.stderr)
        return 4
    print(f'Installer: {expected}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

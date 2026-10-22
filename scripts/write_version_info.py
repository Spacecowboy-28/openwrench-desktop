"""Generate the Windows VS_VERSIONINFO resource and packaging metadata.

One source of truth for the product version: ``openwrench.__version__`` and
``pyproject.toml`` must agree, and every installer, spec and metadata file is
derived from them here. Keeping this in code (not a checked-in blob) means a
version bump cannot leave a stale number in one of the packaging files.
"""

import argparse
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = 'OpenWrench'
COMPANY = 'OpenWrench'
DESCRIPTION = 'Offline automotive workshop desktop'
COPYRIGHT = 'MIT licensed. Copyright OpenWrench contributors.'


def package_version():
    """Read the authoritative version from the installed package."""
    sys.path.insert(0, str(ROOT / 'src'))
    from openwrench import __version__
    return __version__


def pyproject_version():
    """Read the version declared in pyproject.toml, for a consistency check."""
    text = (ROOT / 'pyproject.toml').read_text('utf-8')
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError('pyproject.toml has no version')
    return match.group(1)


def numeric_version(version=None):
    """Return a 4-tuple of ints for the Windows file version.

    Windows requires four numeric fields; a PEP 440 pre-release suffix cannot be
    expressed, so ``0.3.0.dev1`` becomes (0, 3, 0, 1) with the pre-release marker
    carried in the textual fields instead.
    """
    version = version or package_version()
    core = version.split('+')[0]
    numbers = [int(part) for part in re.findall(r'\d+', core.split('.dev')[0])][:3]
    numbers += [0] * (3 - len(numbers))
    pre = re.search(r'\.dev(\d+)', core)
    numbers.append(int(pre.group(1)) if pre else 0)
    return tuple(numbers[:4])


def version_info_text(version=None):
    """Return a PyInstaller ``--version-file`` VSVersionInfo document."""
    version = version or package_version()
    four = numeric_version(version)
    numeric = ', '.join(str(part) for part in four)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric},),
    prodvers=({numeric},),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '{COMPANY}'),
         StringStruct('FileDescription', '{DESCRIPTION}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{PRODUCT_NAME}'),
         StringStruct('LegalCopyright', '{COPYRIGHT}'),
         StringStruct('OriginalFilename', '{PRODUCT_NAME}.exe'),
         StringStruct('ProductName', '{PRODUCT_NAME}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description='Write packaging version metadata')
    parser.add_argument('--version-file', type=Path, help='Write the PyInstaller version resource')
    parser.add_argument('--check', action='store_true',
                        help='Fail if openwrench.__version__ and pyproject.toml disagree')
    arguments = parser.parse_args(argv)
    if arguments.check:
        package, project = package_version(), pyproject_version()
        if package != project:
            print(f'Version mismatch: package={package} pyproject={project}', file=sys.stderr)
            return 1
        print(f'Versions agree: {package}')
    if arguments.version_file:
        arguments.version_file.parent.mkdir(parents=True, exist_ok=True)
        arguments.version_file.write_text(version_info_text(), 'utf-8')
        print(arguments.version_file)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

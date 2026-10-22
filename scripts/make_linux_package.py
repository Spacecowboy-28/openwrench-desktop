"""Package the PyInstaller onedir bundle as a portable Linux tarball.

The tarball is relocatable: it carries the onedir bundle, the desktop entry, the
hicolor icon set and an ``install.sh`` that installs into ``~/.local`` (no root) or
``/usr/local`` (root). Nothing is installed implicitly by this script; it only
assembles the archive so a packager can inspect it first.

Usage:
    python scripts/make_linux_package.py --bundle-dir dist/OpenWrench --output-dir dist
"""

import argparse
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = '''#!/bin/sh
# Install OpenWrench from this portable archive. Run with sudo for /usr/local.
set -eu
PREFIX="${PREFIX:-$HOME/.local}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$PREFIX/bin" "$PREFIX/share/applications" "$PREFIX/share/icons/hicolor"
cp -a "$HERE/OpenWrench" "$PREFIX/"
ln -sf "$PREFIX/OpenWrench/OpenWrench" "$PREFIX/bin/openwrench"
sed "s|^Exec=openwrench|Exec=$PREFIX/bin/openwrench|" "$HERE/openwrench.desktop" \\
    > "$PREFIX/share/applications/openwrench.desktop"
for size in 16 32 48 64 128 256; do
    dir="$PREFIX/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dir"
    cp "$HERE/icons/openwrench-${size}.png" "$dir/openwrench.png"
done
echo "Installed to $PREFIX. Run: $PREFIX/bin/openwrench"
'''


def ensure_icons(icon_dir):
    """Return the icon directory, rendering the set first if it is missing.

    The Linux package needs one PNG per declared size; a source checkout has none
    committed, so render them here rather than failing the packaging step.
    """
    icon_dir = Path(icon_dir)
    if not any(icon_dir.glob('openwrench-*.png')):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
        from make_icon import build, render, ICO_SIZES
        build(icon_dir)
        for size in ICO_SIZES:
            render(size).save(str(icon_dir / f'openwrench-{size}.png'), 'PNG')
    return icon_dir


def build_archive(bundle_dir, output_dir, version, icon_dir=None):
    """Assemble the portable tarball; return the archive path."""
    bundle_dir = Path(bundle_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    icon_dir = ensure_icons(icon_dir or ROOT / 'build' / 'assets')
    archive = output_dir / f'OpenWrench-{version}-linux-x86_64.tar.gz'

    staging = output_dir / 'openwrench-linux-staging'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(bundle_dir, staging / 'OpenWrench', symlinks=True)
    (staging / 'install.sh').write_text(INSTALL_SH, 'utf-8')
    (staging / 'install.sh').chmod(0o755)
    shutil.copy2(ROOT / 'installer' / 'openwrench.desktop', staging / 'openwrench.desktop')
    icons = staging / 'icons'
    icons.mkdir()
    for source in sorted(icon_dir.glob('openwrench-*.png')):
        shutil.copy2(source, icons / source.name)
    for name in ('LICENSE', 'THIRD_PARTY.md', 'README.md'):
        shutil.copy2(ROOT / name, staging / name)

    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(staging, arcname='openwrench')
    shutil.rmtree(staging)
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the Linux portable package')
    parser.add_argument('--bundle-dir', type=Path, default=ROOT / 'dist' / 'OpenWrench')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--icon-dir', type=Path, default=ROOT / 'build' / 'assets')
    parser.add_argument('--version', help='Override the product version')
    arguments = parser.parse_args(argv)

    bundle_dir = arguments.bundle_dir.resolve()
    if not (bundle_dir / 'OpenWrench').exists():
        print(f'No bundle executable in {bundle_dir}; run scripts/build_desktop.py first.',
              file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT / 'scripts'))
    from write_version_info import package_version
    version = arguments.version or package_version()
    archive = build_archive(bundle_dir, arguments.output_dir, version, arguments.icon_dir)
    print(f'Package: {archive}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

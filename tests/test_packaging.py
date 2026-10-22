"""Milestone 6 packaging tests.

These cover the parts of packaging that are testable on any platform: version
metadata consistency, icon generation, the installer script's data-preservation
contract, and the Linux archive layout. Building the actual Windows installer
requires Inno Setup and is exercised by CI on Windows, not here.
"""

import struct
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def test_package_and_pyproject_versions_agree():
    from write_version_info import package_version, pyproject_version
    assert package_version() == pyproject_version()


@pytest.mark.parametrize('version,expected', [
    ('0.3.0.dev1', (0, 3, 0, 1)),
    ('1.2.3', (1, 2, 3, 0)),
    ('0.1.0', (0, 1, 0, 0)),
    ('2.0.0.dev10', (2, 0, 0, 10)),
])
def test_numeric_version_is_four_windows_fields(version, expected):
    from write_version_info import numeric_version
    assert numeric_version(version) == expected


def test_version_resource_is_well_formed_and_names_the_product():
    from write_version_info import version_info_text, package_version
    text = version_info_text()
    assert text.startswith('# UTF-8')
    assert 'VSVersionInfo(' in text
    assert f"StringStruct('ProductVersion', '{package_version()}')" in text
    # Windows requires exactly four integers per version field.
    from write_version_info import numeric_version
    numeric = ', '.join(map(str, numeric_version()))
    assert text.count(f'filevers=({numeric},)') == 1
    assert text.count(f'prodvers=({numeric},)') == 1


def test_icon_build_is_deterministic_and_writes_a_multi_size_ico(tmp_path):
    from PySide6.QtGui import QGuiApplication, QIcon
    QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    from make_icon import build, ICO_SIZES
    first = tmp_path / 'one'
    second = tmp_path / 'two'
    build(first)
    build(second)
    assert (first / 'openwrench.png').read_bytes() == (second / 'openwrench.png').read_bytes()
    ico = (first / 'openwrench.ico')
    assert ico.read_bytes() == (second / 'openwrench.ico').read_bytes()
    # A single-image ICO is what Qt writes by default and what Windows rejects for
    # shell icons; assert every declared size is present and PNG-encoded.
    data = ico.read_bytes()
    reserved, kind, count = struct.unpack('<HHH', data[:6])
    assert reserved == 0 and kind == 1
    assert count == len(ICO_SIZES)
    sizes = []
    for index in range(count):
        offset = 6 + index * 16
        width, height, _colors, _res, _planes, bpp, size, start = struct.unpack('<BBBBHHII', data[offset:offset + 16])
        assert bpp == 32
        assert data[start:start + 8] == b'\x89PNG\r\n\x1a\n'
        sizes.append(width or 256)
    assert sorted(sizes, reverse=True) == sorted(ICO_SIZES, reverse=True)
    assert not QIcon(str(ico)).isNull()


@pytest.mark.parametrize('platform,preferred', [('linux', 'png'), ('win32', 'ico')])
def test_resource_lookup_prefers_windows_ico_and_falls_back(tmp_path, monkeypatch, platform, preferred):
    import importlib
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    from make_icon import build
    bundle = tmp_path / 'bundle'
    build(bundle / 'assets')
    from openwrench import resources
    importlib.reload(resources)

    # Simulate a frozen build: PyInstaller points _MEIPASS at the bundle root.
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'platform', platform)
    assert resources.resource_root() == bundle
    assert resources.icon_path() == bundle / 'assets' / f'openwrench.{preferred}'
    assert not resources.application_icon().isNull()

    (bundle / 'assets' / f'openwrench.{preferred}').unlink()
    fallback = 'png' if preferred == 'ico' else 'ico'
    assert resources.icon_path() == bundle / 'assets' / f'openwrench.{fallback}'
    assert not resources.application_icon().isNull()

    # In a source checkout no icon is committed, so lookup must return None rather
    # than raising; the app must tolerate a missing icon.
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    monkeypatch.setattr(resources, 'RESOURCE_DIR', 'definitely-missing')
    assert resources.icon_path() is None
    assert resources.application_icon().isNull()


def test_icon_set_covers_every_hicolor_size(tmp_path):
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    from make_icon import ICO_SIZES
    from make_linux_package import ensure_icons
    icon_dir = ensure_icons(tmp_path / 'icons')
    # ensure_icons must render the set on demand so packaging never depends on a
    # prior build step leaving assets behind.
    for size in ICO_SIZES:
        assert (icon_dir / f'openwrench-{size}.png').stat().st_size > 0


def test_desktop_entry_has_required_keys():
    text = (ROOT / 'installer' / 'openwrench.desktop').read_text('utf-8')
    assert 'Type=Application' in text
    assert 'Exec=openwrench' in text
    assert 'Icon=openwrench' in text
    assert 'Categories=' in text
    assert 'StartupWMClass=OpenWrench' in text
    # The launcher must not silently inherit a terminal.
    assert 'Terminal=false' in text


def test_installer_script_preserves_user_data_and_installs_shortcuts():
    text = (ROOT / 'installer' / 'openwrench.iss').read_text('utf-8')
    # The workspace must live outside the install directory and uninstall must ask
    # before deleting it, defaulting to No.
    assert '{localappdata}\\OpenWrench\\OpenWrench' in text
    assert 'MB_DEFBUTTON2' in text
    assert 'IDYES' in text
    assert 'desktopicon' in text
    assert '{group}\\{#AppName}' in text
    assert 'OutputBaseFilename=OpenWrench-{#AppVersion}-setup' in text
    # The version and source paths must be injected, never hard-coded.
    assert 'AppVersion={#AppVersion}' in text
    assert '#define AppVersion "0.0.0"' in text
    assert 'PrivilegesRequired=lowest' in text
    assert 'not UninstallSilent' in text
    assert 'VersionInfoVersion={#AppNumericVersion}' in text
    assert 'SetupIconFile={#SourceDir}\\_internal\\assets\\openwrench.ico' in text


def test_linux_package_layout_is_relocatable(tmp_path):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from make_linux_package import build_archive
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'OpenWrench').write_text('#!/bin/sh\nexit 0\n')
    (bundle / 'OpenWrench').chmod(0o755)
    (bundle / 'lib.so').write_bytes(b'x')
    icon_dir = tmp_path / 'icons'
    icon_dir.mkdir()
    for size in (16, 32, 48, 64, 128, 256):
        (icon_dir / f'openwrench-{size}.png').write_bytes(b'png')
    archive = build_archive(bundle, tmp_path / 'out', '1.2.3', icon_dir)
    assert archive.name == 'OpenWrench-1.2.3-linux-x86_64.tar.gz'
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert 'openwrench/OpenWrench/OpenWrench' in names
    assert 'openwrench/install.sh' in names
    assert 'openwrench/openwrench.desktop' in names
    assert 'openwrench/icons/openwrench-256.png' in names
    assert 'openwrench/LICENSE' in names
    # Staging must not be left behind.
    assert not (tmp_path / 'out' / 'openwrench-linux-staging').exists()


def test_linux_install_script_targets_user_local_and_does_not_require_root():
    text = (ROOT / 'scripts' / 'make_linux_package.py').read_text('utf-8')
    assert 'PREFIX:-$HOME/.local' in text
    assert 'share/applications' in text
    assert 'hicolor' in text


def test_installer_builder_refuses_without_a_bundle(tmp_path):
    from make_linux_package import main as linux_main
    # A missing bundle must fail with a clear status, not traceback or a silent pass.
    assert linux_main(['--bundle-dir', str(tmp_path / 'nope'), '--output-dir', str(tmp_path / 'out')]) == 2


def test_windows_installer_builder_checks_inputs(tmp_path, monkeypatch):
    import make_installer
    assert make_installer.main(['--source-dir', str(tmp_path)]) == 2
    (tmp_path / 'OpenWrench.exe').write_bytes(b'bundle fixture')
    monkeypatch.setattr(make_installer, 'find_iscc', lambda _: None)
    assert make_installer.main(['--source-dir', str(tmp_path)]) == 3


@pytest.mark.parametrize('outcome', ['success', 'compiler-error', 'missing-output'])
def test_windows_installer_compilation_reports_failures_and_checksums(tmp_path, monkeypatch, capsys, outcome):
    import hashlib
    import subprocess
    import make_installer
    source = tmp_path / 'bundle with spaces'
    source.mkdir()
    (source / 'OpenWrench.exe').write_bytes(b'bundle fixture')
    output = tmp_path / 'installer output'
    compiler = tmp_path / 'ISCC.exe'
    monkeypatch.setattr(make_installer, 'find_iscc', lambda _: compiler)

    def compile_command(command, **kwargs):
        assert command[0] == str(compiler)
        assert '/DAppVersion=1.2.3.dev4' in command
        assert '/DAppNumericVersion=1.2.3.4' in command
        assert f'/DSourceDir={source}' in command
        assert f'/DOutputDir={output}' in command
        if outcome == 'compiler-error':
            raise subprocess.CalledProcessError(1, command, output='compiler detail', stderr='bad input')
        if outcome == 'success':
            (output / 'OpenWrench-1.2.3.dev4-setup.exe').write_bytes(b'installer fixture')
        return subprocess.CompletedProcess(command, 0, stdout='compiled', stderr='')

    monkeypatch.setattr(make_installer.subprocess, 'run', compile_command)
    result = make_installer.main(['--source-dir', str(source), '--output-dir', str(output), '--version', '1.2.3.dev4'])
    assert result == {'success': 0, 'compiler-error': 1, 'missing-output': 4}[outcome]
    if outcome == 'success':
        checksum = (output / 'OpenWrench-1.2.3.dev4-setup.exe.sha256').read_text('utf-8')
        assert checksum == hashlib.sha256(b'installer fixture').hexdigest() + '  OpenWrench-1.2.3.dev4-setup.exe\n'
    elif outcome == 'compiler-error':
        captured = capsys.readouterr()
        assert 'compiler detail' in captured.out and 'bad input' in captured.err

"""Exercise a real per-user Windows install, version upgrade and silent uninstall.

Run on an isolated Windows CI account with no existing OpenWrench installation
or workspace. The script refuses to touch either when they already exist.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C4B2E6A-9D3F-4A5B-9C1E-6F0A1B2C3D4E}_is1'


def installed_version():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return winreg.QueryValueEx(key, 'DisplayVersion')[0]
    except FileNotFoundError:
        return None


def snapshot(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob('*') if path.is_file()}


def run(command, **kwargs):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True,
                            timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    parser.add_argument('--previous-installer', type=Path, required=True)
    parser.add_argument('--previous-version', default='0.3.0.dev1')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts' / 'installer-acceptance')
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        parser.error('This acceptance test requires a native Windows runner.')
    from openwrench import __version__
    from openwrench.garage import Garage
    from openwrench.storage import Store
    from openwrench.transfers import read_tables

    workspace = Path(os.environ['LOCALAPPDATA']) / 'OpenWrench' / 'OpenWrench'
    if workspace.exists() or installed_version() is not None:
        raise RuntimeError('Use a clean Windows CI account: an existing workspace or installation was found.')
    installers = [args.previous_installer.resolve(), args.installer.resolve()]
    if not all(path.is_file() for path in installers):
        raise FileNotFoundError('Both the previous and current Windows installers are required.')
    report = args.output_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    group = 'OpenWrench acceptance ' + uuid4().hex
    shortcuts = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / group
    workspace.mkdir(parents=True)
    try:
        with closing(Store(workspace / 'openwrench.sqlite3')) as store:
            Garage(store).save_vehicle(dict(nickname='Installer acceptance', year=2020, make='Honda', model='Civic'))
            store.set_theme('light')
            expected_records = read_tables(store.connection)
            store.backup(workspace / 'acceptance-backup.sqlite3')
        documents = workspace / 'openwrench.documents'
        documents.mkdir()
        (documents / 'retained-manual.txt').write_text('Original synthetic installer acceptance fixture.', encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='OpenWrench install with spaces ') as temporary:
            destination = Path(temporary) / 'OpenWrench Desktop'
            uninstaller = destination / 'unins000.exe'
            try:
                for label, installer, version in zip(('install', 'upgrade'), installers,
                                                      (args.previous_version, __version__)):
                    before = snapshot(workspace)
                    run([installer, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                         f'/DIR={destination}', f'/GROUP={group}', f'/LOG={report / (label + ".log")}'])
                    assert snapshot(workspace) == before, f'{label} modified the workspace'
                    executable = destination / 'OpenWrench.exe'
                    assert installed_version() == version, 'Wrong per-user uninstall registration'
                    assert (shortcuts / 'OpenWrench.lnk').is_file(), 'Start Menu shortcut missing'
                    assert (destination / '_internal' / 'assets' / 'openwrench.ico').is_file()
                    assert run([executable, '--version']).strip() == version
                    result = json.loads(run([executable, '--smoke-test', '--data-dir', workspace]))
                    assert result == dict(status='ok', version=version, schema=6, visible=True, theme='light'), result
                    with closing(Store(workspace / 'openwrench.sqlite3')) as reopened:
                        assert read_tables(reopened.connection) == expected_records
                    print(f'{label}: {version}, native event loop and unchanged workspace verified', flush=True)
                run([sys.executable, ROOT / 'scripts' / 'check_packaged_library.py', executable])
                before = snapshot(workspace)
                run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                     f'/LOG={report / "uninstall.log"}'])
                deadline = time.monotonic() + 30
                while (executable.exists() or shortcuts.exists() or installed_version() is not None) and time.monotonic() < deadline:
                    time.sleep(0.2)
                assert not executable.exists(), 'Uninstall left the program executable'
                assert not shortcuts.exists(), 'Uninstall left Start Menu shortcuts'
                assert installed_version() is None, 'Uninstall left its registry entry'
                assert snapshot(workspace) == before, 'Silent uninstall changed user data'
                summary = dict(status='ok', previous_version=args.previous_version, version=__version__,
                               install=True, upgrade=True, installed_library=True, uninstall=True,
                               workspace_preserved=True)
                (report / 'results.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
                print(json.dumps(summary), flush=True)
            finally:
                if uninstaller.exists() and installed_version() is not None:
                    run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
    finally:
        # Only the synthetic workspace created above is ours to remove.
        shutil.rmtree(workspace)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

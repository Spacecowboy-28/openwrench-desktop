from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from openwrench.storage import Store


def test_first_launch_migrates_and_reopen_preserves_theme(tmp_path):
    path = tmp_path / 'nested' / 'app.sqlite3'
    store = Store(path)
    assert store.theme == 'dark'
    store.set_theme('light')
    store.close()
    reopened = Store(path)
    assert reopened.theme == 'light'
    assert reopened.integrity() == 'ok'
    assert reopened.connection.execute('PRAGMA user_version').fetchone()[0] == 4
    reopened.close()


@pytest.mark.parametrize('theme', ['', 'system', 'LIGHT', "dark';DROP TABLE settings;"])
def test_invalid_settings_never_change_database(tmp_path, theme):
    store = Store(tmp_path / 'app.sqlite3')
    with pytest.raises(ValueError):
        store.set_theme(theme)
    assert store.theme == 'dark'
    store.close()


def test_newer_database_refuses_downgrade_without_mutation(tmp_path):
    path = tmp_path / 'app.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA user_version=99')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='newer'):
        Store(path)
    assert path.read_bytes() == before


def test_unrelated_database_is_preserved(tmp_path):
    path = tmp_path / 'other.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE records (value TEXT)')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='not an empty'):
        Store(path)
    assert path.read_bytes() == before


def test_corrupt_database_is_preserved(tmp_path):
    path = tmp_path / 'broken.sqlite3'
    path.write_bytes(b'not a database')
    with pytest.raises(sqlite3.DatabaseError):
        Store(path)
    assert path.read_bytes() == b'not a database'


def test_backup_is_independent_and_reopens(tmp_path):
    store = Store(tmp_path / 'app.sqlite3')
    store.set_theme('light')
    backup = store.backup(tmp_path / 'backup.sqlite3')
    store.set_theme('dark')
    other = Store(backup)
    assert other.theme == 'light'
    assert other.integrity() == 'ok'
    other.close()
    store.close()


def test_backup_never_overwrites_current_or_existing_file(tmp_path):
    store = Store(tmp_path / 'app.sqlite3')
    with pytest.raises(ValueError):
        store.backup(store.path)
    target = tmp_path / 'backup.sqlite3'
    target.write_bytes(b'preserve me')
    with pytest.raises(FileExistsError):
        store.backup(target)
    assert target.read_bytes() == b'preserve me'
    store.close()


def test_backup_failure_keeps_source_usable(tmp_path):
    store = Store(tmp_path / 'app.sqlite3')
    with pytest.raises(OSError):
        store.backup(tmp_path / 'missing' / 'backup.sqlite3')
    assert store.integrity() == 'ok'
    store.close()


def test_failed_flush_removes_partial_backup(tmp_path, monkeypatch):
    store = Store(tmp_path / 'app.sqlite3')
    target = tmp_path / 'backup.sqlite3'
    def fail_flush(fd):
        raise OSError('disk full')
    monkeypatch.setattr('openwrench.storage.os.fsync', fail_flush)
    with pytest.raises(OSError, match='disk full'):
        store.backup(target)
    assert not target.exists()
    assert not list(tmp_path.glob('.openwrench-*'))
    assert store.integrity() == 'ok'
    store.close()

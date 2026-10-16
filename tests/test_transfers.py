from contextlib import closing
import csv
import io
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from openwrench.garage import Garage
from openwrench.storage import Store
from openwrench.transfers import export_garage, garage_document, read_tables


def seed(store, name='Daily', unit='km'):
    garage = Garage(store)
    identifier = garage.save_vehicle(dict(nickname=name, year=2020, make='Honda', model='Civic', unit=unit, notes='=text,"quoted"\nJosé'))
    garage.save_entry(identifier, dict(kind='mileage', date='2026-01-01', odometer=12345))
    garage.save_entry(identifier, dict(kind='service', date='2026-01-02', odometer=12350, title='Oil, filter', cost='54.99', currency='CAD', notes='Line 1\nLine 2'))
    garage.save_entry(identifier, dict(kind='service', date='2026-01-03', title='Inspection', notes='No mileage or cost recorded'))
    return identifier


@pytest.fixture
def populated(tmp_path):
    store = Store(tmp_path / 'current.sqlite3')
    seed(store)
    yield store
    store.close()


def test_json_preserves_ids_units_dates_currency_nulls_and_exact_text(populated, tmp_path):
    before = read_tables(populated.connection)
    file = export_garage(populated, tmp_path / 'garage.json', 'json')
    data = json.loads(file.read_text('utf-8'))
    owner = data['vehicles'][0]
    assert owner['id'] == before['vehicles'][0]['id']
    assert owner['notes'] == '=text,"quoted"\nJosé'
    assert owner['engine'] is None and owner['unit'] == 'km'
    reading = data['odometer_readings'][0]
    assert reading['vehicle_id'] == owner['id'] and reading['distance_unit'] == 'km'
    assert reading['date'] == '2026-01-01' and reading['odometer'] == 12345
    service = data['service_history'][0]
    assert service['cost_cents'] == 5499 and service['currency'] == 'CAD'
    assert data['service_history'][1]['odometer'] is None
    assert data['service_history'][1]['cost_cents'] is None
    assert read_tables(populated.connection) == before


def test_csv_relationships_quoting_and_formula_escaping(populated, tmp_path):
    file = export_garage(populated, tmp_path / 'csv.zip', 'csv')
    with zipfile.ZipFile(file) as archive:
        def rows(name):
            return list(csv.DictReader(io.StringIO(archive.read(name).decode('utf-8-sig'))))
        vehicles = rows('vehicles.csv')
        mileage = rows('odometer_readings.csv')
        services = rows('service_history.csv')
        assert vehicles[0]['notes'] == "'=text,\"quoted\"\nJosé"
        assert mileage[0]['vehicle_id'] == vehicles[0]['id'] == services[0]['vehicle_id']
        assert services[0]['title'] == 'Oil, filter'
        assert services[0]['notes'] == 'Line 1\nLine 2'
        assert services[0]['cost_cents'] == '5499' and services[0]['currency'] == 'CAD'
        assert services[0]['distance_unit'] == 'km'
        assert json.loads(archive.read('manifest.json'))['format_version'] == 3


def test_empty_exports_include_arrays_and_csv_headers(tmp_path):
    with closing(Store(tmp_path / 'empty.sqlite3')) as store:
        assert garage_document(store)['vehicles'] == []
        file = export_garage(store, tmp_path / 'empty.zip', 'csv')
        with zipfile.ZipFile(file) as archive:
            assert archive.read('service_history.csv').decode('utf-8-sig').startswith('id,vehicle_id,kind,date,odometer,distance_unit')


def test_export_refuses_existing_targets_and_bad_format(populated, tmp_path):
    target = tmp_path / 'existing.json'
    target.write_text('keep me')
    with pytest.raises(FileExistsError):
        export_garage(populated, target, 'json')
    assert target.read_text() == 'keep me'
    with pytest.raises(ValueError):
        export_garage(populated, target, 'xml')
    with pytest.raises(FileExistsError):
        export_garage(populated, populated.path, 'json')
    assert populated.integrity() == 'ok'


def test_export_failure_removes_partial_file(populated, tmp_path, monkeypatch):
    def fail(_):
        raise OSError('disk full')
    monkeypatch.setattr('openwrench.transfers.os.fsync', fail)
    target = tmp_path / 'partial.json'
    with pytest.raises(OSError):
        export_garage(populated, target, 'json')
    assert not target.exists()
    assert len(Garage(populated).vehicles()) == 1


def test_restore_preserves_complete_backup_and_creates_safety(populated, tmp_path):
    source = tmp_path / 'source.sqlite3'
    with closing(Store(source)) as other:
        identifier = seed(other, 'Restored vehicle', 'mi')
        other.set_theme('light')
        vin = 'TEST0000000000001'
        with other.connection:
            other.connection.execute('INSERT INTO vin_cache VALUES (?,?,?,?)',
                (vin, 2020, json.dumps({'Results': [{'VIN': vin}]}), '2026-01-01T00:00:00+00:00'))
        expected = read_tables(other.connection)
    before = read_tables(populated.connection)
    bytes_before = source.read_bytes()
    old_garage = Garage(populated)
    safety = populated.restore(source)
    assert source.read_bytes() == bytes_before
    assert read_tables(populated.connection) == expected
    assert old_garage.vehicle(identifier)['unit'] == 'mi'  # Existing handles still work.
    with closing(Store(safety)) as saved:
        assert read_tables(saved.connection) == before
    with closing(Store(populated.path)) as reopened:
        assert read_tables(reopened.connection) == expected


def test_legacy_restore_migrates_copy_and_clears_garage(populated, tmp_path):
    source = tmp_path / 'v1.sqlite3'
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')")
        db.execute('PRAGMA user_version=1')
        db.commit()
    original = source.read_bytes()
    safety = populated.restore(source)
    assert populated.theme == 'light'
    assert Garage(populated).vehicles() == []
    assert populated.connection.execute('PRAGMA user_version').fetchone()[0] == 5
    assert source.read_bytes() == original
    with closing(Store(safety)) as old:
        assert len(Garage(old).vehicles()) == 1


@pytest.mark.parametrize('damage', ['corrupt', 'future', 'unrelated', 'trigger', 'orphan', 'bad-date', 'bad-unit', 'bad-id', 'bad-money', 'bad-cache'])
def test_malformed_restore_never_changes_current(populated, tmp_path, damage):
    source = tmp_path / 'bad.sqlite3'
    with closing(Store(source)) as candidate:
        seed(candidate)
    with closing(sqlite3.connect(source)) as db:
        if damage == 'future': db.execute('PRAGMA user_version=99')
        elif damage == 'unrelated': db.execute('CREATE TABLE unrelated (data TEXT)')
        elif damage == 'trigger': db.execute('CREATE TRIGGER unwanted AFTER INSERT ON settings BEGIN DELETE FROM vehicles; END')
        elif damage == 'orphan': db.execute("UPDATE entries SET vehicle_id='missing'")
        elif damage == 'bad-date': db.execute("UPDATE entries SET date='2026-02-30'")
        elif damage == 'bad-unit':
            db.execute('PRAGMA ignore_check_constraints=ON')
            db.execute("UPDATE vehicles SET unit='bad'")
        elif damage == 'bad-id': db.execute("UPDATE entries SET id='bad' WHERE kind='mileage'")
        elif damage == 'bad-money': db.execute("UPDATE entries SET cost_cents=1.5 WHERE kind='service'")
        elif damage == 'bad-cache': db.execute("INSERT INTO vin_cache VALUES ('TEST0000000000001',2020,'bad JSON','2026-01-01T00:00:00+00:00')")
        db.commit()
    if damage == 'corrupt': source.write_bytes(b'not SQLite')
    before = read_tables(populated.connection)
    with pytest.raises((ValueError, sqlite3.Error)):
        populated.restore(source)
    assert read_tables(populated.connection) == before
    assert not list(tmp_path.glob('current.pre-restore-*'))


def test_export_rejects_malformed_stored_record(populated,tmp_path):
    with populated.connection:
        populated.connection.execute("UPDATE entries SET date='invalid'")
    with pytest.raises(ValueError):
        export_garage(populated,tmp_path/'bad.json','json')
    assert not (tmp_path/'bad.json').exists()


def test_restore_rolls_back_partial_replacement(populated,tmp_path,monkeypatch):
    source=tmp_path/'other.sqlite3'
    with closing(Store(source)) as other:
        seed(other,'Other')
    before=read_tables(populated.connection)
    def fail(_):
        populated.connection.execute('DELETE FROM entries')
        populated.connection.execute('DELETE FROM vehicles')
        raise sqlite3.OperationalError('injected failure')
    monkeypatch.setattr(populated,'_replace_records',fail)
    with pytest.raises(ValueError,match='Safety backup'):
        populated.restore(source)
    assert read_tables(populated.connection) == before
    assert not populated.connection.in_transaction
    safety=next(tmp_path.glob('current.pre-restore-*'))
    with closing(Store(safety)) as old:
        assert read_tables(old.connection) == before


def test_safety_backup_failure_prevents_restore(populated,tmp_path,monkeypatch):
    source=tmp_path/'other.sqlite3'
    with closing(Store(source)) as other:
        seed(other,'Other')
    before=read_tables(populated.connection)
    def fail(_): raise OSError('backup unavailable')
    monkeypatch.setattr(populated,'backup',fail)
    with pytest.raises(OSError): populated.restore(source)
    assert read_tables(populated.connection) == before


def test_restore_active_or_missing_file_is_rejected(populated,tmp_path):
    before=read_tables(populated.connection)
    for path in [populated.path,tmp_path/'missing.sqlite3']:
        with pytest.raises(ValueError): populated.restore(path)
    assert read_tables(populated.connection) == before

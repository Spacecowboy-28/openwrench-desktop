from contextlib import closing
from datetime import date, timedelta
import json
import sqlite3

import pytest

from openwrench.garage import Garage, money
from openwrench.storage import Store


@pytest.fixture
def garage(tmp_path):
    store = Store(tmp_path / 'garage.sqlite3')
    yield Garage(store)
    store.close()


def vehicle(**changes):
    return dict(year=2001, make='Toyota', model='Tundra', **changes)


def entry(when='2026-01-01', odometer=100, **changes):
    return dict(kind='mileage', date=when, odometer=odometer, **changes)


def test_upgrade_preserves_v1_settings_and_backup(tmp_path):
    path = tmp_path / 'garage.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')")
        db.execute('PRAGMA user_version=1')
        db.commit()
    store = Store(path)
    assert store.theme == 'light'
    assert store.connection.execute('PRAGMA user_version').fetchone()[0] == 6
    backups = list(tmp_path.glob('*.pre-v2-*.sqlite3'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute('SELECT value FROM settings').fetchone()[0] == 'light'
    store.close()
    Store(path).close()
    assert len(list(tmp_path.glob('*.pre-v2-*.sqlite3'))) == 1


def test_failed_migration_rolls_back(tmp_path):
    path = tmp_path / 'garage.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')")
        db.execute('CREATE TABLE entries (unexpected TEXT)')
        db.execute('PRAGMA user_version=1')
        db.commit()
    with pytest.raises(sqlite3.OperationalError):
        Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='vehicles'").fetchone()


def test_initial_profiles_unknown_fields_and_reopen(garage):
    from openwrench.garage_ui import PROFILES
    for year, make, model, engine, trim in PROFILES:
        garage.save_vehicle(dict(year=year, make=make, model=model, engine=engine, trim=trim))
    garage.save_vehicle(dict(year=1999, make='Subaru', model='Legacy', unit='km'))
    assert len(garage.vehicles()) == 5
    for v in garage.vehicles():
        if v['model'] in ('Tundra', 'Civic'):
            assert v['engine'] is None and v['trim'] is None
    with closing(sqlite3.connect(garage.store.path)) as db:
        assert db.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0] == 5


def test_crud_and_cascade(garage):
    identifier = garage.save_vehicle(vehicle())
    garage.save_vehicle(vehicle(nickname='Work truck', engine='Confirmed later'), identifier)
    assert garage.vehicle(identifier)['nickname'] == 'Work truck'
    garage.save_entry(identifier, entry())
    garage.save_entry(identifier, dict(kind='service',date='2026-01-02',title='Oil change',odometer=120,cost='49.95',notes='Filter replaced'))
    assert garage.vehicles()[0]['mileage'] == 120
    assert garage.entries(identifier)[0]['cost_cents'] == 4995
    garage.delete_vehicle(identifier)
    assert not garage.vehicles()
    assert garage.db.execute('SELECT COUNT(*) FROM entries').fetchone()[0] == 0


@pytest.mark.parametrize('data', [vehicle(year_bad='x'), dict(year=0,make='A',model='B'), dict(year=2001,make='',model='T'), vehicle(vin='I'*17), vehicle(unit='miles')])
def test_invalid_vehicle(garage, data):
    if 'year_bad' in data:
        data['year'] = data.pop('year_bad')
    with pytest.raises(ValueError):
        garage.save_vehicle(data)
    assert not garage.vehicles()


def test_duplicate_vin_and_normalized_name(garage):
    # Synthetic structurally valid test VIN, not an owner's VIN or a live request.
    vin = 'TEST0000000000001'
    identifier = garage.save_vehicle(vehicle(nickname='Work   Truck',vin=vin))
    with pytest.raises(ValueError,match='already exists'):
        garage.save_vehicle(vehicle(nickname=' work truck '))
    with pytest.raises(ValueError,match='already exists'):
        garage.save_vehicle(vehicle(nickname='Different name',vin=vin.lower()))
    garage.save_vehicle(vehicle(nickname='Work   Truck',vin=vin), identifier)
    # Two genuinely separate vehicles of the same model are allowed.
    garage.save_vehicle(vehicle(nickname='Second truck'))
    assert len(garage.vehicles()) == 2


def test_odometer_chronology_edit_delete_and_units(garage):
    identifier = garage.save_vehicle(vehicle())
    old = garage.save_entry(identifier, entry('2026-01-01',100))
    new = garage.save_entry(identifier, entry('2026-03-01',300))
    garage.save_entry(identifier, entry('2026-02-01',200))
    for when, value in [('2025-12-01',101),('2026-04-01',299),('2026-02-01',301)]:
        with pytest.raises(ValueError,match='conflicts'):
            garage.save_entry(identifier,entry(when,value))
    with pytest.raises(ValueError,match='conflicts'):
        garage.save_entry(identifier,entry('2026-01-01',250),old)
    with pytest.raises(ValueError,match='locked'):
        garage.save_vehicle(vehicle(unit='km'),identifier)
    garage.save_entry(identifier,entry('2026-03-01',320),new)
    assert garage.vehicles()[0]['mileage'] == 320
    garage.delete_entry(identifier,new)
    assert garage.vehicles()[0]['mileage'] == 200


@pytest.mark.parametrize('cost', ['-1','NaN','Infinity','1.001','1e100','abc'])
def test_invalid_cost(cost):
    with pytest.raises(ValueError):
        money(cost)


@pytest.mark.parametrize('data', [entry(odometer=-1),entry(odometer=1.5),entry(when='2026-02-30'),entry(when=(date.today()+timedelta(days=1)).isoformat()),entry(odometer=None)])
def test_bad_history_has_no_partial_writes(garage,data):
    identifier = garage.save_vehicle(vehicle())
    with pytest.raises(ValueError):
        garage.save_entry(identifier,data)
    assert garage.entries(identifier) == []


def test_service_without_mileage_does_not_invent_reading(garage):
    identifier = garage.save_vehicle(vehicle())
    record = garage.save_entry(identifier,dict(kind='service',date='2026-01-01',title='Inspection',cost='0'))
    assert garage.vehicles()[0]['mileage'] is None
    assert garage.entries(identifier)[0]['cost_cents'] == 0
    garage.save_entry(identifier,dict(kind='service',date='2026-01-01',title='Updated inspection',cost='10.25'),record)
    assert garage.entries(identifier)[0]['cost_cents'] == 1025


def test_backup_preserves_garage_and_history(garage,tmp_path):
    identifier = garage.save_vehicle(vehicle())
    garage.save_entry(identifier,entry())
    target = garage.store.backup(tmp_path/'backup.sqlite3')
    restored = Store(target)
    assert Garage(restored).vehicle(identifier)['engine'] is None
    assert Garage(restored).entries(identifier)[0]['odometer'] == 100
    restored.close()

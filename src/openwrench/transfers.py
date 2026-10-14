"""Versioned Garage exports and strict backup validation. No network access."""

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import UUID
import zipfile

from openwrench.garage import integer, normalize_vin, text, validated_date

TABLES = ('settings', 'vehicles', 'entries', 'vin_cache')
VEHICLE_FIELDS = ('id', 'nickname', 'vin', 'year', 'make', 'model', 'engine', 'trim', 'notes', 'unit', 'created_at')
RECORD_FIELDS = ('id', 'vehicle_id', 'kind', 'date', 'odometer', 'distance_unit', 'title', 'notes', 'cost_cents', 'currency')


def schema_signature(db):
    """Include indexes/triggers/views: extra executable schema is not accepted."""
    return [(row[0], row[1], ' '.join(row[2].split()).lower()) for row in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]


def read_tables(db):
    result = {}
    for table in TABLES:  # Fixed identifiers only, never supplied by an import.
        cursor = db.execute(f'SELECT * FROM {table}')
        names = [item[0] for item in cursor.description]
        result[table] = [dict(zip(names, row)) for row in cursor]
    return result


def valid_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Backup contains an invalid stable identifier.')


def valid_timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError('Backup contains an invalid timestamp.')


def validate_records(data):
    """Reject malformed values and relationships before export or restore."""
    try:
        settings = {row['key']: row['value'] for row in data['settings']}
        if settings.get('theme') not in ('dark', 'light'):
            raise ValueError('Backup has an invalid theme.')
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in settings.items()):
            raise ValueError('Backup has invalid settings.')
        owners, names, vins = {}, set(), set()
        for vehicle in data['vehicles']:
            identifier = vehicle['id']
            valid_id(identifier)
            if identifier in owners:
                raise ValueError('Duplicate vehicle identifier.')
            nickname = text(vehicle['nickname'], 'Garage name', 80, True)
            name_key = ' '.join(nickname.split()).casefold()
            if vehicle['name_key'] != name_key or name_key in names:
                raise ValueError('Duplicate or invalid Garage name.')
            names.add(name_key)
            vin = normalize_vin(vehicle['vin'] or '')
            if vin != vehicle['vin'] or (vin and vin in vins):
                raise ValueError('Duplicate or invalid VIN.')
            if vin:
                vins.add(vin)
            integer(vehicle['year'], 'Year', 1886, datetime.now().year + 1)
            for field in ('make', 'model'):
                text(vehicle[field], field, required=True)
            for field in ('engine', 'trim'):
                if vehicle[field] is not None:
                    text(vehicle[field], field)
            text(vehicle['notes'], 'Notes', 4000)
            if vehicle['unit'] not in ('mi', 'km'):
                raise ValueError('Invalid distance units.')
            valid_timestamp(vehicle['created_at'])
            owners[identifier] = vehicle
        identifiers, readings = set(), defaultdict(lambda: defaultdict(list))
        for record in data['entries']:
            valid_id(record['id'])
            if record['id'] in identifiers or record['vehicle_id'] not in owners:
                raise ValueError('Duplicate or orphan history record.')
            identifiers.add(record['id'])
            kind = record['kind']
            if kind not in ('mileage', 'service'):
                raise ValueError('Invalid history type.')
            when = validated_date(record['date'])
            odometer = record['odometer']
            if odometer is not None:
                integer(odometer, 'Odometer', 0, 10000000)
                readings[record['vehicle_id']][when].append(odometer)
            elif kind == 'mileage':
                raise ValueError('Missing odometer reading.')
            text(record['title'], 'Description', required=True)
            text(record['notes'], 'Notes', 4000)
            if record['cost_cents'] is not None:
                integer(record['cost_cents'], 'Cost in cents', 0, 9999999900)
                if kind == 'mileage':
                    raise ValueError('Mileage records must not contain costs.')
            if not isinstance(record['currency'], str) or not re.fullmatch('[A-Z]{3}', record['currency']):
                raise ValueError('Invalid currency code.')
        for dates in readings.values():
            previous = -1
            for when in sorted(dates):
                if min(dates[when]) < previous:
                    raise ValueError('Conflicting chronological odometer readings.')
                previous = max(dates[when])
        for row in data['vin_cache']:
            if not row['vin'] or normalize_vin(row['vin']) != row['vin']:
                raise ValueError('Invalid cached VIN.')
            if row['model_year'] != 0:
                integer(row['model_year'], 'Cached year', 1886, datetime.now().year + 1)
            valid_timestamp(row['fetched_at'])
            if not isinstance(row['payload'], str) or len(row['payload'].encode('utf-8')) > 1_000_000:
                raise ValueError('Invalid cache payload.')
            payload = json.loads(row['payload'])
            if not isinstance(payload, dict) or not isinstance(payload.get('Results'), list):
                raise ValueError('Invalid cache payload.')
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('Database contains malformed Garage data.') from error


def garage_document(store):
    db = store.connection
    if db.in_transaction:
        raise ValueError('Finish the current database operation before exporting.')
    with db:
        db.execute('BEGIN')
        data = read_tables(db)
    validate_records(data)
    units = {v['id']: v['unit'] for v in data['vehicles']}
    vehicles = [{k: v[k] for k in VEHICLE_FIELDS} for v in sorted(data['vehicles'], key=lambda v: v['id'])]
    records = [dict(row, distance_unit=units[row['vehicle_id']]) for row in sorted(data['entries'], key=lambda r: (r['vehicle_id'], r['date'], r['id']))]
    return dict(format='openwrench-garage', format_version=1, database_schema=2,
                exported_at=datetime.now(timezone.utc).isoformat(), vehicles=vehicles,
                odometer_readings=[r for r in records if r['kind'] == 'mileage'],
                service_history=[r for r in records if r['kind'] == 'service'])


def csv_text(value):
    # Prefix all leading apostrophes too, so the escaping is reversible.
    if isinstance(value, str) and (value.startswith(("'", '\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + value
    return value


def csv_bytes(rows, columns):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_text(row[key]) for key in columns})
    return output.getvalue().encode('utf-8-sig')


def write_new(destination, content):
    """Exclusive creation; preserve existing files and remove failed writes."""
    destination = Path(destination)
    output = destination.open('xb')
    try:
        with output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def export_garage(store, destination, kind):
    if kind not in ('json', 'csv'):
        raise ValueError('Choose JSON or CSV export.')
    document = garage_document(store)
    if kind == 'json':
        content = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    else:
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('vehicles.csv', csv_bytes(document['vehicles'], VEHICLE_FIELDS))
            archive.writestr('odometer_readings.csv', csv_bytes(document['odometer_readings'], RECORD_FIELDS))
            archive.writestr('service_history.csv', csv_bytes(document['service_history'], RECORD_FIELDS))
            archive.writestr('manifest.json', json.dumps({k: document[k] for k in ('format', 'format_version', 'database_schema', 'exported_at')}, indent=2))
            archive.writestr('README.txt', 'OpenWrench Garage CSV export, format 1.\n'
                'Join record.vehicle_id to vehicles.id. Record id values remain stable.\n'
                'Units: vehicles.unit and record.distance_unit use mi or km.\n'
                'Dates: YYYY-MM-DD. Timestamps: ISO 8601 with UTC offset.\n'
                'cost_cents is an integer amount in hundredths of the stated currency.\n'
                'Empty CSV cells mean absent values. UTF-8 with BOM, RFC-style quoting.\n'
                'Text beginning with a formula marker or apostrophe has one extra apostrophe.\n'
                'Remove one initial apostrophe to recover original text programmatically.\n'
                'JSON retains exact text and distinguishes null from empty text.\n'
                'Exports exclude application settings and VIN cache. Use SQLite backup/restore for recovery.\n')
        content = output.getvalue()
    return write_new(destination, content)


def validated_backup(source, directory):
    """Read only the selected file. Validate/migrate an isolated snapshot."""
    from openwrench.storage import Store
    source, directory = Path(source).resolve(), Path(directory)
    if not source.is_file() or source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Choose an existing SQLite backup smaller than 256 MiB.')
    snapshot = directory / 'snapshot.sqlite3'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as incoming:
        incoming.execute('PRAGMA trusted_schema=OFF')
        incoming.execute('BEGIN')  # Validate and copy the same consistent snapshot.
        version = incoming.execute('PRAGMA user_version').fetchone()[0]
        if version not in (1, 2):
            raise ValueError('Only OpenWrench schema 1 or 2 backups are supported. Newer versions need a newer app.')
        if incoming.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Backup failed SQLite integrity validation.')
        with closing(sqlite3.connect(':memory:')) as expected_v1, closing(Store(directory / 'reference.sqlite3')) as reference:
            expected_v1.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            expected = expected_v1 if version == 1 else reference.connection
            if schema_signature(incoming) != schema_signature(expected):
                raise ValueError('This file does not match the supported OpenWrench schema.')
        if incoming.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Backup contains orphan history records.')
        with closing(sqlite3.connect(snapshot)) as target:
            incoming.backup(target)
    with closing(Store(snapshot)) as staged:
        result = read_tables(staged.connection)
        validate_records(result)
    return result

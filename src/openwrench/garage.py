"""Validated Garage operations. Pure Python and SQLite, independent of Qt."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import sqlite3
from uuid import uuid4

from openwrench.storage import Store


def text(value, field, limit=160, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be text.')
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f'{field} is required and limited to {limit} characters.' if required else f'{field} is limited to {limit} characters.')
    return value


def normalize_vin(value):
    value = text(value, 'VIN', 17).upper()
    if value and not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', value):
        raise ValueError('Use a full 17-character VIN without I, O, or Q, or leave VIN blank.')
    return value or None


def integer(value, field, minimum, maximum):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError(f'{field} must be a whole number.')
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f'{field} must be between {minimum} and {maximum}.')
    return result


def validated_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Use a date in YYYY-MM-DD format.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('Enter a valid calendar date.') from None
    if parsed > date.today():
        raise ValueError('History entries must not be in the future.')
    return value


def money(value):
    if value in ('', None):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 99999999 or amount != amount.quantize(Decimal('.01')):
            raise ValueError
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('Cost must be a nonnegative amount with at most two decimal places.') from None


class Garage:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.connection

    def vehicles(self):
        return [dict(row) for row in self.db.execute('''SELECT v.*,
            (SELECT MAX(odometer) FROM entries e WHERE e.vehicle_id=v.id) AS mileage
            FROM vehicles v ORDER BY name_key''')]

    def vehicle(self, vehicle_id):
        row = self.db.execute('SELECT * FROM vehicles WHERE id=?', (vehicle_id,)).fetchone()
        if row is None:
            raise ValueError('This vehicle no longer exists. Refresh your Garage.')
        return dict(row)

    def save_vehicle(self, data, vehicle_id=None):
        year = integer(data.get('year', ''), 'Year', 1886, date.today().year + 1)
        make = text(data.get('make', ''), 'Make', required=True)
        model = text(data.get('model', ''), 'Model', required=True)
        nickname = text(data.get('nickname', ''), 'Garage name', 80) or f'{year} {make} {model}'
        nickname = text(nickname, 'Garage name', 80, True)
        unit = data.get('unit', 'mi')
        if unit not in ('mi', 'km'):
            raise ValueError('Choose mi or km.')
        if vehicle_id:
            previous = self.vehicle(vehicle_id)
            if unit != previous['unit'] and self.db.execute('SELECT 1 FROM entries WHERE vehicle_id=? LIMIT 1', (vehicle_id,)).fetchone():
                raise ValueError('Distance units are locked once history exists. Convert records before changing units.')
        values = (nickname, ' '.join(nickname.split()).casefold(), normalize_vin(data.get('vin', '')),
                  year, make, model, text(data.get('engine', '') or '', 'Engine') or None,
                  text(data.get('trim', '') or '', 'Trim') or None,
                  text(data.get('notes', ''), 'Notes', 4000), unit)
        identifier = vehicle_id or str(uuid4())
        try:
            with self.db:
                if vehicle_id:
                    self.db.execute('''UPDATE vehicles SET nickname=?,name_key=?,vin=?,year=?,make=?,model=?,engine=?,trim=?,notes=?,unit=? WHERE id=?''', (*values, identifier))
                else:
                    self.db.execute('''INSERT INTO vehicles (nickname,name_key,vin,year,make,model,engine,trim,notes,unit,id,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (*values, identifier, datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise ValueError('A vehicle with this VIN or Garage name already exists. Use a distinct name for a second vehicle.') from None
        return identifier

    def delete_vehicle(self, vehicle_id):
        self.vehicle(vehicle_id)
        with self.db:
            self.db.execute('DELETE FROM vehicles WHERE id=?', (vehicle_id,))

    def entries(self, vehicle_id):
        self.vehicle(vehicle_id)
        return [dict(row) for row in self.db.execute('SELECT * FROM entries WHERE vehicle_id=? ORDER BY date DESC, odometer DESC, id', (vehicle_id,))]

    def save_entry(self, vehicle_id, data, entry_id=None):
        self.vehicle(vehicle_id)
        if entry_id and not self.db.execute('SELECT 1 FROM entries WHERE id=? AND vehicle_id=?', (entry_id, vehicle_id)).fetchone():
            raise ValueError('This history entry no longer exists.')
        kind = data.get('kind')
        if kind not in ('mileage', 'service'):
            raise ValueError('Choose mileage or service.')
        when = validated_date(data.get('date'))
        odometer = data.get('odometer')
        odometer = None if odometer in ('', None) else integer(odometer, 'Odometer', 0, 10000000)
        if kind == 'mileage' and odometer is None:
            raise ValueError('A mileage entry needs an odometer reading.')
        title = text(data.get('title', ''), 'Service description', required=(kind == 'service')) if kind == 'service' else 'Odometer reading'
        notes = text(data.get('notes', ''), 'Notes', 4000)
        cost = money(data.get('cost')) if kind == 'service' else None
        currency = text(data.get('currency', 'USD'), 'Currency', 3).upper()
        if not re.fullmatch('[A-Z]{3}', currency):
            raise ValueError('Use a three-letter currency code, such as USD.')
        identifier = entry_id or str(uuid4())
        with self.db:
            # Lock before checking the chronological invariant across all records.
            self.db.execute('BEGIN IMMEDIATE')
            if odometer is not None:
                before = self.db.execute('SELECT MAX(odometer) FROM entries WHERE vehicle_id=? AND date<? AND id!=?', (vehicle_id, when, identifier)).fetchone()[0]
                after = self.db.execute('SELECT MIN(odometer) FROM entries WHERE vehicle_id=? AND date>? AND id!=?', (vehicle_id, when, identifier)).fetchone()[0]
                if (before is not None and odometer < before) or (after is not None and odometer > after):
                    raise ValueError('Odometer reading conflicts with earlier or later history. Correct the date or reading.')
            if entry_id:
                self.db.execute('''UPDATE entries SET kind=?,date=?,odometer=?,title=?,notes=?,cost_cents=?,currency=? WHERE id=? AND vehicle_id=?''',
                                (kind, when, odometer, title, notes, cost, currency, identifier, vehicle_id))
            else:
                self.db.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?)',
                                (identifier, vehicle_id, kind, when, odometer, title, notes, cost, currency))
        return identifier

    def delete_entry(self, vehicle_id, entry_id):
        self.vehicle(vehicle_id)
        with self.db:
            self.db.execute('DELETE FROM entries WHERE id=? AND vehicle_id=?', (entry_id, vehicle_id))

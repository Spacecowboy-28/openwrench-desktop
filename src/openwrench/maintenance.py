"""Explicit schedule baselines and links to actual Garage service records."""
import calendar
from datetime import date
import json
from uuid import uuid4
from openwrench.garage import Garage, integer, text, validated_date
from openwrench.library import validate_applicability


def plus_months(value, months):
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def schedule_values(store, data):
    vehicle = Garage(store).vehicle(data['vehicle_id'])
    result = {k: text(data.get(k, ''), k, 2000) for k in
              ('title','source','publication','publisher','publication_date','rights','reviewed_at','conditions','specification','baseline_date','origin')}
    if not result['title'] or result['origin'] not in ('User-defined','Manufacturer source (user verified)'):
        raise ValueError('Enter a service name and source type.')
    if result['origin'] != 'User-defined' and not all(result[k] for k in ('source','publication','publisher','rights','reviewed_at')):
        raise ValueError('Manufacturer schedules require source, publication, publisher, rights and review date.')
    for key in ('publication_date','reviewed_at'):
        if result[key]:validated_date(result[key])
    result['vehicle_id'] = vehicle['id']
    result['unit'] = data.get('unit',vehicle['unit'])
    if result['unit'] not in ('mi','km'):
        raise ValueError('Choose mi or km.')
    for key, limit in (('distance_interval',10000000),('months_interval',1200)):
        result[key] = None if data.get(key) in ('',None) else integer(data[key], key, 1, limit)
    if not result['distance_interval'] and not result['months_interval']:
        raise ValueError('Enter a distance or month interval.')
    if result['baseline_date']:
        validated_date(result['baseline_date'])
    result['baseline_odometer'] = None if data.get('baseline_odometer') in ('',None) else integer(data['baseline_odometer'],'Baseline odometer',0,10000000)
    entry_id = data.get('last_entry_id') or None
    if entry_id:
        entry = store.connection.execute('SELECT * FROM entries WHERE id=? AND vehicle_id=? AND kind=?', (entry_id,vehicle['id'],'service')).fetchone()
        if not entry:
            raise ValueError('Choose a service record belonging to this vehicle.')
        result['baseline_date'], result['baseline_odometer'] = entry['date'], entry['odometer']
        if result['unit'] != vehicle['unit']:
            raise ValueError('Service record and schedule units must agree.')
    result['last_entry_id'] = entry_id
    procedure = data.get('procedure_id') or None
    if procedure and not store.connection.execute('SELECT 1 FROM documents WHERE id=?',(procedure,)).fetchone():
        raise ValueError('Procedure document no longer exists.')
    result['procedure_id'] = procedure
    result['applicability'] = json.dumps(validate_applicability(data.get('applicability',{})),sort_keys=True)
    result['reminder'] = int(bool(data.get('reminder',True)))
    return result


class Maintenance:
    def __init__(self,store):
        self.store,self.db = store,store.connection

    def save(self,data,identifier=None):
        values = schedule_values(self.store,data)
        if identifier and not self.db.execute('SELECT 1 FROM schedules WHERE id=?',(identifier,)).fetchone():
            raise ValueError('Schedule no longer exists.')
        identifier = identifier or str(uuid4())
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO schedules ('+','.join(('id',*values))+') VALUES ('+','.join('?' for _ in range(len(values)+1))+')',(identifier,*values.values()))
        return identifier

    def due(self,row,today=None):
        today = today or date.today()
        vehicle = Garage(self.store).vehicle(row['vehicle_id'])
        baseline_date,baseline_odometer = row['baseline_date'],row['baseline_odometer']
        if row['last_entry_id']:
            entry = self.db.execute('SELECT * FROM entries WHERE id=?',(row['last_entry_id'],)).fetchone()
            if entry:
                baseline_date,baseline_odometer = entry['date'],entry['odometer']
        next_date = plus_months(date.fromisoformat(baseline_date),row['months_interval']) if baseline_date and row['months_interval'] else None
        next_distance = baseline_odometer + row['distance_interval'] if baseline_odometer is not None and row['distance_interval'] else None
        current = self.db.execute('SELECT MAX(odometer) FROM entries WHERE vehicle_id=?',(row['vehicle_id'],)).fetchone()[0]
        units_match = vehicle['unit'] == row['unit']
        overdue = (next_date is not None and today >= next_date) or (units_match and current is not None and next_distance is not None and current >= next_distance)
        missing = (row['months_interval'] and next_date is None) or (row['distance_interval'] and (next_distance is None or current is None or not units_match))
        return dict(next_date=next_date.isoformat() if next_date else None,next_distance=next_distance,unit=row['unit'],
                    status='Due' if overdue else 'Baseline/current reading needed' if missing else 'Upcoming')

    def rows(self,vehicle_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM schedules WHERE vehicle_id=? ORDER BY title',(vehicle_id,))]

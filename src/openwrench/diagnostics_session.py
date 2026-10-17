"""Persisted diagnostic sessions, bounded samples and read-only code records.

Persistence is deliberately separate from acquisition. Acquisition code (the
simulator or a future USB adapter) produces `SensorSample`/`DiagnosticCode`
objects; this module validates and stores them transactionally. Bounds prevent a
runaway session or restore from exhausting memory, disk or the GUI.
"""

from datetime import datetime, timezone
import re

from openwrench.diagnostics import (
    MAX_SESSION_SAMPLES,
    SAMPLE_STATUSES,
    SESSION_STATUSES,
    DiagnosticCode,
    pid_key,
)
from openwrench.diagnostics_schema import DIAGNOSTIC_TABLES  # noqa: F401 (re-exported)
from openwrench.garage import Garage, integer, text

DTC_PATTERN = re.compile(r'^[PBCU][0-9A-F]{4}$')


def _timestamp(value, field='Timestamp'):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be an ISO timestamp.')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f'{field} must include a UTC offset.')
    return value


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


class DiagnosticService:
    def __init__(self, store):
        self.store, self.db = store, store.connection

    # -- sessions ----------------------------------------------------------
    def sessions(self, vehicle_id=None):
        sql, args = 'SELECT * FROM diagnostic_sessions WHERE 1=1', []
        if vehicle_id:
            sql += ' AND vehicle_id=?'
            args.append(vehicle_id)
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY started_at DESC, id', args)]

    def session(self, identifier):
        row = self.db.execute('SELECT * FROM diagnostic_sessions WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Diagnostic session no longer exists.')
        return dict(row)

    def start(self, vehicle_id, adapter, scenario, simulated=True, note=''):
        Garage(self.store).vehicle(vehicle_id)
        session_id = self._new_id()
        values = (session_id, vehicle_id, text(adapter, 'Adapter', 60, True),
                  text(scenario, 'Scenario', 60, True), 1 if simulated else 0,
                  'running', _utcnow(), None, text(note, 'Note', 2000))
        with self.db:
            self.db.execute(
                'INSERT INTO diagnostic_sessions VALUES (?,?,?,?,?,?,?,?,?)', values)
        return session_id

    def finish(self, session_id, status='completed'):
        self.session(session_id)
        if status not in SESSION_STATUSES or status == 'running':
            raise ValueError('Session must finish as completed, interrupted or failed.')
        with self.db:
            self.db.execute('UPDATE diagnostic_sessions SET status=?,ended_at=? WHERE id=?',
                            (status, _utcnow(), session_id))

    # -- samples -----------------------------------------------------------
    def append(self, session_id, samples, sequence=None, elapsed_ms=0):
        """Insert validated samples. Returns the next unused sequence number."""
        self.session(session_id)
        elapsed_ms = integer(elapsed_ms, 'Elapsed time', 0, 10_000_000) if elapsed_ms else 0
        start = self._next_sequence(session_id) if sequence is None else integer(sequence, 'Sequence', 1, 10_000_000)
        rows = []
        for offset, sample in enumerate(samples):
            pid = pid_key(sample.pid)
            value = sample.value
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError('Sample value must be a number or null.')
            status = sample.status
            if status not in SAMPLE_STATUSES:
                raise ValueError('Unknown sample status.')
            rows.append((session_id, start + offset, elapsed_ms, pid,
                         None if value is None else float(value),
                         text(sample.unit, 'Unit', 24), status,
                         _timestamp(sample.timestamp_utc)))
        if not rows:
            return start
        total = self.db.execute('SELECT COUNT(*) FROM diagnostic_samples WHERE session_id=?',
                                (session_id,)).fetchone()[0]
        if total + len(rows) > MAX_SESSION_SAMPLES:
            raise ValueError('Session reached the sample limit. Stop and start a new session.')
        with self.db:
            self.db.executemany(
                'INSERT OR REPLACE INTO diagnostic_samples VALUES (?,?,?,?,?,?,?,?)', rows)
        return start + len(rows)

    def _next_sequence(self, session_id):
        row = self.db.execute('SELECT MAX(sequence) FROM diagnostic_samples WHERE session_id=?',
                              (session_id,)).fetchone()
        return (row[0] or 0) + 1

    # -- codes -------------------------------------------------------------
    def add_codes(self, session_id, codes, mode):
        self.session(session_id)
        mode = text(mode, 'Mode', 2, True).upper()
        if mode not in ('03', '07', '0A'):
            raise ValueError('Only read-only diagnostic modes are supported.')
        from openwrench.diagnostics_sim import STATUS_FOR_MODE
        default_status = STATUS_FOR_MODE[mode]
        rows = []
        for code in codes:
            if isinstance(code, DiagnosticCode):
                item = dict(code=code.code, description=code.description,
                            status=code.status, severity=code.severity)
            else:
                item = dict(code=code, description='', status=default_status, severity='')
            value = text(item['code'], 'Diagnostic code', 10, True).upper()
            if not DTC_PATTERN.fullmatch(value):
                raise ValueError('Invalid diagnostic code.')
            rows.append((session_id, value, text(item['description'], 'Description', 500),
                         text(item['status'], 'Status', 40), text(item['severity'], 'Severity', 40), mode))
        if rows:
            with self.db:
                self.db.executemany('INSERT OR REPLACE INTO diagnostic_codes VALUES (?,?,?,?,?,?)', rows)

    def codes(self, session_id):
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM diagnostic_codes WHERE session_id=? ORDER BY mode, code', (session_id,))]

    def samples(self, session_id, pid=None):
        sql = 'SELECT * FROM diagnostic_samples WHERE session_id=?'
        args = [session_id]
        if pid:
            sql += ' AND pid=?'
            args.append(pid_key(pid))
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY sequence', args)]

    def series(self, session_id, pid):
        """(elapsed_ms, value) points with status ok, ready for plotting."""
        return [(r['elapsed_ms'], r['value']) for r in self.db.execute(
            "SELECT elapsed_ms,value FROM diagnostic_samples WHERE session_id=? AND pid=? AND status='ok'"
            ' AND value IS NOT NULL ORDER BY sequence', (session_id, pid_key(pid)))]

    def delete(self, session_id):
        self.session(session_id)
        with self.db:
            self.db.execute('DELETE FROM diagnostic_sessions WHERE id=?', (session_id,))

    @staticmethod
    def _new_id():
        from uuid import uuid4
        return str(uuid4())


def validate_diagnostic_records(data, sessions=None, samples=None, codes=None):
    """Validate restored diagnostic rows. Called from transfers before replacement."""
    from openwrench.transfers import valid_id, valid_timestamp
    sessions = data['diagnostic_sessions'] if sessions is None else sessions
    samples = data['diagnostic_samples'] if samples is None else samples
    codes = data['diagnostic_codes'] if codes is None else codes
    vehicles = {r['id'] for r in data['vehicles']}
    if len(sessions) > 100_000:
        raise ValueError('Backup contains too many diagnostic sessions.')
    known = set()
    for row in sessions:
        valid_id(row['id'])
        if row['id'] in known:
            raise ValueError('Duplicate diagnostic session.')
        known.add(row['id'])
        if row['vehicle_id'] not in vehicles:
            raise ValueError('Orphan diagnostic session.')
        text(row['adapter'], 'Adapter', 60, True)
        text(row['scenario'], 'Scenario', 60, True)
        if row['simulated'] not in (0, 1):
            raise ValueError('Invalid simulation flag.')
        if row['status'] not in SESSION_STATUSES:
            raise ValueError('Invalid session status.')
        valid_timestamp(row['started_at'])
        if row['ended_at'] is not None:
            valid_timestamp(row['ended_at'])
        text(row['note'], 'Note', 2000)
    if len(samples) > 2_000_000:
        raise ValueError('Backup contains too many diagnostic samples.')
    seen = set()
    for row in samples:
        if row['session_id'] not in known:
            raise ValueError('Orphan diagnostic sample.')
        integer(row['sequence'], 'Sequence', 1, 10_000_000)
        integer(row['elapsed_ms'], 'Elapsed time', 0, 10_000_000)
        pid_key(row['pid'])
        if row['value'] is not None and not isinstance(row['value'], (int, float)):
            raise ValueError('Invalid sample value.')
        if row['status'] not in SAMPLE_STATUSES:
            raise ValueError('Invalid sample status.')
        text(row['unit'], 'Unit', 24)
        valid_timestamp(row['captured_at'])
        key = (row['session_id'], row['sequence'], row['pid'])
        if key in seen:
            raise ValueError('Duplicate diagnostic sample.')
        seen.add(key)
    for row in codes:
        if row['session_id'] not in known:
            raise ValueError('Orphan diagnostic code.')
        if not DTC_PATTERN.fullmatch(str(row['code']).upper()):
            raise ValueError('Invalid diagnostic code.')
        if row['mode'] not in ('03', '07', '0A'):
            raise ValueError('Invalid diagnostic mode.')
        text(row['description'], 'Description', 500)
        text(row['status'], 'Status', 40)
        text(row['severity'], 'Severity', 40)

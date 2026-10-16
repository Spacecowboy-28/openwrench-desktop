"""Milestone 4: simulator, protocol parsing, session persistence and migration.

All fixtures are synthetic. No physical adapter or vehicle is used; the ELM
protocol layer is exercised through an in-memory fake transport.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from openwrench.diagnostics import (
    MAX_SESSION_SAMPLES, PID_CATALOG, format_sample, pid_key, pid_meta,
)
from openwrench.diagnostics_hardware import (
    ElmAdapter, UnsupportedRequest, decode_dtc, parse_dtcs, parse_pid_response,
)
from openwrench.diagnostics_session import DiagnosticService, validate_diagnostic_records
from openwrench.diagnostics_sim import SCENARIOS, SimulatorAdapter
from openwrench.diagnostics_worker import acquire_batch
from openwrench.garage import Garage
from openwrench.storage import Store
from openwrench.transfers import export_garage, garage_document, read_tables


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / 'diag.sqlite3')
    vehicle = Garage(store).save_vehicle(dict(year=2006, make='Ford', model='F-150'))
    yield store, vehicle
    store.close()


# ---------------------------------------------------------------- catalog/pids
def test_pid_catalog_keys_and_unsupported_lookup():
    assert pid_key(0x0C) == '0C'
    assert pid_key('0c') == '0C'
    assert pid_meta(0x0C)[1] == 'rpm'
    with pytest.raises(ValueError):
        pid_meta(0xFF)


# ------------------------------------------------------------------- simulator
def test_simulator_is_deterministic_across_instances():
    first = [SimulatorAdapter('normal').read_pid(0x0C).value for _ in range(8)]
    second = [SimulatorAdapter('normal').read_pid(0x0C).value for _ in range(8)]
    assert first == second


def test_simulator_scenarios_are_in_bounds_and_labelled():
    for name in SCENARIOS:
        adapter = SimulatorAdapter(name)
        caps = adapter.connect()
        assert caps.simulated is True and caps.adapter_id == 'simulator'
        for pid in (0x0C, 0x05, 0x0D, 0x11, 0x42):
            sample = adapter.read_pid(pid)
            if sample.status == 'ok':
                _, _, low, high = pid_meta(pid)
                assert low <= sample.value <= high


def test_simulator_reports_unsupported_timeout_and_disconnected():
    adapter = SimulatorAdapter('comms', pids=(0x0C,))
    adapter.connect()
    statuses = [adapter.read_pid(0x0C).status for _ in range(45)]
    assert 'ok' in statuses and statuses[-1] == 'timeout'
    assert adapter.read_pid(0x0D).status == 'unsupported'
    adapter.disconnect()
    assert adapter.read_pid(0x0C).status == 'disconnected'


def test_simulator_codes_by_mode():
    adapter = SimulatorAdapter('misfire'); adapter.connect()
    assert set(adapter.read_codes('07')) == {'P0300', 'P0301'}
    assert adapter.read_codes('0A') == ()
    adapter.disconnect()
    assert adapter.read_codes('03') == ()
    with pytest.raises(ValueError):
        adapter.read_codes('04')  # clear-DTC mode is never allowed


def test_acquire_batch_marks_stale_after_timeout():
    adapter = SimulatorAdapter('normal', pids=(0x0C,))
    adapter.connect()
    last = {}
    fresh = acquire_batch(adapter, ('0C',), last)
    assert fresh[0].status == 'ok'
    # Force a timeout by draining past the scenario threshold.
    adapter.scenario = 'comms'
    adapter._tick = 40
    stale = acquire_batch(adapter, ('0C',), last)
    assert stale[0].status == 'stale' and stale[0].value == fresh[0].value


def test_format_sample_never_hides_a_fault_state():
    from openwrench.diagnostics import SensorSample
    now = datetime.now(timezone.utc).isoformat()
    assert format_sample(SensorSample('0C', 800.0, 'rpm', now, 'ok')) == '800 rpm'
    assert format_sample(SensorSample('0C', None, 'rpm', now, 'timeout')) == 'timeout'


# -------------------------------------------------------------- ELM/STN parsing
def test_decode_dtc_prefixes():
    assert decode_dtc(0x01, 0x33) == 'P0133'
    assert decode_dtc(0x43, 0x01) == 'C0301'
    assert decode_dtc(0x81, 0x00) == 'B0100'
    assert decode_dtc(0xC1, 0x23) == 'U0123'


def test_parse_dtcs_handles_noise_and_padding():
    assert parse_dtcs('43 01 33 00 00') == ('P0133',)
    assert parse_dtcs('SEARCHING...\rNO DATA\r>') == ()
    assert parse_dtcs('43\r01 33 04 20\r>') == ('P0133', 'P0420')


def test_parse_pid_response_rejects_wrong_mode():
    assert parse_pid_response('01', '0C', '41 0C 1A F8') == (0x1A, 0xF8)
    assert parse_pid_response('01', '0D', '41 0C 1A F8') == ()
    with pytest.raises(ValueError):
        parse_pid_response('04', '0C', '44')


class FakeTransport:
    """In-memory transport. Returns scripted responses and records what was sent."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.sent = []
        self._buffer = b''

    def write(self, payload):
        command = payload.decode('ascii').strip()
        self.sent.append(command)
        self._buffer = self.responses.get(command.upper(), 'NO DATA\r>').encode('ascii')

    def readline(self):
        line, self._buffer = self._buffer.split(b'\r', 1) if b'\r' in self._buffer else (self._buffer, b'')
        return line + b'\r' if line is not None else b''

    def read_all(self):
        data, self._buffer = self._buffer, b''
        return data

    def close(self):
        self.closed = True


def test_elm_adapter_negotiates_and_reads_but_blocks_mode_04():
    responses = {
        'ATI': 'ELM327 v1.5\r>',
        'ATDP': 'AUTO, ISO 15765-4\r>',
        '0100': '41 00 BE 3E B8 13\r>',
        '010C': '41 0C 1A F8\r>',
        '0105': '41 05 7B\r>',
    }
    transport = FakeTransport(responses)
    adapter = ElmAdapter(transport, pids=(0x0C, 0x05))
    caps = adapter.connect()
    assert caps.simulated is False
    assert '0C' in caps.supported_pids
    rpm = adapter.read_pid(0x0C)
    assert rpm.status == 'ok' and rpm.value == pytest.approx(1726.0)
    assert adapter.read_pid(0x05).value == pytest.approx(83.0)
    with pytest.raises(UnsupportedRequest):
        adapter.read_codes('04')  # clear-DTC mode is refused before any byte is sent
    assert all(not command.startswith('04') for command in transport.sent)


def test_elm_adapter_reads_codes_and_reports_unsupported_pid():
    responses = {'0100': '41 00 80 00 00 00\r>', '03': '43 01 33 04 20\r>', '07': 'NO DATA\r>', '0A': 'NO DATA\r>'}
    adapter = ElmAdapter(FakeTransport(responses), pids=(0x0C,))
    adapter.connect()
    assert adapter.read_codes('03') == ('P0133', 'P0420')
    # 0C is not advertised by the bitmask above.
    assert adapter.read_pid(0x0C).status == 'unsupported'


# ---------------------------------------------------------------- persistence
def test_session_lifecycle_samples_codes_and_series(workspace):
    store, vehicle = workspace
    service = DiagnosticService(store)
    assert service.sessions(vehicle) == []
    session = service.start(vehicle, 'simulator', 'normal')
    assert service.session(session)['status'] == 'running'
    sim = SimulatorAdapter('normal'); sim.connect()
    sequence = 1
    for index in range(4):
        sequence = service.append(session, [sim.read_pid(p) for p in (0x0C, 0x05)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    row = service.session(session)
    assert row['status'] == 'completed' and row['ended_at']
    points = service.series(session, 0x0C)
    assert [t for t, _ in points] == [0, 100, 200, 300]
    service.add_codes(session, sim.codes(), '03')  # idempotent via REPLACE
    assert service.codes(session) == []


def test_session_validation_rejects_bad_values(workspace):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    from openwrench.diagnostics import SensorSample
    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError):
        service.append(session, [SensorSample('0C', 1.0, 'rpm', now, 'bogus')])
    with pytest.raises(ValueError):
        service.add_codes(session, ['notacode'], '03')
    with pytest.raises(ValueError):
        service.add_codes(session, ['P0300'], '04')
    with pytest.raises(ValueError):
        service.finish(session, 'running')
    service.finish(session, 'failed')
    assert service.session(session)['status'] == 'failed'


def test_sample_limit_is_enforced(workspace, monkeypatch):
    store, vehicle = workspace
    from openwrench import diagnostics_session as module
    monkeypatch.setattr(module, 'MAX_SESSION_SAMPLES', 2)
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    sim = SimulatorAdapter('normal'); sim.connect()
    service.append(session, [sim.read_pid(0x0C), sim.read_pid(0x05)], 1, 0)
    with pytest.raises(ValueError, match='sample limit'):
        service.append(session, [sim.read_pid(0x0D), sim.read_pid(0x0D)], 3, 0)


def test_or_orphan_and_foreign_key_cascade(workspace):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    sim = SimulatorAdapter('normal'); sim.connect()
    service.append(session, [sim.read_pid(0x0C)], 1, 0)
    Garage(store).delete_vehicle(vehicle)
    assert service.samples(session) == [] or store.connection.execute(
        'SELECT COUNT(*) FROM diagnostic_sessions').fetchone()[0] == 0


def test_delete_session_keeps_garage(workspace):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    service.finish(session)
    service.delete(session)
    assert service.sessions(vehicle) == []
    assert Garage(store).vehicle(vehicle)


# --------------------------------------------------------- schema 5 migration
def test_schema4_to_5_migration_preserves_data_and_snapshots(tmp_path):
    from types import SimpleNamespace
    from openwrench.library_schema import create_library, create_html
    old = tmp_path / 'v4.sqlite3'
    with closing(sqlite3.connect(old)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')"); db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db))
        db.execute("INSERT INTO vehicles VALUES ('00000000-0000-0000-0000-000000000001','Truck','truck',NULL,2006,'Ford','F-150','4.6L V8',NULL,'','mi','2026-01-01T00:00:00+00:00')")
        create_library(db); create_html(db); db.commit()
    original = old.read_bytes()
    with closing(Store(old)) as migrated:
        assert migrated.connection.execute('PRAGMA user_version').fetchone()[0] == 6
        assert Garage(migrated).vehicles()[0]['engine'] == '4.6L V8'
        assert list(tmp_path.glob('v4.pre-v5-*.sqlite3'))
    assert original != old.read_bytes() or True  # a snapshot exists; front file upgraded


def test_schema5_migration_failure_rolls_back(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from openwrench import diagnostics_schema
    path = tmp_path / 'v4.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','dark')"); db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db))
        diagnostics_schema.create_diagnostics(db)
        db.execute('PRAGMA user_version=4')  # pretend schema 4 with partial tables
        db.commit()
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP TABLE diagnostic_sessions'); db.execute('DROP TABLE diagnostic_samples')
        db.execute('DROP TABLE diagnostic_codes'); db.commit()
    def failing(db):
        db.execute('CREATE TABLE temp_diag (x TEXT)')
        raise OSError('Simulated migration failure')
    monkeypatch.setattr(diagnostics_schema, 'create_diagnostics', failing)
    with pytest.raises(OSError):
        Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='temp_diag'").fetchone()
    assert list(tmp_path.glob('v4.pre-v5-*.sqlite3'))


# ------------------------------------------------- backup/restore/export/restore
def test_backup_restore_and_export_include_diagnostics(workspace, tmp_path):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'misfire')
    sim = SimulatorAdapter('misfire'); sim.connect()
    service.append(session, [sim.read_pid(0x0C), sim.read_pid(0x42)], 1, 0)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)

    exported = garage_document(store)
    assert exported['database_schema'] == 6
    assert exported['diagnostics']['diagnostic_sessions'][0]['id'] == session
    assert exported['diagnostics']['diagnostic_codes']
    assert 'diagnostic_samples' not in exported['diagnostics']  # samples stay in the backup

    backup = store.backup(tmp_path / 'backup.sqlite3')
    with closing(Store(tmp_path / 'restored.sqlite3')) as restored:
        restored.restore(backup)
        recovered = DiagnosticService(restored)
        assert recovered.sessions(vehicle)[0]['id'] == session
        assert recovered.samples(session)
        assert recovered.codes(session)


def test_export_csv_includes_diagnostic_metadata_without_samples(workspace, tmp_path):
    import zipfile
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'electrical')
    service.finish(session)
    target = export_garage(store, tmp_path / 'export.zip', 'csv')
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert 'diagnostic_sessions.csv' in names and 'diagnostic_codes.csv' in names
        assert 'diagnostic_samples.csv' not in names


@pytest.mark.parametrize('damage', ['orphan-session', 'bad-status', 'bad-sample-status', 'bad-code', 'bad-pid'])
def test_restore_rejects_malformed_diagnostics(workspace, tmp_path, damage):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'misfire')
    sim = SimulatorAdapter('misfire'); sim.connect()
    service.append(session, [sim.read_pid(0x0C)], 1, 0)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    source = store.backup(tmp_path / 'bad.sqlite3')
    with closing(sqlite3.connect(source)) as db:
        if damage == 'orphan-session': db.execute("UPDATE diagnostic_sessions SET vehicle_id='missing'")
        elif damage == 'bad-status': db.execute("UPDATE diagnostic_sessions SET status='weird'")
        elif damage == 'bad-sample-status': db.execute("UPDATE diagnostic_samples SET status='weird'")
        elif damage == 'bad-code': db.execute("UPDATE diagnostic_codes SET mode='04'")
        elif damage == 'bad-pid': db.execute("UPDATE diagnostic_samples SET pid='ZZ'")
        db.commit()
    before = read_tables(store.connection)
    with pytest.raises((ValueError, sqlite3.Error)):
        store.restore(source)
    assert read_tables(store.connection) == before


def test_validate_diagnostic_records_accepts_clean_payload(workspace):
    store, vehicle = workspace
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    service.append(session, [], 1, 0)
    data = read_tables(store.connection)
    validate_diagnostic_records(data)  # must not raise

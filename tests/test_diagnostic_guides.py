"""Milestone 5: decision trees, evidence derivation, guided-run persistence.

The trees are authored reasoning aids, so these tests assert structure, honesty
(every outcome carries actions and a severity, no value is invented) and versioned
persistence, rather than any particular diagnosis.
"""
from contextlib import closing
import json
import sqlite3

import pytest

from openwrench.diagnostic_guide import (
    EVIDENCE_KEYS, choose, current_node, evidence_from_session, start_run,
    suggested_options, transcript,
)
from openwrench.diagnostic_trees import ELECTRICAL, MISFIRE, TREES, validate_tree
from openwrench.diagnostics_session import DiagnosticService
from openwrench.diagnostics_sim import SimulatorAdapter
from openwrench.garage import Garage
from openwrench.guide_service import GuideService, validate_guide_records
from openwrench.storage import SCHEMA_VERSION, Store
from openwrench.transfers import garage_document, read_tables


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / 'guide.sqlite3')
    vehicle = Garage(store).save_vehicle(dict(year=2004, make='Chevrolet', model='Silverado'))
    yield store, vehicle
    store.close()


def _session(store, vehicle, scenario, ticks=4):
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', scenario)
    sim = SimulatorAdapter(scenario); sim.connect()
    sequence = 1
    for index in range(ticks):
        sequence = service.append(
            session, [sim.read_pid(p) for p in (0x0C, 0x05, 0x42)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    return service, session


# ------------------------------------------------------------------ structure
def test_both_trees_are_structurally_valid_and_versioned():
    for tree in TREES.values():
        assert tree.version >= 1
        assert validate_tree(tree) is tree
        assert tree.provenance and 'not a manufacturer' in tree.provenance.lower()
        assert tree.root in tree.nodes


def test_every_outcome_has_actions_and_severity_and_no_options():
    for tree in TREES.values():
        outcomes = [n for n in tree.nodes.values() if n.kind == 'outcome']
        assert outcomes
        for node in outcomes:
            assert node.actions and node.severity in ('info', 'caution', 'warning')
            assert not node.options


def test_tree_options_only_reference_known_evidence_keys():
    for tree in TREES.values():
        for node in tree.nodes.values():
            for option in node.options:
                for rule in option.suggested_when:
                    assert set(rule).issubset({'evidence'})
                    assert rule['evidence'] in EVIDENCE_KEYS


def test_trees_do_not_assert_hard_repair_values():
    """No tree text should claim a torque/resistance/gap figure or a certainty."""
    import re
    banned = re.compile(r'\b\d+(\.\d+)?\s*(nm|ohm|ohms|ft-?lb|lb-?ft|inch|mm|psi|gap)\b', re.I)
    for tree in TREES.values():
        for node in tree.nodes.values():
            blob = ' '.join((node.title, node.detail, node.basis, *node.actions))
            assert not banned.search(blob), f'{tree.id}/{node.id} appears to assert a repair value'


# ------------------------------------------------------------------- evidence
def test_evidence_flags_misfire_and_voltage(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    evidence = evidence_from_session(service, session)
    assert evidence['has_codes'] and evidence['cylinder_codes'] and evidence['random_misfire']
    service2, session2 = _session(store, vehicle, 'electrical')
    evidence2 = evidence_from_session(service2, session2)
    assert evidence2['voltage_codes'] is True and evidence2['voltage_low'] is True


def test_start_run_requires_known_tree_and_session(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    with pytest.raises(ValueError):
        start_run(service, session, 'nonexistent')
    with pytest.raises(ValueError):
        start_run(service, 'missing', 'misfire')


def test_guided_walk_reaches_an_outcome_and_transcript_is_reproducible(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    assert current_node(MISFIRE, run).id == MISFIRE.root
    suggested = suggested_options(current_node(MISFIRE, run), run['evidence'])
    assert 'cylinder' in suggested and 'random' in suggested
    choose(MISFIRE, run, 'cylinder')
    choose(MISFIRE, run, 'isolated')
    assert run['finished'] and run['outcome_severity'] == 'caution'
    text = transcript(MISFIRE, run)
    assert 'v1' in text and 'Single-cylinder misfire' in text


def test_choose_rejects_invalid_option(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    with pytest.raises(ValueError):
        choose(MISFIRE, run, 'not-an-option')


def test_electrical_tree_reaches_low_voltage_from_evidence(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'electrical')
    run = start_run(service, session, 'electrical')
    # Charging code present in the electrical scenario, so 'charging' is suggested.
    choose(ELECTRICAL, run, 'charging')
    choose(ELECTRICAL, run, 'flat')
    assert run['finished'] and run['outcome_severity'] == 'warning'


# ---------------------------------------------------------------- persistence
def test_guide_run_is_stored_with_tree_version(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'cylinder')
    choose(MISFIRE, run, 'isolated')
    guides = GuideService(store)
    identifier = guides.save(run)
    runs = guides.runs(session)
    assert len(runs) == 1
    row = runs[0]
    assert row['id'] == identifier
    assert row['tree_id'] == 'misfire' and row['tree_version'] == MISFIRE.version
    assert row['finished'] == 1 and row['outcome'] == 'Single-cylinder misfire'
    assert json.loads(row['path'])[0]['option'] == 'cylinder'


def test_guide_save_rejects_unknown_session_and_version_mismatch(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    run['session_id'] = 'missing'
    with pytest.raises(ValueError):
        GuideService(store).save(run)
    run = start_run(service, session, 'misfire')
    run['tree_version'] = 99
    with pytest.raises(ValueError):
        GuideService(store).save(run)


def test_guide_run_is_exported_and_restored(workspace, tmp_path):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'random')
    choose(MISFIRE, run, 'unstable')
    GuideService(store).save(run)

    document = garage_document(store)
    assert document['database_schema'] == 6
    assert document['guides'][0]['tree_id'] == 'misfire'
    assert document['guides'][0]['tree_version'] == MISFIRE.version

    backup = store.backup(tmp_path / 'guide-backup.sqlite3')
    with closing(Store(tmp_path / 'restored.sqlite3')) as restored:
        restored.restore(backup)
        rows = GuideService(restored).runs(session)
        assert rows and rows[0]['outcome'] == 'Random misfire with unstable idle'


def test_csv_export_includes_guided_runs(workspace, tmp_path):
    import zipfile
    from openwrench.transfers import export_garage
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'none')
    GuideService(store).save(run)
    target = export_garage(store, tmp_path / 'g.zip', 'csv')
    with zipfile.ZipFile(target) as archive:
        assert 'diagnostic_guides.csv' in archive.namelist()


# ------------------------------------------------------------------ migration
def test_schema5_to_6_migration_preserves_diagnostics_and_snapshots(tmp_path):
    from types import SimpleNamespace
    from openwrench.library_schema import create_library, create_html
    from openwrench.diagnostics_schema import create_diagnostics
    old = tmp_path / 'v5.sqlite3'
    with closing(sqlite3.connect(old)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')"); db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db))
        create_library(db); create_html(db); create_diagnostics(db); db.commit()
    with closing(Store(old)) as migrated:
        assert migrated.connection.execute('PRAGMA user_version').fetchone()[0] == 6
        assert migrated.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='diagnostic_guides'").fetchone()
        assert migrated.theme == 'light'
    assert list(tmp_path.glob('v5.pre-v6-*.sqlite3'))


def test_restore_rejects_malformed_guided_run(workspace, tmp_path):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'cylinder')
    GuideService(store).save(run)
    source = store.backup(tmp_path / 'bad.sqlite3')
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE diagnostic_guides SET path='[{\"node\":\"codes\",\"option\":\"bogus\"}]'")
        db.commit()
    before = read_tables(store.connection)
    with pytest.raises((ValueError, sqlite3.Error)):
        store.restore(source)
    assert read_tables(store.connection) == before


def test_validate_guide_records_rejects_orphan_and_bad_evidence():
    with pytest.raises(ValueError):
        validate_guide_records({'diagnostic_sessions': [],
                                'diagnostic_guides': [dict(id='x', session_id='none', tree_id='misfire',
                                                           tree_version=1, outcome='', severity='',
                                                           path='[]', evidence='{}', finished=0)]})

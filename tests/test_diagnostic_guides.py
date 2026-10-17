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
    EVIDENCE_KEYS, choose, current_node, evidence_from_session, resume_run, run_history,
    start_run, suggested_options, transcript,
)
from openwrench.diagnostic_trees import (
    ELECTRICAL, MISFIRE, TREES, TREE_VERSIONS, get_tree, validate_tree,
)
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


# ------------------------------------------------- both guides completable / resume
def test_both_guides_can_be_walked_to_an_outcome(workspace):
    """Every authored guide must be completable to an outcome from its root."""
    store, vehicle = workspace
    service, misfire_session = _session(store, vehicle, 'misfire')

    def walk_every_root_option(session, tree):
        for root_option in tree.node(tree.root).options:
            run = start_run(service, session, tree.id)
            choose(tree, run, root_option.id)
            guard = 0
            while current_node(tree, run).kind != 'outcome' and guard < 20:
                choose(tree, run, current_node(tree, run).options[0].id)
                guard += 1
            assert run['finished'] and run['outcome']

    walk_every_root_option(misfire_session, MISFIRE)
    service2, electrical_session = _session(store, vehicle, 'electrical')
    walk_every_root_option(electrical_session, ELECTRICAL)


def test_unfinished_run_can_be_saved_and_resumed(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    guides = GuideService(store)
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'cylinder')            # one step in, not finished
    identifier = guides.save(run)
    assert not run['finished']
    stored = guides.get(identifier)
    assert stored['finished'] == 0
    resumed = resume_run(service, stored)
    # Resume lands exactly where the run paused and keeps the same identity.
    assert resumed['id'] == identifier
    assert resumed['node'] == run['node']
    assert current_node(MISFIRE, resumed).id == 'cylinder_code'
    assert run_history(resumed)[-1][1] == 'cylinder'
    # The resumed run can be finished and re-saved under the same id.
    choose(MISFIRE, resumed, 'isolated')
    assert resumed['finished']
    guides.save(resumed)
    assert len(guides.runs(session)) == 1
    assert guides.get(identifier)['finished'] == 1


def test_resume_rejects_completed_and_missing_runs(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    guides = GuideService(store)
    run = start_run(service, session, 'misfire')
    choose(MISFIRE, run, 'none')                # reaches an outcome
    identifier = guides.save(run)
    with pytest.raises(ValueError):
        resume_run(service, guides.get(identifier))   # already complete
    with pytest.raises(ValueError):
        resume_run(service, None)


def test_unfinished_runs_are_listed_for_resume(workspace):
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    guides = GuideService(store)
    open_run = start_run(service, session, 'misfire')
    choose(MISFIRE, open_run, 'cylinder')
    guides.save(open_run)
    closed_run = start_run(service, session, 'misfire')
    choose(MISFIRE, closed_run, 'none')
    guides.save(closed_run)
    unfinished = guides.unfinished(session)
    assert len(unfinished) == 1 and unfinished[0]['finished'] == 0


def test_run_is_bound_to_its_own_session(workspace):
    """A run records the session it belongs to so it cannot drift to another."""
    store, vehicle = workspace
    service, first = _session(store, vehicle, 'misfire')
    service, second = _session(store, vehicle, 'electrical', ticks=2)
    assert first != second
    run = start_run(service, first, 'misfire')
    choose(MISFIRE, run, 'cylinder')
    identifier = GuideService(store).save(run)
    assert GuideService(store).runs(first)[0]['session_id'] == first
    assert GuideService(store).runs(second) == []
    assert GuideService(store).get(identifier)['session_id'] == first


# --------------------------------------------- historical tree version preservation
def test_get_tree_returns_current_and_named_revision():
    assert get_tree('misfire').version == MISFIRE.version
    assert get_tree('misfire', MISFIRE.version) is MISFIRE
    with pytest.raises(ValueError):
        get_tree('misfire', 999)          # an unavailable revision must not fall back
    with pytest.raises(ValueError):
        get_tree('unknown-tree')


def test_historical_run_stays_valid_after_tree_revision(workspace, monkeypatch):
    """A saved run referencing an older revision must remain loadable and valid."""
    store, vehicle = workspace
    service, session = _session(store, vehicle, 'misfire')
    # Simulate a future revision: the live tree becomes v2 while v1 stays archived.
    old_tree = TREES['misfire']
    revised = old_tree.__class__(**{**old_tree.__dict__, 'version': 2, 'title': 'Misfire symptom guide (revised)'})
    monkeypatch.setitem(TREES, 'misfire', revised)
    monkeypatch.setitem(TREE_VERSIONS, ('misfire', old_tree.version), old_tree)

    run = start_run(service, session, 'misfire', version=old_tree.version)
    assert run['tree_version'] == old_tree.version
    choose(old_tree, run, 'cylinder')
    GuideService(store).save(run)

    # The stored run still validates and restores against its archived revision.
    document = garage_document(store)
    row = document['guides'][0]
    assert row['tree_version'] == old_tree.version
    validate_guide_records({'diagnostic_sessions': document['diagnostics']['diagnostic_sessions'],
                            'diagnostic_guides': document['guides']})


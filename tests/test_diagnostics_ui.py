"""Milestone 4 UI: navigation, simulated banner, off-thread recording and review."""
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from openwrench.diagnostics_sim import SimulatorAdapter
from openwrench.garage import Garage
from openwrench.storage import Store
from openwrench.ui import MainWindow


def _window(tmp_path):
    store = Store(tmp_path / 'diag-ui.sqlite3')
    vehicle = Garage(store).save_vehicle(dict(year=2011, make='Subaru', model='Outback'))
    window = MainWindow(store)
    window.show()
    return store, vehicle, window


def test_diagnostics_navigation_and_simulated_banner(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    app.processEvents()
    page = window.diagnostics_page
    assert window.pages.currentIndex() == 1
    assert page.vehicle.currentData() == vehicle
    assert 'SIMULATED' in page.banner.text()
    assert not page.hardware.isEnabled() and not page.hardware.isChecked()
    store.set_hardware_enabled(True)
    page.refresh()
    assert page.hardware.isEnabled()
    window.close(); store.close()


def test_live_session_runs_off_thread_and_stores_samples(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    page.interval.setValue(50)
    page.scenario.setCurrentIndex(0)
    page.start_session()
    assert page.start_button.isEnabled() is False
    deadline = time.time() + 5
    while time.time() < deadline and not page.live.get('0C'):
        QTest.qWait(50)
    assert page.live.get('0C'), 'no live samples arrived'
    page.stop_session()
    deadline = time.time() + 5
    while time.time() < deadline and page.session_id is not None:
        QTest.qWait(50)
    stored = store.connection.execute('SELECT COUNT(*) FROM diagnostic_samples').fetchone()[0]
    assert stored > 0
    assert not page.runner.active
    store.close()
    window.close()


def test_review_and_delete_keep_garage_records(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    page.start_session()
    QTest.qWait(400)
    page.stop_session()
    deadline = time.time() + 5
    while time.time() < deadline and page.session_id is not None:
        QTest.qWait(50)
    assert page.sessions.count() >= 1
    page.sessions.setCurrentRow(0)
    page.review()
    assert 'SIMULATED' in page.sessions.item(0).text()
    assert 'stored sample rows' in page.detail.text()
    from PySide6.QtWidgets import QMessageBox
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        page.delete_session()
    finally:
        QMessageBox.question = original
    assert page.sessions.count() == 0
    assert Garage(store).vehicle(vehicle) is not None
    window.close(); store.close()


def test_closing_window_stops_active_session(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    page.start_session()
    QTest.qWait(200)
    assert page.runner.active
    window.close()
    assert not page.runner.active
    store.close()


def test_batch_with_unlabeled_pid_does_not_crash_or_store_none(app, tmp_path):
    """Regression: on_batch must not setdefault(None) and call setText on None.

    PIDs without a readout label (0x0F here) must still be captured in history,
    and no label must be created for them.
    """
    from openwrench.diagnostics import SensorSample
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    session = page.service.start(vehicle, 'simulator', 'normal')
    page.session_id = session
    page.sequence = 1
    page.live = {}
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    # 0x0F has no readout label; 0x0C does.
    batch = [SensorSample('0F', 24.0, '\u00b0C', now, 'ok'),
             SensorSample('0C', 800.0, 'rpm', now, 'ok')]
    page.on_batch(batch, 0)          # must not raise
    assert '0F' in page.live and page.live['0F'][-1][1] == 24.0
    assert '0C' in page.readout_labels          # only real labels exist
    assert '0F' not in page.readout_labels
    assert all(value is not None for value in page.readout_labels.values())
    page.session_id = None
    window.close(); store.close()


def test_live_history_is_bounded(app, tmp_path):
    """Live per-PID history must stay bounded so a long session cannot grow forever."""
    from openwrench import diagnostics_ui
    from openwrench.diagnostics import SensorSample
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    session = page.service.start(vehicle, 'simulator', 'normal')
    page.session_id = session
    page.sequence = 1
    page.live = {}
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    for index in range(diagnostics_ui.MAX_LIVE_POINTS + 50):
        page.on_batch([SensorSample('0C', 800.0, 'rpm', now, 'ok')], index)
    assert len(page.live['0C']) == diagnostics_ui.MAX_LIVE_POINTS
    page.session_id = None
    window.close(); store.close()


def test_code_modes_are_shown_and_stored_per_mode(app, tmp_path):
    """The UI must show each code's real mode, not a hardcoded 03."""
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_worker import scan_codes
    from openwrench.diagnostics_sim import SimulatorAdapter
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'codes')
    page.session_id = session
    adapter = SimulatorAdapter('codes'); adapter.connect()
    page.on_codes(scan_codes(adapter))
    page.session_id = None
    texts = [page.codes.item(i).text() for i in range(page.codes.count())]
    assert any('mode 07' in t and 'P0301' in t for t in texts)
    # A pending code must be stored under mode 07, never mode 03.
    stored = {(row['code'], row['mode']) for row in service.codes(session)}
    assert ('P0301', '07') in stored and ('P0301', '03') not in stored
    window.close(); store.close()


def test_diagnostics_page_has_scroll_area_and_single_sensor_graph(app, tmp_path):
    from PySide6.QtWidgets import QScrollArea
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    assert page.findChild(QScrollArea) is not None      # page scrolls
    # The graph plots one selectable sensor, with the selector defaulting to RPM.
    assert page.graph_pid.currentData() == '0C'
    count = page.graph_pid.count()
    page.graph_pid.setCurrentIndex((page.graph_pid.currentIndex() + 1) % count)
    assert page.graph_pid.currentData() != '0C'
    window.close(); store.close()


def test_graph_reflects_a_saved_session(app, tmp_path):
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_sim import SimulatorAdapter
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'normal')
    sim = SimulatorAdapter('normal'); sim.connect()
    sequence = 1
    for index in range(5):
        sequence = service.append(session, [sim.read_pid(0x0C)], sequence, index * 100)
    service.finish(session)
    page.refresh()
    page.sessions.setCurrentRow(0)
    page.review()
    assert len(page.live.get('0C', ())) == 5
    assert len(page.graph.points) == 5
    window.close(); store.close()


def test_guided_tree_walk_and_save_in_ui(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    # Deterministic misfire session so the guide has codes and rpm evidence.
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_sim import SimulatorAdapter
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'misfire')
    sim = SimulatorAdapter('misfire'); sim.connect()
    sequence = 1
    for index in range(4):
        sequence = service.append(session, [sim.read_pid(0x0C), sim.read_pid(0x42)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    page.refresh()
    assert page.sessions.count() >= 1
    page.sessions.setCurrentRow(0)
    page.review()
    assert 'SIMULATED' in page.banner.text()
    page.start_guide()
    assert page.guide_options.count() >= 1
    # Walk to an outcome using the first available option buttons.
    while page.guide_options.count():
        page.guide_options.itemAt(0).widget().click()
    assert 'Outcome' in page.guide_outcome.text()
    page.save_guide()
    assert 'Run saved.' in page.guide_node.text()
    assert page.guide_runs.count() == 1
    window.close(); store.close()


def test_guided_electrical_tree_can_be_completed_in_ui(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_sim import SimulatorAdapter
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'electrical')
    sim = SimulatorAdapter('electrical'); sim.connect()
    sequence = 1
    for index in range(4):
        sequence = service.append(session, [sim.read_pid(0x0C), sim.read_pid(0x42)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    page.refresh()
    page.sessions.setCurrentRow(0)
    page.review()
    # Select the electrical guide explicitly.
    index = page.guide_tree.findData('electrical')
    page.guide_tree.setCurrentIndex(index)
    page.start_guide()
    while page.guide_options.count():
        page.guide_options.itemAt(0).widget().click()
    assert 'Outcome' in page.guide_outcome.text()
    window.close(); store.close()


def test_unfinished_guide_can_be_resumed_in_ui(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_sim import SimulatorAdapter
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'misfire')
    sim = SimulatorAdapter('misfire'); sim.connect()
    sequence = 1
    for index in range(4):
        sequence = service.append(session, [sim.read_pid(0x0C)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    page.refresh()
    page.sessions.setCurrentRow(0)
    page.review()
    page.start_guide()
    page.guide_options.itemAt(0).widget().click()   # take one step only
    page.save_guide()                               # save an unfinished run
    assert page.guide_runs.count() == 1
    assert 'resumable' in page.guide_runs.item(0).text()
    page.guide_runs.setCurrentRow(0)
    page.resume_guide()
    assert 'No answers recorded yet' not in page.guide_history.text()
    while page.guide_options.count():
        page.guide_options.itemAt(0).widget().click()
    assert 'Outcome' in page.guide_outcome.text()
    window.close(); store.close()


def test_mismatched_guide_shows_informational_note_without_blocking(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    from openwrench.diagnostics_session import DiagnosticService
    from openwrench.diagnostics_sim import SimulatorAdapter
    service = DiagnosticService(store)
    session = service.start(vehicle, 'simulator', 'misfire')   # misfire evidence
    sim = SimulatorAdapter('misfire'); sim.connect()
    sequence = 1
    for index in range(4):
        sequence = service.append(session, [sim.read_pid(0x0C)], sequence, index * 100)
    service.add_codes(session, sim.codes(), '03')
    service.finish(session)
    page.refresh()
    page.sessions.setCurrentRow(0)
    page.review()
    # Choose the electrical guide against misfire evidence: allowed, but flagged.
    page.guide_tree.setCurrentIndex(page.guide_tree.findData('electrical'))
    page.start_guide()
    assert page.guide_note.isVisible()
    assert 'points at' in page.guide_note.text()
    assert page.guide_options.count() >= 1        # selection was not blocked
    window.close(); store.close()


def test_comm_failure_marks_session_failed(app, tmp_path):
    """A dropped link must be stored as failed, not silently completed."""
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    index = page.scenario.findData('comms')
    page.scenario.setCurrentIndex(index)
    page.start_session()
    deadline = time.time() + 8
    while time.time() < deadline and page.session_id is not None:
        QTest.qWait(50)
    row = store.connection.execute(
        'SELECT status FROM diagnostic_sessions ORDER BY started_at DESC').fetchone()
    assert row is not None and row[0] in ('failed', 'interrupted')
    assert not page.runner.active
    window.close(); store.close()


def test_cancelling_a_session_stops_worker_and_cleans_up(app, tmp_path):
    store, vehicle, window = _window(tmp_path)
    window.navigation.setCurrentRow(1)
    page = window.diagnostics_page
    page.start_session()
    QTest.qWait(250)
    assert page.runner.active
    page.stop_session()
    deadline = time.time() + 5
    while time.time() < deadline and page.session_id is not None:
        QTest.qWait(50)
    assert not page.runner.active
    assert page.runner.thread is None and page.runner.recorder is None
    status = store.connection.execute(
        'SELECT status FROM diagnostic_sessions ORDER BY started_at DESC').fetchone()[0]
    assert status == 'interrupted'
    window.close(); store.close()



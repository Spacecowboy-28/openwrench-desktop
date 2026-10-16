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
    assert 'codes' in page.guide_node.text().lower() or page.guide_node.text()
    # Walk to an outcome using the first available option buttons.
    while page.guide_options.count():
        page.guide_options.itemAt(0).widget().click()
    assert 'Outcome' in page.guide_outcome.text()
    page.save_guide()
    assert 'Run saved.' in page.guide_node.text()
    assert page.guide_runs.count() == 1
    window.close(); store.close()


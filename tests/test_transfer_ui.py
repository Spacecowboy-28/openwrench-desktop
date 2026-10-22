from contextlib import closing
import json
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from openwrench.garage import Garage
from openwrench.storage import Store
from openwrench.ui import MainWindow


def wait_for_task(app,window,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        task=getattr(window,'storage_task',None)
        if task is not None and task.done:return
        QTest.qWait(10)
    assert getattr(window,'storage_task',None) and window.storage_task.done,'Timed out waiting for storage worker'


def add(store,name):
    return Garage(store).save_vehicle(dict(nickname=name,year=2001,make='Toyota',model='Tundra'))


def test_settings_exports_and_restore_refresh_same_window(app,tmp_path,monkeypatch):
    with closing(Store(tmp_path/'active.sqlite3')) as store:
        add(store,'Current')
        window=MainWindow(store)
        window.show()
        window.navigation.setCurrentRow(1)
        assert window.garage.summary.text().startswith('1 vehicle ·')
        target=tmp_path/'export.json'
        monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:(str(target),''))
        QTest.mouseClick(window.json_button,Qt.MouseButton.LeftButton)
        assert json.loads(target.read_text())['vehicles'][0]['nickname'] == 'Current'
        source=tmp_path/'source.sqlite3'
        with closing(Store(source)) as other:
            add(other,'Restored')
            other.set_theme('light')
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(source),''))
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
        QTest.mouseClick(window.restore_button,Qt.MouseButton.LeftButton)
        wait_for_task(app,window)
        assert window.garage.table.item(0,0).text() == 'Restored'
        assert window.theme.currentText() == 'light'
        window.theme.setCurrentText('dark')
        assert store.theme == 'dark'
        window.check_database()
        assert window.result.text() == 'Database check passed.'
        add(store,'Second')
        window.garage.refresh()
        assert window.garage.summary.text().startswith('2 vehicles ·')
        window.close()


def test_restore_cancel_and_rejected_input_preserve_ui(app,tmp_path,monkeypatch):
    with closing(Store(tmp_path/'active.sqlite3')) as store:
        identifier=add(store,'Current')
        window=MainWindow(store)
        source=tmp_path/'broken.sqlite3'
        source.write_bytes(b'bad')
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(source),''))
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No)
        window.choose_restore()
        assert Garage(store).vehicle(identifier)['nickname'] == 'Current'
        errors=[]
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(QMessageBox,'critical',lambda *a:errors.append(a))
        window.choose_restore()
        wait_for_task(app,window)
        assert errors and window.garage.table.item(0,0).text() == 'Current'
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:('',''))
        window.choose_restore()
        monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:('',''))
        window.choose_export('csv')
        assert len(Garage(store).vehicles()) == 1
        window.close()


def test_schema5_restore_refreshes_diagnostics_and_hardware_off_thread(app, tmp_path, monkeypatch):
    from openwrench.diagnostics_session import DiagnosticService
    from test_transfers import legacy_library_backup
    source, expected = legacy_library_backup(tmp_path, 5)
    with closing(Store(tmp_path / 'active.sqlite3')) as store:
        vehicle = add(store, 'Replaced vehicle')
        store.set_hardware_enabled(True)
        session = DiagnosticService(store).start(vehicle, 'simulator', 'normal')
        DiagnosticService(store).finish(session)
        window = MainWindow(store)
        page = window.diagnostics_page
        page.sessions.setCurrentRow(0)
        page.review()
        page.start_guide()
        assert page.last_session == session and page.run
        assert window.hardware.isChecked()
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(source), ''))
        monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
        errors = []
        monkeypatch.setattr(QMessageBox, 'critical', lambda *a: errors.append(a))
        window.choose_restore()
        assert not window.navigation.isEnabled()
        assert not window.hardware.isEnabled()
        wait_for_task(app, window)
        assert not errors
        assert window.navigation.isEnabled() and window.hardware.isEnabled()
        assert not window.hardware.isChecked() and not page.hardware.isEnabled()
        assert page.last_session is None and page.run is None and not page.live
        assert page.guide_options.count() == 0 and not page.guide_save.isEnabled()
        assert page.vehicle.currentData() == expected['vehicles'][0]['id']
        assert page.sessions.count() == 1
        assert window.theme.currentText() == 'light'
        page.sessions.setCurrentRow(0)
        page.review()
        assert page.last_session == expected['diagnostic_sessions'][0]['id']
        assert page.codes.count() and page.live
        window.close()


def test_restore_waits_for_running_diagnostics(app, tmp_path, monkeypatch):
    with closing(Store(tmp_path / 'active.sqlite3')) as store:
        add(store, 'Recording')
        window = MainWindow(store)
        page = window.diagnostics_page
        page.start_session()
        messages = []
        monkeypatch.setattr(QMessageBox, 'information', lambda *a: messages.append(a))
        def unexpected_dialog(*args):
            raise AssertionError('Restore must not open a file while recording')
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', unexpected_dialog)
        window.choose_restore()
        assert messages and not hasattr(window, 'storage_task')
        assert page.runner.active
        window.close()
        app.processEvents()

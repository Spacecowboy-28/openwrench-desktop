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

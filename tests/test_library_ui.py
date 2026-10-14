from contextlib import closing
import json
import time
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from openwrench.garage import Garage
from openwrench.library_tasks import DocumentTask
from openwrench.library_ui import DocumentDialog,PdfViewer,ScheduleDialog
from openwrench.storage import Store
from openwrench.ui import MainWindow
from openwrench.recalls import parse_recalls,RecallClient
from test_library import synthetic_pdf,details
import pytest


def wait_for(app,predicate,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        QTest.qWait(10)
    assert predicate(),'Timed out waiting for document worker'


def test_native_background_import_viewer_search_themes(app,tmp_path):
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        vehicle=Garage(store).save_vehicle(dict(year=2020,make='Honda',model='Civic'))
        window=MainWindow(store);window.show();window.open_vehicle_library()
        page=window.library_page
        assert page.vehicle.currentData()==vehicle
        source=synthetic_pdf(tmp_path/'input.pdf')
        page.run_task('import',dict(source=str(source),metadata=details(),vehicles=[vehicle]))
        assert page.busy and page.cancel.isVisible()
        wait_for(app,lambda:not page.busy)
        assert page.documents.count()==1,page.status.text()
        page.query.setText('brake');page.reload()
        assert 'page 1' in page.documents.item(0).text()
        identifier=page.selected_document()[0]
        viewer=PdfViewer(page.library,identifier,parent=window);viewer.show()
        wait_for(app,lambda:viewer.task.done)
        assert len(viewer.scene.items())==1,viewer.status.text()
        viewer.zoom.setCurrentText('200%');wait_for(app,lambda:viewer.task.done)
        assert viewer.scene.itemsBoundingRect().width()==600
        viewer.find.setText('brake');viewer.search();assert viewer.hits.count()==1
        viewer.bookmark();page.reload_bookmarks();assert page.bookmarks.count()==1
        window.theme.setCurrentText('light');assert store.theme=='light'
        window.theme.setCurrentText('dark');assert store.theme=='dark'
        viewer.close();window.close()


def test_worker_cancellation_and_bad_pdf_report(app,tmp_path):
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        source=tmp_path/'bad.pdf';source.write_bytes(b'bad')
        task=DocumentTask(store,'import',dict(source=str(source),metadata=details(),vehicles=[]))
        messages=[];task.finished.connect(lambda result,message:messages.append(message))
        task.start();wait_for(app,lambda:task.done)
        assert messages and 'PDF' in messages[0]
        task2=DocumentTask(store,'import',dict(source=str(source),metadata=details(),vehicles=[]))
        task2.start();task2.cancel()
        assert task2.done and store.integrity()=='ok'


def test_native_metadata_schedule_and_delete_cancel(app,tmp_path,monkeypatch):
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        vehicle=Garage(store).save_vehicle(dict(year=2001,make='Toyota',model='Tundra'))
        window=MainWindow(store);page=window.library_page
        identifier=page.library.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
        page.reload()
        dialog=DocumentDialog(page.library,document=page.library.document(identifier))
        dialog.fields['title'].setText('Edited');dialog.accept()
        assert dialog.payload[0]['title']=='Edited'
        schedule=ScheduleDialog(page.library,vehicle)
        schedule.fields['title'].setText('My inspection');schedule.fields['months_interval'].setText('6')
        schedule.fields['baseline_date'].setText('2026-01-01');schedule.accept()
        page.reload_schedules();assert page.schedules.count()==1
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No)
        page.delete_document();assert page.library.document(identifier)
        monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
        page.delete_document();assert not page.library.documents()
        assert Garage(store).vehicle(vehicle)
        window.close()


def test_recalls_validation_and_timeout(app):
    content=json.dumps(dict(results=[dict(NHTSACampaignNumber='26V000000',ReportReceivedDate='01/01/2026',Component='Test',Summary='Synthetic only')])).encode()
    assert parse_recalls(content)[0]['campaign']=='26V000000'
    for malformed in [b'invalid',b'{}',b'{"results":[{}]}',b'x'*2000001]:
        with pytest.raises(ValueError):parse_recalls(malformed)
    client=RecallClient();received=[];client.completed.connect(lambda rows,message:received.append(message))
    client.timeout();assert 'timed out' in received[0]

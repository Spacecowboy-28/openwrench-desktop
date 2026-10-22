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


@pytest.mark.parametrize('status,network_error',[(200,0),(503,0),(302,0),(0,1)])
def test_recall_network_results_and_failures(app,status,network_error):
    from PySide6.QtCore import Signal
    from PySide6.QtNetwork import QNetworkReply
    from test_vpic import FakeReply,FakeManager
    class Reply(FakeReply):
        readyRead=Signal()
        def readAll(self):
            value,self.body=self.body,b''
            return value
    body=json.dumps(dict(results=[dict(NHTSACampaignNumber='26V000000',ReportReceivedDate='',Component='Test',Summary='Synthetic')])).encode()
    reply=Reply(body,status,QNetworkReply.NetworkError.HostNotFoundError if network_error else QNetworkReply.NetworkError.NoError)
    client=RecallClient();client.manager=FakeManager(reply)
    received=[];client.completed.connect(lambda rows,message:received.append((rows,message)))
    client.fetch(dict(year=2006,make='Ford',model='F-150',vin='PRIVATE_NOT_SENT'))
    assert 'PRIVATE' not in client.manager.request.url().toString()
    reply.finished.emit()
    assert received and client.reply is None
    assert bool(received[0][0])==(status==200 and not network_error)


def test_recall_cancel_ignores_stale_reply(app):
    from PySide6.QtCore import Signal
    from test_vpic import FakeReply,FakeManager
    class Reply(FakeReply):readyRead=Signal()
    reply=Reply(b'{"results":[]}')
    client=RecallClient();client.manager=FakeManager(reply)
    received=[];client.completed.connect(lambda *a:received.append(a))
    client.fetch(dict(year=2001,make='Toyota',model='Tundra'))
    client.cancel();reply.finished.emit()
    assert reply.aborted and not received


def test_folder_import_action_imports_and_reports(app,tmp_path,monkeypatch):
    """The new action must import a whole nested folder and explain limitations."""
    from PySide6.QtWidgets import QFileDialog
    from openwrench.library_ui import RepairLibraryPage
    from test_html_library import synthetic_folder
    class _Field:
        def setText(self,*a):pass
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        vehicle=Garage(store).save_vehicle(dict(year=2020,make='Honda',model='Civic'))
        window=MainWindow(store);window.show();window.open_vehicle_library()
        page=window.library_page
        assert 'Import HTML Folder' in [b.text() for b in page.document_buttons]
        folder=synthetic_folder(tmp_path/'manual')
        (folder/'assets'/'nav.js').write_bytes(b'menu()')
        monkeypatch.setattr(QFileDialog,'getExistingDirectory',staticmethod(lambda *a,**k:str(folder)))
        class FakeDialog:
            def __init__(self,*a,**k):self.fields={'title':_Field()}
            def exec(self):return True
            @property
            def payload(self):return (dict(details(),applicability='{}'),[vehicle])
        monkeypatch.setattr('openwrench.library_ui.DocumentDialog',FakeDialog)
        shown=[]
        monkeypatch.setattr(RepairLibraryPage,'show_notice',lambda self,notice:shown.append(notice))
        page.import_folder()
        wait_for(app,lambda:not page.busy)
        assert page.documents.count()==1,page.status.text()
        assert shown and shown[0]['entry']=='index.html'
        assert 'assets/nav.js' in shown[0]['inactive']
        assert any('JavaScript' in note for note in shown[0]['notes'])
        identifier=page.selected_document()[0]
        assert page.library.document(identifier)['format']=='html'
        window.close()


def test_folder_import_cancel_leaves_no_partial_document(app,tmp_path):
    from test_html_library import synthetic_folder
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        vehicle=Garage(store).save_vehicle(dict(year=2020,make='Honda',model='Civic'))
        window=MainWindow(store);window.show();window.open_vehicle_library()
        page=window.library_page
        folder=synthetic_folder(tmp_path/'manual')
        page.run_task('import',dict(source=str(folder),metadata=details(),vehicles=[vehicle]))
        page.cancel.click()
        wait_for(app,lambda:not page.busy)
        assert page.documents.count()==0,page.status.text()
        assert (folder/'index.html').is_file()
        window.close()


def test_backup_and_restore_run_in_the_worker_not_the_gui_thread(app,tmp_path,monkeypatch):
    """Backup and restore must run in the worker process so the GUI thread never
    blocks, and the window must re-read state once the worker finishes."""
    from openwrench.library_tasks import DocumentTask
    monkeypatch.setattr(QMessageBox,'critical',staticmethod(lambda *a,**k:None))
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        Garage(store).save_vehicle(dict(year=2020,make='Honda',model='Civic'))
        store.set_theme('light')
        window=MainWindow(store);window.show()
        destination=tmp_path/'backup.sqlite3'
        operations=[]
        original_start=DocumentTask.start
        def recording_start(self):
            operations.append(self.job['operation']);original_start(self)
        monkeypatch.setattr(DocumentTask,'start',recording_start)
        window._run_storage_task('backup',dict(destination=str(destination)),'Backup saved','Backup failed')
        assert operations==['backup']
        assert not window.backup_button.isEnabled()
        wait_for(app,lambda:window.storage_task.done)
        assert destination.is_file() and 'Backup saved' in window.result.text()
        assert window.backup_button.isEnabled()
        # A restore must bring back the earlier state and refresh the UI.
        Garage(store).save_vehicle(dict(year=2011,make='Ford',model='F-150'))
        store.set_theme('dark')
        window._run_storage_task('restore',dict(source=str(destination)),None,'Restore failed')
        wait_for(app,lambda:window.storage_task.done)
        assert len(Garage(store).vehicles())==1
        assert store.theme=='light' and window.theme.currentText()=='light'
        assert 'restored' in window.result.text().lower()
        window.close()


def test_backup_failure_is_reported_and_buttons_recover(app,tmp_path,monkeypatch):
    monkeypatch.setattr(QMessageBox,'critical',staticmethod(lambda *a,**k:None))
    with closing(Store(tmp_path/'ui.sqlite3')) as store:
        window=MainWindow(store);window.show()
        existing=tmp_path/'exists.sqlite3';existing.write_bytes(b'x')
        window._run_storage_task('backup',dict(destination=str(existing)),'Backup saved','Backup failed')
        wait_for(app,lambda:window.storage_task.done)
        assert window.backup_button.isEnabled() and window.restore_button.isEnabled()
        assert 'Backup failed' in window.result.text()
        assert existing.read_bytes()==b'x'
        window.close()


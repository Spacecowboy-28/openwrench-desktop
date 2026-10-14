from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from openwrench.garage import Garage
from openwrench.garage_ui import EntryDialog, GaragePage, VehicleDialog
from openwrench.storage import Store


def click_save(dialog):
    dialog.show()
    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Save),Qt.MouseButton.LeftButton)


def test_native_forms_create_edit_history_and_delete(app,tmp_path,monkeypatch):
    store=Store(tmp_path/'app.sqlite3')
    garage=Garage(store)
    form=VehicleDialog(garage)
    form.profile.setCurrentIndex(1)
    click_save(form)
    assert form.result() == QDialog.DialogCode.Accepted
    identifier=form.vehicle_id
    assert garage.vehicle(identifier)['engine'] is None
    edit=VehicleDialog(garage,identifier)
    edit.fields['nickname'].setText('Daily truck')
    click_save(edit)
    assert garage.vehicle(identifier)['nickname'] == 'Daily truck'
    mileage=EntryDialog(garage,identifier)
    mileage.odometer.setText('123456')
    click_save(mileage)
    assert mileage.result() == QDialog.DialogCode.Accepted
    service=EntryDialog(garage,identifier,'service')
    service.title.setText('Oil and filter')
    service.cost.setText('54.99')
    service.odometer.setText('123460')
    click_save(service)
    page=GaragePage(store)
    page.show()
    app.processEvents()
    assert page.table.rowCount() == 1
    assert page.history.rowCount() == 2
    assert '123,460' in page.table.item(0,2).text()
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.StandardButton.No)
    page.delete_vehicle()
    assert len(garage.vehicles()) == 1
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.StandardButton.Yes)
    page.delete_vehicle()
    assert not garage.vehicles() and page.table.rowCount() == 0
    for widget in (form,edit,mileage,service,page): widget.close()
    store.close()


def test_invalid_form_stays_open_and_cancel_does_not_save(app,tmp_path):
    store=Store(tmp_path/'app.sqlite3')
    garage=Garage(store)
    form=VehicleDialog(garage)
    click_save(form)
    assert form.isVisible() and form.error.text()
    form.profile.setCurrentIndex(2)
    form.reject()
    assert not garage.vehicles()
    store.close()


def test_decode_preview_applies_only_blanks_and_stale_vin_cancels(app,tmp_path):
    store=Store(tmp_path/'app.sqlite3')
    form=VehicleDialog(Garage(store))
    form.fields['make'].setText('Manual make')
    form.decoded(dict(fields=dict(year='2020',make='HONDA',model='Civic',engine='',trim=''),cached=False,fetched_at='2026-10-13',valid=True,message='OK'))
    form.apply_decode()
    assert form.fields['make'].text() == 'Manual make'
    assert form.fields['model'].text() == 'Civic'
    assert form.fields['engine'].text() == ''
    form.fields['vin'].setText('TEST0000000000001')
    assert not form.apply.isEnabled()
    form.reject()
    store.close()


def test_switching_presets_and_cancelling_preserves_manual_input(app,tmp_path):
    store=Store(tmp_path/'app.sqlite3')
    form=VehicleDialog(Garage(store))
    form.profile.setCurrentIndex(3)
    form.fields['nickname'].setText('My vehicle')
    form.profile.setCurrentIndex(2)
    assert form.fields['year'].text() == '2020'
    assert form.fields['make'].text() == 'Honda'
    assert form.fields['engine'].text() == ''
    assert form.fields['trim'].text() == ''
    assert form.fields['nickname'].text() == 'My vehicle'
    form.reject()
    store.close()

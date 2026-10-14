"""Vehicle forms and history in native Qt widgets."""

import sqlite3

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from openwrench.garage import Garage
from openwrench.vpic import VinLookup

PROFILES = [
    (2001, 'Toyota', 'Tundra', '', ''),
    (2020, 'Honda', 'Civic', '', ''),
    (2015, 'Lexus', 'GS 350', '3.5L V6', 'F Sport'),
    (2006, 'Ford', 'F-150', '4.6L V8', ''),
]


def plain_label(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class VehicleDialog(QDialog):
    def __init__(self, garage, vehicle_id=None, parent=None):
        super().__init__(parent)
        self.garage, self.vehicle_id = garage, vehicle_id
        self.preset_values = {}
        self.setWindowTitle('Edit vehicle' if vehicle_id else 'Add vehicle')
        self.setMinimumWidth(570)
        layout = QVBoxLayout(self)
        self.profile = QComboBox()
        self.profile.addItem('Manual entry')
        for year, make, model, *_ in PROFILES:
            self.profile.addItem(f'{year} {make} {model}')
        if not vehicle_id:
            layout.addWidget(plain_label('Optional starting profile. Confirm all details before saving.'))
            layout.addWidget(self.profile)
        form = QFormLayout()
        self.fields = {}
        for key, title in [('nickname', 'Garage name'), ('vin', 'VIN (optional)'), ('year', 'Year *'), ('make', 'Make *'), ('model', 'Model *'), ('engine', 'Engine (unknown = blank)'), ('trim', 'Trim (unknown = blank)')]:
            edit = QLineEdit()
            edit.setAccessibleName(title)
            edit.setMaxLength(160 if key in ('engine','trim','make','model') else 80 if key == 'nickname' else 17 if key == 'vin' else 4)
            form.addRow(title, edit)
            self.fields[key] = edit
        self.fields['nickname'].setPlaceholderText('Defaults to year, make and model')
        self.unit = QComboBox()
        self.unit.addItems(['mi', 'km'])
        form.addRow('Distance units', self.unit)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)
        form.addRow('Notes', self.notes)
        layout.addLayout(form)
        layout.addWidget(plain_label('VIN lookup sends your VIN and entered year to NHTSA. Manual entry works offline.'))
        buttons = QHBoxLayout()
        self.decode = QPushButton('Decode VIN with NHTSA')
        self.apply = QPushButton('Apply returned fields to blanks')
        self.apply.setEnabled(False)
        buttons.addWidget(self.decode)
        buttons.addWidget(self.apply)
        layout.addLayout(buttons)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(100)
        layout.addWidget(self.preview)
        self.error = plain_label('')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.lookup = VinLookup(garage.store, self)
        self.lookup.completed.connect(self.decoded)
        self.lookup.failed.connect(self.decode_failed)
        self.decode.clicked.connect(self.start_decode)
        self.apply.clicked.connect(self.apply_decode)
        self.profile.currentIndexChanged.connect(self.use_profile)
        self.fields['vin'].textChanged.connect(self.invalidate_decode)
        self.fields['year'].textChanged.connect(self.invalidate_decode)
        self.finished.connect(lambda _: self.lookup.cancel())
        if vehicle_id:
            data = garage.vehicle(vehicle_id)
            for key, widget in self.fields.items():
                widget.setText(str(data.get(key) or ''))
            self.notes.setPlainText(data['notes'])
            self.unit.setCurrentText(data['unit'])

    def use_profile(self, index):
        if index == 0:
            return
        # Replace prior preset values, but preserve independently typed input.
        for key, value in zip(('year','make','model','engine','trim'), PROFILES[index-1]):
            current = self.fields[key].text().strip()
            if not current or current == self.preset_values.get(key):
                self.fields[key].setText(str(value))
        self.preset_values = dict(zip(('year','make','model','engine','trim'), map(str, PROFILES[index-1])))

    def invalidate_decode(self):
        self.lookup.cancel()
        self.decode.setEnabled(True)
        self.apply.setEnabled(False)
        self.preview.clear()

    def start_decode(self):
        self.apply.setEnabled(False)
        self.decode.setEnabled(False)
        self.preview.setPlainText('Looking up VIN…')
        try:
            self.lookup.start(self.fields['vin'].text(), self.fields['year'].text())
        except (ValueError, sqlite3.Error) as error:
            self.decode_failed(str(error))

    def decode_failed(self, message):
        self.decode.setEnabled(True)
        self.preview.setPlainText(message)

    def decoded(self, result):
        self.decode.setEnabled(True)
        self.decoded_fields = result['fields']
        source = 'Local cache' if result['cached'] else 'NHTSA vPIC'
        lines = [f'{source} · {result["fetched_at"]}', result['message']]
        lines.extend(f'{k}: {v or "Unknown"}' for k, v in result['fields'].items())
        self.preview.setPlainText('\n'.join(lines))
        self.apply.setEnabled(result['valid'])

    def apply_decode(self):
        values = dict(self.decoded_fields)
        for key, value in values.items():
            if value and not self.fields[key].text().strip():
                self.fields[key].setText(value)
        self.apply.setEnabled(False)
        self.preview.setPlainText('Returned values filled empty fields. Review all details before saving. Existing entries stayed unchanged.')

    def save(self):
        data = {key: widget.text() for key, widget in self.fields.items()}
        data.update(unit=self.unit.currentText(), notes=self.notes.toPlainText())
        try:
            self.vehicle_id = self.garage.save_vehicle(data, self.vehicle_id)
        except (ValueError, sqlite3.Error) as error:
            self.error.setText(str(error))
            return
        self.accept()


class EntryDialog(QDialog):
    def __init__(self, garage, vehicle_id, kind='mileage', entry=None, parent=None):
        super().__init__(parent)
        self.garage, self.vehicle_id, self.entry = garage, vehicle_id, entry
        self.kind = entry['kind'] if entry else kind
        self.setWindowTitle(('Edit ' if entry else 'Add ') + self.kind + ' record')
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setMaximumDate(QDate.currentDate())
        self.odometer = QLineEdit()
        self.odometer.setMaxLength(8)
        self.title = QLineEdit()
        self.title.setMaxLength(160)
        self.cost = QLineEdit()
        self.currency = QLineEdit('USD')
        self.currency.setMaxLength(3)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(110)
        form.addRow('Date', self.date)
        unit = garage.vehicle(vehicle_id)['unit']
        form.addRow(f'Odometer ({unit})' + (' *' if self.kind == 'mileage' else ' (optional)'), self.odometer)
        if self.kind == 'service':
            form.addRow('Service description *', self.title)
            form.addRow('Cost (optional)', self.cost)
            form.addRow('Currency', self.currency)
        form.addRow('Notes / parts', self.notes)
        layout.addLayout(form)
        self.error = plain_label('')
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if entry:
            self.date.setDate(QDate.fromString(entry['date'], 'yyyy-MM-dd'))
            self.odometer.setText('' if entry['odometer'] is None else str(entry['odometer']))
            self.title.setText(entry['title'])
            self.cost.setText('' if entry['cost_cents'] is None else f'{entry["cost_cents"]/100:.2f}')
            self.currency.setText(entry['currency'])
            self.notes.setPlainText(entry['notes'])

    def save(self):
        data = dict(kind=self.kind, date=self.date.date().toString('yyyy-MM-dd'), odometer=self.odometer.text(),
                    title=self.title.text(), cost=self.cost.text(), currency=self.currency.text(), notes=self.notes.toPlainText())
        try:
            self.garage.save_entry(self.vehicle_id, data, self.entry['id'] if self.entry else None)
        except (ValueError, sqlite3.Error) as error:
            self.error.setText(str(error))
            return
        self.accept()


class GaragePage(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.garage = Garage(store)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 20)
        title = plain_label('My Garage')
        title.setObjectName('title')
        layout.addWidget(title)
        self.summary = plain_label('')
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.add_button = QPushButton('Add vehicle')
        self.edit_button = QPushButton('Edit vehicle')
        self.delete_button = QPushButton('Delete vehicle')
        for button in (self.add_button, self.edit_button, self.delete_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.table = self.make_table(['Garage name', 'Vehicle', 'Odometer'])
        self.table.setMinimumHeight(110)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(70)
        self.history = self.make_table(['Date', 'Record', 'Odometer', 'Cost'])
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.addWidget(self.history)
        splitter.setSizes([180, 110, 180])
        layout.addWidget(splitter, 1)
        row = QHBoxLayout()
        self.mileage_button = QPushButton('Log mileage')
        self.service_button = QPushButton('Add service')
        self.edit_entry_button = QPushButton('Edit record')
        self.delete_entry_button = QPushButton('Delete record')
        for button in (self.mileage_button, self.service_button, self.edit_entry_button, self.delete_entry_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.add_button.clicked.connect(lambda: self.edit_vehicle(False))
        self.edit_button.clicked.connect(lambda: self.edit_vehicle(True))
        self.delete_button.clicked.connect(self.delete_vehicle)
        self.mileage_button.clicked.connect(lambda: self.edit_entry('mileage'))
        self.service_button.clicked.connect(lambda: self.edit_entry('service'))
        self.edit_entry_button.clicked.connect(lambda: self.edit_entry(edit=True))
        self.delete_entry_button.clicked.connect(self.delete_entry)
        self.table.itemSelectionChanged.connect(self.select_vehicle)
        self.history.itemSelectionChanged.connect(self.select_entry)
        self.table.doubleClicked.connect(lambda _: self.edit_vehicle(True))
        self.refresh()

    @staticmethod
    def make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        return table

    def refresh(self, select_id=None):
        self.records = self.garage.vehicles()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            values = [record['nickname'], f'{record["year"]} {record["make"]} {record["model"]}',
                      'Unknown' if record['mileage'] is None else f'{record["mileage"]:,} {record["unit"]}']
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.summary.setText(f'{len(self.records)} vehicles · Local records' if self.records else 'Your Garage is empty. Add a vehicle to start recording mileage and service.')
        if self.records:
            selected = next((i for i, r in enumerate(self.records) if r['id'] == select_id), 0)
            self.table.selectRow(selected)
        self.select_vehicle()

    def current_id(self):
        row = self.table.currentRow()
        return self.records[row]['id'] if 0 <= row < len(self.records) else None

    def select_vehicle(self):
        identifier = self.current_id()
        for button in (self.edit_button, self.delete_button, self.mileage_button, self.service_button):
            button.setEnabled(identifier is not None)
        self.history.blockSignals(True)
        self.history.clearSelection()
        self.history.setCurrentCell(-1, -1)
        self.history.setRowCount(0)
        self.history_records = []
        self.details.clear()
        if identifier:
            v = self.garage.vehicle(identifier)
            self.details.setPlainText(f'VIN: {v["vin"] or "Not entered"}\nEngine: {v["engine"] or "Unknown"} | Trim: {v["trim"] or "Unknown"}\nNotes: {v["notes"] or "None"}')
            self.history_records = self.garage.entries(identifier)
            self.history.setRowCount(len(self.history_records))
            for i, record in enumerate(self.history_records):
                values = [record['date'], record['title'], '' if record['odometer'] is None else f'{record["odometer"]:,} {v["unit"]}',
                          '' if record['cost_cents'] is None else f'{record["cost_cents"]/100:.2f} {record["currency"]}']
                for j, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(record['notes'])
                    self.history.setItem(i, j, item)
        self.history.blockSignals(False)
        self.select_entry()

    def select_entry(self):
        selected = bool(self.history.selectedItems())
        self.edit_entry_button.setEnabled(selected)
        self.delete_entry_button.setEnabled(selected)

    def edit_vehicle(self, existing):
        identifier = self.current_id() if existing else None
        if existing and not identifier:
            return
        dialog = VehicleDialog(self.garage, identifier, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(dialog.vehicle_id)
        dialog.deleteLater()

    def delete_vehicle(self):
        identifier = self.current_id()
        if identifier and QMessageBox.question(self, 'Delete vehicle?', 'Delete this vehicle and all its mileage and service records?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                self.garage.delete_vehicle(identifier)
                self.refresh()
            except sqlite3.Error:
                QMessageBox.critical(self, 'Delete failed', 'Unable to update local storage.')

    def edit_entry(self, kind='mileage', edit=False):
        identifier = self.current_id()
        row = self.history.currentRow()
        if not identifier or (edit and row < 0):
            return
        dialog = EntryDialog(self.garage, identifier, kind, self.history_records[row] if edit else None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(identifier)
        dialog.deleteLater()

    def delete_entry(self):
        identifier, row = self.current_id(), self.history.currentRow()
        if identifier and row >= 0 and QMessageBox.question(self, 'Delete record?', 'Delete this history record?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                self.garage.delete_entry(identifier, self.history_records[row]['id'])
                self.refresh(identifier)
            except sqlite3.Error:
                QMessageBox.critical(self, 'Delete failed', 'Unable to update local storage.')

"""Native Qt Widgets shell. Only implemented pages appear in navigation."""

from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget, QScrollArea,
)

from openwrench import __version__
from openwrench.garage_ui import GaragePage
from openwrench.diagnostics_ui import DiagnosticsPage
from openwrench.storage import SCHEMA_VERSION, Store
from openwrench.transfers import export_garage
from openwrench.library_ui import RepairLibraryPage


def label(text: str, name: str = '') -> QLabel:
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(True)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setWindowTitle('OpenWrench Desktop')
        self.resize(1060, 720)
        self.setMinimumSize(800, 580)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(225)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(24, 32, 24, 24)
        side.addWidget(label('OPENWRENCH', 'brand'))
        side.addWidget(label('Your local workshop', 'muted'))
        side.addSpacing(32)
        self.navigation = QListWidget()
        self.navigation.setAccessibleName('Main navigation')
        self.navigation.addItems(['My Garage', 'Diagnostics', 'Repair Library', 'Settings'])
        side.addWidget(self.navigation)
        side.addWidget(label('LOCAL DATA\nNo account required', 'muted'))
        side.addWidget(label(f'Garage build {__version__}', 'muted'))
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self.garage_page())
        self.diagnostics_page = DiagnosticsPage(self.store, self)
        self.pages.addWidget(self.diagnostics_page)
        self.library_page = RepairLibraryPage(self.store, self)
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.settings_page())
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(lambda index: self.diagnostics_page.refresh() if index == 1 else None)
        self.navigation.currentRowChanged.connect(lambda index: self.library_page.refresh() if index == 2 else None)
        self.navigation.setCurrentRow(0)
        self.apply_theme(store.theme)
        self.statusBar().showMessage('Local database ready  |  No adapter connected')

    def page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 34, 38, 28)
        layout.setSpacing(18)
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle, 'muted'))
        return page, layout

    def garage_page(self) -> QWidget:
        self.garage = GaragePage(self.store, self)
        repair_button = QPushButton('Open Repair Library')
        repair_button.clicked.connect(self.open_vehicle_library)
        self.garage.layout().addWidget(repair_button)
        return self.garage

    def open_vehicle_library(self):
        self.navigation.setCurrentRow(2)
        self.library_page.refresh(self.garage.current_id())

    def closeEvent(self, event):
        self.diagnostics_page.stop()
        self.library_page.stop()
        super().closeEvent(event)

    def settings_page(self) -> QWidget:
        page, layout = self.page('Settings', 'Control appearance and inspect your local workspace.')
        layout.addWidget(label('Appearance', 'heading'))
        self.theme = QComboBox()
        self.theme.setAccessibleName('Color theme')
        self.theme.addItems(['dark', 'light'])
        self.theme.setCurrentText(self.store.theme)
        self.theme.currentTextChanged.connect(self.change_theme)
        layout.addWidget(self.theme)
        layout.addWidget(label('Diagnostics hardware', 'heading'))
        self.hardware = QCheckBox('Enable experimental USB OBD-II adapter access')
        self.hardware.setChecked(self.store.hardware_enabled)
        self.hardware.toggled.connect(self.toggle_hardware)
        layout.addWidget(self.hardware)
        layout.addWidget(label('Off by default. Read-only requests only (no DTC clearing, actuation or programming). '
                               'Real hardware compatibility is unverified and needs physical testing. The deterministic '
                               'simulator needs no hardware.', 'muted'))
        layout.addWidget(label('Local data', 'heading'))
        path = label(str(self.store.path), 'muted')
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path)
        layout.addWidget(label(f'SQLite schema {SCHEMA_VERSION}. Backups include Garage records, imported PDF bytes, Repair Library metadata and settings.'))
        self.backup_button = QPushButton('Save database backup…')
        self.backup_button.clicked.connect(self.choose_backup)
        self.restore_button = QPushButton('Restore database…')
        self.restore_button.clicked.connect(self.choose_restore)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self.backup_button)
        backup_row.addWidget(self.restore_button)
        layout.addLayout(backup_row)
        export_row = QHBoxLayout()
        self.json_button = QPushButton('Export Garage JSON…')
        self.csv_button = QPushButton('Export Garage CSV ZIP…')
        self.json_button.clicked.connect(lambda: self.choose_export('json'))
        self.csv_button.clicked.connect(lambda: self.choose_export('csv'))
        export_row.addWidget(self.json_button)
        export_row.addWidget(self.csv_button)
        layout.addLayout(export_row)
        self.check_button = QPushButton('Check database')
        self.check_button.clicked.connect(self.check_database)
        layout.addWidget(self.check_button)
        self.result = label('', 'muted')
        self.result.setAccessibleName('Storage action result')
        layout.addWidget(self.result)
        layout.addStretch()
        layout.addWidget(label(f'OpenWrench {__version__} · MIT project license\nQt for Python uses separate LGPLv3 terms. See THIRD_PARTY.md.\nVIN lookup contacts NHTSA only on request. No telemetry or adapter connection.', 'muted'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def choose_export(self, kind):
        default, filter_text = ('openwrench-garage.json', 'JSON (*.json)') if kind == 'json' else ('openwrench-garage-csv.zip', 'CSV ZIP (*.zip)')
        filename, _ = QFileDialog.getSaveFileName(self, 'Export Garage', default, filter_text)
        if not filename:
            return
        try:
            export_garage(self.store, Path(filename), kind)
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.critical(self, 'Export failed', str(error))
            return
        self.result.setText(f'Garage export saved: {filename}')

    def choose_restore(self):
        if self.library_page.busy:
            QMessageBox.information(self, 'Document task active', 'Finish or cancel the document task before restoring.')
            return
        self.library_page.stop()
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose an OpenWrench backup', '', 'SQLite database (*.sqlite3 *.db);;All files (*)')
        if not filename:
            return
        answer = QMessageBox.question(self, 'Replace this workspace?',
            'Restore replaces all current vehicles, history, documents, schedules, bookmarks, settings, and VIN cache with this backup. '
            'Schema-1 backups contain settings only; schema-2 backups contain Garage records without a Repair Library. OpenWrench validates the file and saves a safety backup before making changes. Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            safety = self.store.restore(Path(filename))
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.critical(self, 'Restore failed', str(error))
            return
        self.garage.refresh()
        self.library_page.refresh()
        self.theme.blockSignals(True)
        self.theme.setCurrentText(self.store.theme)
        self.theme.blockSignals(False)
        self.apply_theme(self.store.theme)
        self.result.setText(f'Database restored. Previous workspace saved to: {safety}')

    def toggle_hardware(self, enabled: bool) -> None:
        try:
            self.store.set_hardware_enabled(enabled)
        except sqlite3.Error:
            self.hardware.blockSignals(True)
            self.hardware.setChecked(self.store.hardware_enabled)
            self.hardware.blockSignals(False)
            QMessageBox.critical(self, 'Setting unavailable', 'Unable to save the hardware setting.')
            return
        self.diagnostics_page.refresh()

    def change_theme(self, theme: str) -> None:
        try:
            self.store.set_theme(theme)
        except sqlite3.Error:
            self.theme.blockSignals(True)
            self.theme.setCurrentText(self.store.theme)
            self.theme.blockSignals(False)
            QMessageBox.critical(self, 'Setting unavailable', 'Unable to save appearance. Check available disk space and file permissions.')
            return
        self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        dark = theme == 'dark'
        bg, panel, fg, muted, edge = ('#101820', '#1b2733', '#edf4f7', '#acbcc9', '#334859') if dark else ('#f4f6f8', '#ffffff', '#142a3b', '#516677', '#cdd7df')
        QApplication.instance().setStyleSheet(f'''
            QWidget {{ background: {bg}; color: {fg}; font-family: "Segoe UI", sans-serif; font-size: 14px; }}
            QFrame#sidebar, QFrame#sidebar QLabel {{ background: {panel}; }}
            QLabel#brand {{ font-size: 20px; font-weight: 700; color: #17a89b; }}
            QLabel#title {{ font-size: 30px; font-weight: 700; }}
            QLabel#heading {{ font-size: 18px; font-weight: 600; }}
            QLabel#muted {{ color: {muted}; }}
            QFrame#card {{ border: 1px solid {edge}; border-radius: 10px; }}
            QListWidget {{ border: 0; background: {panel}; }}
            QListWidget::item {{ padding: 14px 10px; border-radius: 5px; }}
            QListWidget::item:selected {{ background: #12695f; color: white; }}
            QPushButton, QComboBox {{ padding: 11px; border: 1px solid {edge}; border-radius: 5px; background: {panel}; }}
            QPushButton:hover {{ border-color: #17a89b; }}
            QPushButton:focus, QComboBox:focus {{ border: 2px solid #17a89b; }}
            QStatusBar {{ color: {muted}; border-top: 1px solid {edge}; }}
        ''')

    def choose_backup(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, 'Save database backup', 'openwrench-backup.sqlite3', 'SQLite database (*.sqlite3)')
        if not filename:
            return
        try:
            self.store.backup(Path(filename))
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.critical(self, 'Backup failed', str(error))
            return
        self.result.setText(f'Backup saved: {filename}')

    def check_database(self) -> None:
        try:
            result = self.store.integrity()
        except sqlite3.Error:
            result = 'Unable to read the database.'
        self.result.setText('Database check passed.' if result == 'ok' else f'Database check failed: {result}')

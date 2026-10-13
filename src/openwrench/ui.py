"""Native Qt Widgets shell. Only implemented pages appear in navigation."""

from pathlib import Path
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from openwrench import __version__
from openwrench.storage import SCHEMA_VERSION, Store


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
        self.navigation.addItems(['My Garage', 'Settings'])
        side.addWidget(self.navigation)
        side.addWidget(label('OFFLINE\nNo account required', 'muted'))
        side.addWidget(label(f'Foundation build {__version__}', 'muted'))
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self.garage_page())
        self.pages.addWidget(self.settings_page())
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
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
        page, layout = self.page('My Garage', 'A private workspace for your vehicles and repair records.')
        panel = QFrame()
        panel.setObjectName('card')
        body = QVBoxLayout(panel)
        body.setContentsMargins(25, 25, 25, 25)
        body.addWidget(label('Desktop foundation ready', 'heading'))
        body.addWidget(label('This development build establishes local storage, application settings, backups, and desktop packaging.'))
        body.addSpacing(12)
        body.addWidget(label('Vehicle entry arrives in Milestone 2.\nThis build contains no vehicle records or repair specifications.', 'muted'))
        layout.addWidget(panel)
        layout.addWidget(label('Development sequence', 'heading'))
        for title, detail in [
            ('02  Vehicle Garage', 'Vehicle entry, VIN lookup, mileage, and restore'),
            ('03  Repair Library + Maintenance', 'Source-linked information and imported documents'),
            ('04  Diagnostics', 'Simulator first, then read-only USB communication'),
            ('05  Guided Repairs', 'Evidence-based misfire and electrical workflows'),
        ]:
            layout.addWidget(label(f'{title}\n{detail}', 'muted'))
        layout.addStretch()
        return page

    def settings_page(self) -> QWidget:
        page, layout = self.page('Settings', 'Control appearance and inspect your local workspace.')
        layout.addWidget(label('Appearance', 'heading'))
        self.theme = QComboBox()
        self.theme.setAccessibleName('Color theme')
        self.theme.addItems(['dark', 'light'])
        self.theme.setCurrentText(self.store.theme)
        self.theme.currentTextChanged.connect(self.change_theme)
        layout.addWidget(self.theme)
        layout.addWidget(label('Local data', 'heading'))
        path = label(str(self.store.path), 'muted')
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path)
        layout.addWidget(label(f'SQLite schema {SCHEMA_VERSION}. Backups currently contain application settings.'))
        self.backup_button = QPushButton('Save database backup…')
        self.backup_button.clicked.connect(self.choose_backup)
        layout.addWidget(self.backup_button)
        self.check_button = QPushButton('Check database')
        self.check_button.clicked.connect(self.check_database)
        layout.addWidget(self.check_button)
        self.result = label('', 'muted')
        self.result.setAccessibleName('Storage action result')
        layout.addWidget(self.result)
        layout.addStretch()
        layout.addWidget(label(f'OpenWrench {__version__} · MIT project license\nQt for Python uses separate LGPLv3 terms. See THIRD_PARTY.md.\nNo telemetry, online service, or vehicle connection runs in this build.', 'muted'))
        return page

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

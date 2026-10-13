from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from openwrench.storage import Store
from openwrench.ui import MainWindow


def test_window_navigation_theme_and_restart(app, tmp_path):
    path = tmp_path / 'app.sqlite3'
    store = Store(path)
    window = MainWindow(store)
    window.show()
    app.processEvents()
    assert window.isVisible()
    assert window.pages.count() == 2
    window.navigation.setCurrentRow(1)
    assert window.pages.currentIndex() == 1
    window.theme.setCurrentText('light')
    QTest.mouseClick(window.check_button, Qt.MouseButton.LeftButton)
    assert window.result.text() == 'Database check passed.'
    window.close()
    store.close()
    store = Store(path)
    reopened = MainWindow(store)
    assert reopened.theme.currentText() == 'light'
    reopened.close()
    store.close()


def test_backup_button_creates_openable_database(app, tmp_path, monkeypatch):
    store = Store(tmp_path / 'app.sqlite3')
    window = MainWindow(store)
    window.show()
    window.navigation.setCurrentRow(1)
    target = tmp_path / 'backup.sqlite3'
    monkeypatch.setattr('openwrench.ui.QFileDialog.getSaveFileName', lambda *a: (str(target), ''))
    QTest.mouseClick(window.backup_button, Qt.MouseButton.LeftButton)
    assert target.exists()
    backup = Store(target)
    assert backup.theme == store.theme
    assert 'Backup saved:' in window.result.text()
    backup.close()
    window.close()
    store.close()


def test_cancelled_backup_writes_nothing(app, tmp_path, monkeypatch):
    store = Store(tmp_path / 'app.sqlite3')
    window = MainWindow(store)
    monkeypatch.setattr('openwrench.ui.QFileDialog.getSaveFileName', lambda *a: ('', ''))
    window.choose_backup()
    assert list(tmp_path.iterdir()) == [store.path]
    window.close()
    store.close()


def test_existing_backup_surfaces_error_without_overwrite(app, tmp_path, monkeypatch):
    store = Store(tmp_path / 'app.sqlite3')
    window = MainWindow(store)
    target = tmp_path / 'backup.sqlite3'
    target.write_text('existing backup')
    errors = []
    monkeypatch.setattr('openwrench.ui.QFileDialog.getSaveFileName', lambda *a: (str(target), ''))
    monkeypatch.setattr('openwrench.ui.QMessageBox.critical', lambda *a: errors.append(a))
    window.choose_backup()
    assert errors
    assert target.read_text() == 'existing backup'
    window.close()
    store.close()

"""Application lifecycle and explicit developer smoke-test entry point."""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sqlite3
import sys

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from openwrench import __version__
from openwrench.storage import SCHEMA_VERSION, Store
from openwrench.ui import MainWindow


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == '--pdf-worker':
        from openwrench.pdf_worker import main as worker_main
        return worker_main(arguments[1:])
    parser = argparse.ArgumentParser(description='OpenWrench native desktop application')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--data-dir', type=Path, help='Use an isolated local workspace')
    parser.add_argument('--smoke-test', action='store_true', help='Render, check storage, then exit')
    parser.add_argument('--screenshot', type=Path, help='Save the rendered window during smoke testing')
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName('OpenWrench')
    app.setOrganizationName('OpenWrench')
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    from openwrench.resources import application_icon
    icon = application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    location = args.data_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    store = None
    handler = None
    log = logging.getLogger('openwrench')
    try:
        location.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(location / 'application.log', maxBytes=500_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        store = Store(location / 'openwrench.sqlite3')
        window = MainWindow(store)
        window.show()
        log.info('Application started version=%s schema=%s', __version__, SCHEMA_VERSION)

        if args.smoke_test:
            def verify() -> None:
                try:
                    if not window.isVisible() or store.integrity() != 'ok':
                        raise RuntimeError('Window or storage check failed')
                    if args.screenshot:
                        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                        if not window.grab().save(str(args.screenshot)):
                            raise RuntimeError('Screenshot could not be saved')
                    print(json.dumps({'status': 'ok', 'version': __version__, 'schema': SCHEMA_VERSION, 'visible': window.isVisible(), 'theme': store.theme}))
                    app.exit(0)
                except Exception:
                    log.exception('Smoke test failed')
                    app.exit(1)
            QTimer.singleShot(250, verify)
        return app.exec()
    except (OSError, ValueError, sqlite3.Error) as error:
        log.error('Startup failed: %s', type(error).__name__)
        if args.smoke_test:
            print(f'Startup failed: {error}', file=sys.stderr)
        else:
            QMessageBox.critical(None, 'OpenWrench startup failed', str(error))
        return 1
    finally:
        if store:
            store.close()
        if handler:
            log.removeHandler(handler)
            handler.close()

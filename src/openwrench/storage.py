"""Local persistence, versioned schema migration and coherent backups."""

from contextlib import closing
from pathlib import Path
import os
import sqlite3
import tempfile
from uuid import uuid4

SCHEMA_VERSION = 2


class Store:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("A newer OpenWrench version created this database. Upgrade the app.")
            if version == 0:
                # Refuse unrelated SQLite files, even when they use version zero.
                if self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("This is not an empty OpenWrench database.")
                with self.connection:
                    self.connection.execute("BEGIN IMMEDIATE")
                    self.connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    self.connection.execute("INSERT INTO settings VALUES ('theme', 'dark')")
                    self.connection.execute("PRAGMA user_version=1")
            # Validate shape and values before the UI uses them.
            self.connection.execute("SELECT key, value FROM settings LIMIT 1")
            if self.theme not in ('light', 'dark'):
                raise ValueError("Invalid theme in the local database.")
            if version < 2:
                if version == 1:
                    self.backup(self.path.with_name(f'{self.path.stem}.pre-v2-{uuid4().hex}.sqlite3'))
                self._migrate_garage()
            self.connection.row_factory = sqlite3.Row
        except Exception:
            self.connection.close()
            raise

    def _migrate_garage(self) -> None:
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            self.connection.execute('''CREATE TABLE vehicles (
                id TEXT PRIMARY KEY, nickname TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE, vin TEXT UNIQUE,
                year INTEGER NOT NULL CHECK(year BETWEEN 1886 AND 9999),
                make TEXT NOT NULL, model TEXT NOT NULL,
                engine TEXT, trim TEXT, notes TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL CHECK(unit IN ('mi','km')),
                created_at TEXT NOT NULL)''')
            self.connection.execute('''CREATE TABLE entries (
                id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('mileage','service')),
                date TEXT NOT NULL, odometer INTEGER CHECK(odometer >= 0),
                title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                cost_cents INTEGER CHECK(cost_cents >= 0), currency TEXT NOT NULL,
                CHECK(kind != 'mileage' OR odometer IS NOT NULL))''')
            self.connection.execute('CREATE INDEX entries_vehicle_date ON entries(vehicle_id,date)')
            self.connection.execute('''CREATE TABLE vin_cache (
                vin TEXT NOT NULL, model_year INTEGER NOT NULL,
                payload TEXT NOT NULL, fetched_at TEXT NOT NULL,
                PRIMARY KEY(vin,model_year))''')
            self.connection.execute('PRAGMA user_version=2')

    @property
    def theme(self) -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key='theme'").fetchone()
        if row is None:
            raise ValueError("Missing theme setting.")
        return row[0]

    def set_theme(self, theme: str) -> None:
        if theme not in ('light', 'dark'):
            raise ValueError("Theme must be light or dark.")
        with self.connection:
            self.connection.execute("UPDATE settings SET value=? WHERE key='theme'", (theme,))

    def integrity(self) -> str:
        return self.connection.execute("PRAGMA quick_check").fetchone()[0]

    def backup(self, destination: Path) -> Path:
        destination = Path(destination).resolve()
        if destination == self.path or (destination.exists() and os.path.samefile(destination, self.path)):
            raise ValueError("Choose a backup path outside the active database.")
        if destination.exists():
            raise FileExistsError("Choose a new filename. Existing backups are preserved.")
        # SQLite's API creates a coherent snapshot, including committed journals.
        descriptor, temporary = tempfile.mkstemp(prefix='.openwrench-', dir=destination.parent)
        os.close(descriptor)
        temporary_path = Path(temporary)
        try:
            with closing(sqlite3.connect(temporary_path)) as target:
                self.connection.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != 'ok':
                    raise ValueError("Backup validation failed.")
            # Exclusive creation also protects a destination created during the backup.
            output = destination.open('xb')
            try:
                with output:
                    output.write(temporary_path.read_bytes())
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                # Remove only the partial file this operation created.
                destination.unlink(missing_ok=True)
                raise
        finally:
            temporary_path.unlink(missing_ok=True)
        return destination

    def close(self) -> None:
        self.connection.close()

"""Schema 3. Content bytes make SQLite snapshots self-contained and recoverable."""
LIBRARY_TABLES = ('vehicle_configuration', 'documents', 'document_files', 'document_vehicles',
                  'document_pages', 'bookmarks', 'schedules')
METADATA_TABLES = ('vehicle_configuration', 'documents', 'document_vehicles', 'bookmarks', 'schedules')
CATEGORIES = ('Engine', 'Transmission and drivetrain', 'Electrical systems', 'Brakes',
              'Steering and suspension', 'Cooling', 'Fuel and emissions', 'HVAC',
              'Body and interior', 'Maintenance', 'Diagnostic trouble codes',
              'Technical service bulletins', 'Recalls')


def create_library(db):
    statements = [
        '''CREATE TABLE vehicle_configuration (
            vehicle_id TEXT PRIMARY KEY REFERENCES vehicles(id) ON DELETE CASCADE,
            drivetrain TEXT NOT NULL, transmission TEXT NOT NULL, engine_code TEXT NOT NULL)''',
        '''CREATE TABLE documents (
            id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
            description TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL,
            publisher TEXT NOT NULL, publication_date TEXT NOT NULL, rights TEXT NOT NULL,
            verification TEXT NOT NULL, reviewed_at TEXT NOT NULL, applicability TEXT NOT NULL,
            document_type TEXT NOT NULL, page_count INTEGER NOT NULL CHECK(page_count>0),
            index_status TEXT NOT NULL, created_at TEXT NOT NULL)''',
        '''CREATE TABLE document_files (
            document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
            content BLOB NOT NULL)''',
        '''CREATE TABLE document_vehicles (
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            vehicle_id TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
            PRIMARY KEY(document_id,vehicle_id))''',
        '''CREATE TABLE document_pages (
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page INTEGER NOT NULL CHECK(page>0), text TEXT NOT NULL,
            PRIMARY KEY(document_id,page))''',
        '''CREATE VIRTUAL TABLE library_fts USING fts5(document_id UNINDEXED, page UNINDEXED, text)''',
        '''CREATE TABLE bookmarks (
            id TEXT PRIMARY KEY, vehicle_id TEXT REFERENCES vehicles(id) ON DELETE CASCADE,
            document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
            page INTEGER, title TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL,
            CHECK(document_id IS NOT NULL OR url!=''))''',
        '''CREATE TABLE schedules (
            id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
            title TEXT NOT NULL, distance_interval INTEGER, months_interval INTEGER,
            unit TEXT NOT NULL, origin TEXT NOT NULL, source TEXT NOT NULL, publication TEXT NOT NULL,
            conditions TEXT NOT NULL, specification TEXT NOT NULL, applicability TEXT NOT NULL,
            last_entry_id TEXT REFERENCES entries(id) ON DELETE SET NULL,
            baseline_date TEXT NOT NULL, baseline_odometer INTEGER,
            procedure_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
            reminder INTEGER NOT NULL CHECK(reminder IN (0,1)))''',
        'CREATE INDEX document_vehicles_vehicle ON document_vehicles(vehicle_id)',
        'CREATE INDEX schedules_vehicle ON schedules(vehicle_id)',
    ]
    for statement in statements:
        db.execute(statement)
    db.execute('PRAGMA user_version=3')


def rebuild_fts(db):
    db.execute('DELETE FROM library_fts')
    db.execute('INSERT INTO library_fts SELECT document_id,page,text FROM document_pages')

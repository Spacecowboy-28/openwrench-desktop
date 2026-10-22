"""Schema 5. Diagnostic sessions, bounded samples and read-only code records.

Samples are measurements, not documentation, so they live in their own tables.
Every row is owned by a session, which is owned by a Garage vehicle UUID. Foreign
keys cascade so removing a vehicle removes only its own diagnostic history.
"""

DIAGNOSTIC_TABLES = ('diagnostic_sessions', 'diagnostic_samples', 'diagnostic_codes')


def create_diagnostics(db):
    statements = [
        '''CREATE TABLE diagnostic_sessions (
            id TEXT PRIMARY KEY,
            vehicle_id TEXT NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
            adapter TEXT NOT NULL, scenario TEXT NOT NULL,
            simulated INTEGER NOT NULL CHECK(simulated IN (0,1)),
            status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
            note TEXT NOT NULL DEFAULT '')''',
        '''CREATE TABLE diagnostic_samples (
            session_id TEXT NOT NULL REFERENCES diagnostic_sessions(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK(sequence>0),
            elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms>=0),
            pid TEXT NOT NULL, value REAL, unit TEXT NOT NULL, status TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY(session_id,sequence,pid))''',
        '''CREATE TABLE diagnostic_codes (
            session_id TEXT NOT NULL REFERENCES diagnostic_sessions(id) ON DELETE CASCADE,
            code TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL,
            PRIMARY KEY(session_id,code,mode))''',
        'CREATE INDEX diagnostic_samples_session ON diagnostic_samples(session_id,sequence)',
        'CREATE INDEX diagnostic_sessions_vehicle ON diagnostic_sessions(vehicle_id,started_at)',
    ]
    for statement in statements:
        db.execute(statement)
    db.execute('PRAGMA user_version=5')

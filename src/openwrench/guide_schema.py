"""Schema 6. Guided diagnostic runs recorded against a session.

A guided run stores the tree id and version it used plus the chosen path, so a
diagnosis is reproducible even after a tree is revised. Runs are owned by a
session, which cascades from a Garage vehicle.
"""

GUIDE_TABLES = ('diagnostic_guides',)


def create_guides(db):
    statements = [
        '''CREATE TABLE diagnostic_guides (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES diagnostic_sessions(id) ON DELETE CASCADE,
            tree_id TEXT NOT NULL, tree_version INTEGER NOT NULL CHECK(tree_version>0),
            outcome TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '[]', evidence TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, finished INTEGER NOT NULL CHECK(finished IN (0,1)))''',
        'CREATE INDEX diagnostic_guides_session ON diagnostic_guides(session_id,created_at)',
    ]
    for statement in statements:
        db.execute(statement)
    db.execute('PRAGMA user_version=6')

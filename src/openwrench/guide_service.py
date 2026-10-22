"""Persistence for guided diagnostic runs (Milestone 5).

Stores the tree id/version and the chosen path so a run is reproducible. Nothing
here evaluates a tree; it only records what the user confirmed. A run may be saved
unfinished and later resumed; a run may also reference a historical tree revision
that is still shipped in `diagnostic_trees.TREE_VERSIONS`.
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from openwrench.diagnostic_trees import get_tree
from openwrench.garage import text

MAX_GUIDE_PATH = 128
MAX_GUIDE_JSON = 200_000


def validate_path(tree, path):
    """Replay a stored option path against a tree; raise on any invalid step."""
    if len(path) > MAX_GUIDE_PATH:
        raise ValueError('Guided run path is too long.')
    node_id = tree.root
    for step in path:
        node = tree.node(node_id)
        if node.kind != 'question':
            raise ValueError('Guided run path continues past an outcome.')
        option = next((o for o in node.options if o.id == step.get('option')), None)
        if option is None:
            raise ValueError('Guided run path contains an invalid option.')
        node_id = option.next
    return True


class GuideService:
    def __init__(self, store):
        self.store = store
        self.db = store.connection

    def save(self, run):
        """Persist a run (from diagnostic_guide.start_run/choose) and return its id."""
        if not isinstance(run, dict) or 'tree_id' not in run:
            raise ValueError('No guided run to save.')
        tree = get_tree(run['tree_id'], run.get('tree_version'))
        if run.get('tree_version') != tree.version:
            raise ValueError('The decision tree changed since this run started. Restart the guide.')
        session_id = run['session_id']
        if self.db.execute('SELECT 1 FROM diagnostic_sessions WHERE id=?', (session_id,)).fetchone() is None:
            raise ValueError('Diagnostic session not found.')
        path = json.dumps(run['path'], separators=(',', ':'))
        evidence = json.dumps(run['evidence'], separators=(',', ':'))
        if len(path) > MAX_GUIDE_JSON or len(evidence) > MAX_GUIDE_JSON:
            raise ValueError('Guided run is too large to store.')
        identifier = run.get('id') or str(uuid4())
        validate_path(tree, run['path'])
        with self.db:
            self.db.execute(
                '''INSERT INTO diagnostic_guides
                   (id,session_id,tree_id,tree_version,outcome,severity,path,evidence,created_at,finished)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET outcome=excluded.outcome,severity=excluded.severity,
                   path=excluded.path,evidence=excluded.evidence,finished=excluded.finished''',
                (identifier, session_id, tree.id, tree.version,
                 text(run.get('outcome') or '', 'Outcome', 200),
                 run.get('outcome_severity') or '',
                 path, evidence, datetime.now(timezone.utc).isoformat(), 1 if run['finished'] else 0))
        return identifier

    def get(self, guide_id):
        """Fetch one saved run, or None. Path/evidence are decoded for reuse."""
        row = self.db.execute('SELECT * FROM diagnostic_guides WHERE id=?', (guide_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record['path'] = json.loads(record['path'] or '[]')
        record['evidence'] = json.loads(record['evidence'] or '{}')
        return record

    def unfinished(self, session_id):
        """Saved runs for a session that can be resumed."""
        return [record for record in self.runs(session_id, decoded=True)
                if not record['finished']]

    def runs(self, session_id, decoded=False):
        rows = self.db.execute(
            'SELECT * FROM diagnostic_guides WHERE session_id=? ORDER BY created_at', (session_id,)).fetchall()
        result = [dict(row) for row in rows]
        if decoded:
            for record in result:
                record['path'] = json.loads(record['path'] or '[]')
                record['evidence'] = json.loads(record['evidence'] or '{}')
        return result

    def delete(self, guide_id):
        with self.db:
            self.db.execute('DELETE FROM diagnostic_guides WHERE id=?', (guide_id,))


def validate_guide_records(data):
    """Restore-time validation of guided runs. Mirrors DiagnosticService checks."""
    guides = data.get('diagnostic_guides', [])
    sessions = {row['id'] for row in data.get('diagnostic_sessions', [])}
    seen = set()
    for row in guides:
        try:
            identifier = row['id']
            if str(UUID(identifier)) != identifier or identifier in seen:
                raise ValueError('Invalid or duplicate guided run identifier.')
            seen.add(identifier)
            if row['session_id'] not in sessions:
                raise ValueError('Orphan guided run.')
            tree = get_tree(row['tree_id'], row['tree_version'])
            if row['finished'] not in (0, 1):
                raise ValueError('Invalid guided run finished flag.')
            if row['severity'] not in ('', 'info', 'caution', 'warning'):
                raise ValueError('Invalid guided run severity.')
            text(row['outcome'], 'Outcome', 200)
            path = json.loads(row['path'])
            evidence = json.loads(row['evidence'])
            if not isinstance(path, list) or not isinstance(evidence, dict):
                raise ValueError('Invalid guided run payload.')
            # Replay the stored path against the tree recorded at save time.
            validate_path(tree, path)
            for value in evidence.values():
                if not isinstance(value, bool):
                    raise ValueError('Guided run evidence must be boolean.')
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            raise ValueError('Malformed guided run record.') from error

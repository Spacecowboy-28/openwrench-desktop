"""Milestone 5 guide engine: derive evidence from a session and walk a tree.

The engine is deliberately deterministic and explainable. It never invents a
measurement and never states a fault as certain: it turns already-captured session
evidence into *suggestions* for a branch, and records the tree id/version used so a
diagnosis is reproducible. A user may always pick any branch.
"""

from datetime import datetime, timezone

from openwrench.diagnostic_trees import TREES, get_tree

# Only these boolean evidence keys may be referenced by tree options.
EVIDENCE_KEYS = frozenset({
    'cylinder_codes', 'random_misfire', 'rpm_spread_high', 'rpm_spread_low',
    'voltage_codes', 'voltage_low', 'has_codes',
})

# Thresholds are reasoning thresholds for *suggesting* a branch, not repair specs.
RPM_SPREAD_RATIO = 0.18
VOLTAGE_LOW = 12.4


def evidence_from_session(service, session_id):
    """Return a dict of boolean evidence derived only from stored session data."""
    codes = service.codes(session_id)
    letters = {code['code'][:1].upper() for code in codes}
    numbers = {code['code'].upper() for code in codes}
    evidence = {
        'has_codes': bool(codes),
        'cylinder_codes': any(n[:4] == 'P030' and n[4:5] != '0' for n in numbers),
        'random_misfire': any(n.startswith('P0300') for n in numbers),
        'voltage_codes': 'P056' in {n[:4] for n in numbers} or 'P0A' in {n[:3] for n in numbers},
    }
    rpm = [value for _, value in service.series(session_id, 0x0C)]
    if len(rpm) >= 3:
        average = sum(rpm) / len(rpm)
        spread = (max(rpm) - min(rpm)) / average if average else 0.0
        evidence['rpm_spread_high'] = spread >= RPM_SPREAD_RATIO
        evidence['rpm_spread_low'] = spread < RPM_SPREAD_RATIO
    voltage = [value for _, value in service.series(session_id, 0x42)]
    if voltage:
        measured = min(voltage)
        evidence['voltage_low'] = measured < VOLTAGE_LOW
    return evidence


def suggested_options(node, evidence):
    """Option ids whose declarative rules are satisfied by the evidence."""
    suggested = []
    for option in node.options:
        for rule in option.suggested_when:
            key = rule.get('evidence')
            if key in EVIDENCE_KEYS and evidence.get(key):
                suggested.append(option.id)
                break
    return tuple(suggested)


def start_run(service, session_id, tree_id, version=None):
    """Begin a guided run against a session's evidence. Returns a run record."""
    if version is None:
        tree = TREES.get(tree_id)
        if tree is None:
            raise ValueError(f'Unknown decision tree {tree_id}.')
    else:
        tree = get_tree(tree_id, version)
    if service.session(session_id) is None:
        raise ValueError('Start or choose a diagnostic session first.')
    evidence = evidence_from_session(service, session_id)
    run = {
        'tree_id': tree.id, 'tree_version': tree.version, 'session_id': session_id,
        'node': tree.root, 'path': [], 'started_at': datetime.now(timezone.utc).isoformat(),
        'evidence': evidence, 'finished': False, 'outcome': None, 'outcome_severity': None,
    }
    return run


def resume_run(service, stored):
    """Rebuild an unfinished run from a saved record, using its own tree revision.

    The stored tree version is honoured so a run started under an earlier revision
    is completed against that revision, not a newer one. Raises for a completed run
    or an unavailable revision so the caller can explain the situation.
    """
    if not isinstance(stored, dict) or 'tree_id' not in stored:
        raise ValueError('No saved guided run to resume.')
    if stored.get('finished'):
        raise ValueError('That guided run is already complete.')
    tree = get_tree(stored['tree_id'], stored.get('tree_version'))
    session_id = stored.get('session_id')
    if service.session(session_id) is None:
        raise ValueError('The session for that guided run no longer exists.')
    path = stored.get('path') or []
    if isinstance(path, str):
        import json
        path = json.loads(path or '[]')
    evidence = stored.get('evidence') or {}
    if isinstance(evidence, str):
        import json
        evidence = json.loads(evidence or '{}')
    # Replay the stored path so the resume point is exactly where the user left it.
    node_id = tree.root
    for step in path:
        node = tree.node(node_id)
        option = next((o for o in node.options if o.id == step.get('option')), None)
        if option is None:
            raise ValueError('The saved guided run path is no longer valid.')
        node_id = option.next
    target = tree.node(node_id)
    return {
        'id': stored.get('id'), 'tree_id': tree.id, 'tree_version': tree.version,
        'session_id': session_id, 'node': node_id, 'path': list(path),
        'started_at': stored.get('started_at') or datetime.now(timezone.utc).isoformat(),
        'evidence': dict(evidence), 'finished': False, 'outcome': None, 'outcome_severity': None,
    }


def run_history(run):
    """Ordered (node_id, option_id, label) steps recorded so far."""
    return tuple((step['node'], step['option'], step['label']) for step in run['path'])


def tree_for_run(run):
    """The exact tree revision a run belongs to (never a newer one)."""
    return get_tree(run['tree_id'], run.get('tree_version'))


def current_node(tree, run):
    return tree.node(run['node'])


def choose(tree, run, option_id):
    """Advance a run down an option. Returns the new current node."""
    node = tree.node(run['node'])
    option = next((o for o in node.options if o.id == option_id), None)
    if option is None:
        raise ValueError(f'Option {option_id} is not valid at node {node.id}.')
    run['path'].append({'node': node.id, 'option': option.id, 'label': option.label})
    run['node'] = option.next
    target = tree.node(option.next)
    if target.kind == 'outcome':
        run['finished'] = True
        run['outcome'] = target.title
        run['outcome_severity'] = target.severity
    return target


def transcript(tree, run):
    """Human-readable, reproducible record of the run so far."""
    lines = [f'{tree.title} (v{tree.version})', f'Symptom: {tree.symptom}', f'Provenance: {tree.provenance}']
    for index, step in enumerate(run['path'], 1):
        lines.append(f'{index}. {step["node"]}: {step["label"]}')
    if run['finished']:
        lines.append(f'Outcome: {run["outcome"]} [{run["outcome_severity"]}]')
    return '\n'.join(lines)

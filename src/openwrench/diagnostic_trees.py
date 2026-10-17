"""Milestone 5: versioned misfire and electrical diagnostic decision trees.

Rights and honesty constraints, deliberately:

* These trees are **authored engineering reasoning aids**, not manufacturer
  procedures and not an imported fault-code dataset. `docs/RESEARCH.md` records
  that no community code dataset was cleared for redistribution, so nothing is
  imported here; every node carries a short `basis` note describing the generic
  principle it relies on.
* No invented technical values. Nodes reference measurements the user has already
  captured, or direct the user to official service information for a specific
  test. Nothing asserts a torque, resistance, gap or replacement threshold.
* Trees are **versioned**. A guided run records the tree id and version it used,
  so a later revision never silently reword an earlier diagnosis.

The data model is intentionally plain: a tree is a root id plus a map of nodes.
Evaluation lives in `diagnostic_guide.py`.
"""

from dataclasses import dataclass, field

# Bumped whenever any node text, option or outcome changes for a given tree.
TREE_SCHEMA_VERSION = 1

NODE_KINDS = ('question', 'outcome')
MAX_NODES = 64
MAX_OPTIONS = 8


@dataclass(frozen=True)
class Option:
    """One branch: a user answer plus the node it leads to and an optional rule."""

    id: str
    label: str
    next: str
    suggested_when: tuple = ()   # declarative evidence rules, see diagnostic_guide


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    title: str
    detail: str
    basis: str = ''
    options: tuple = ()
    actions: tuple = ()          # outcome nodes: recommended next checks
    severity: str = ''           # outcome nodes: info, caution or warning


@dataclass(frozen=True)
class DiagnosticTree:
    id: str
    version: int
    title: str
    symptom: str
    provenance: str
    root: str
    nodes: dict = field(default_factory=dict)

    def node(self, node_id):
        try:
            return self.nodes[node_id]
        except KeyError as error:
            raise ValueError(f'Unknown node {node_id} in tree {self.id}.') from error


_PROVENANCE = (
    'Authored OpenWrench reasoning aid. Generic OBD-II/PID principles only; not a '
    'manufacturer procedure. Confirm every test value in official service information.'
)


MISFIRE = DiagnosticTree(
    id='misfire', version=1, symptom='Misfire',
    title='Misfire symptom guide',
    provenance=_PROVENANCE,
    root='codes',
    nodes={
        'codes': Node(
            'codes', 'question',
            'Which misfire evidence do you have?',
            'Start from the codes and live data already captured in this session. '
            'The recorded readings are shown beside each choice where they apply.',
            basis='OBD-II generic misfire codes P0300-P030X and their cylinder assignment.',
            options=(
                Option('cylinder', 'A cylinder-specific misfire code (e.g. P0301)', 'cylinder_code',
                       suggested_when=({'evidence': 'cylinder_codes'},)),
                Option('random', 'A random/multiple misfire code (P0300)', 'random_code',
                       suggested_when=({'evidence': 'random_misfire'},)),
                Option('none', 'Misfire symptom but no misfire code stored', 'no_code'),
            ),
        ),
        'cylinder_code': Node(
            'cylinder_code', 'question',
            'Is the misfire isolated to one cylinder that others do not share?',
            'A single-cylinder code points at parts unique to that cylinder: ignition '
            'coil/lead, injector, spark plug, or mechanical condition. Confirm the '
            'assignment in service information before swapping parts.',
            basis='Per-cylinder electrical and fuel components are the first suspects for a '
                  'single-cylinder misfire code.',
            options=(
                Option('isolated', 'Yes, only one cylinder is flagged', 'cylinder_isolated'),
                Option('shared', 'No, more than one cylinder is flagged', 'random_code'),
            ),
        ),
        'cylinder_isolated': Node(
            'cylinder_isolated', 'outcome',
            'Single-cylinder misfire',
            'The fault is likely local to the flagged cylinder. Use the captured live '
            'data to decide the order of the tests below, and record each result.',
            actions=(
                'Swap the coil/lead and plug with a known-good cylinder and re-run; if the '
                'code follows the part, replace it (basis: substitution isolates the component).',
                'If the code does not follow the part, test injector operation and compression '
                'per official service information (basis: fuel and mechanical faults stay put).',
                'Recheck fuel trim and ignition data after each step before concluding.',
            ),
            severity='caution',
        ),
        'random_code': Node(
            'random_code', 'question',
            'Does the captured live data show unstable engine speed at idle?',
            'Random/multiple misfire plus an unstable idle usually indicates a shared cause: '
            'air/fuel delivery, ignition system-wide, or a vacuum/intake leak.',
            basis='A shared-cause misfire perturbs idle stability across all cylinders.',
            options=(
                Option('unstable', 'Yes, engine speed is unstable', 'random_unstable',
                       suggested_when=({'evidence': 'rpm_spread_high'},)),
                Option('stable', 'No, engine speed looks steady', 'random_stable'),
            ),
        ),
        'random_unstable': Node(
            'random_unstable', 'outcome',
            'Random misfire with unstable idle',
            'Look for a shared cause rather than a single cylinder.',
            actions=(
                'Check for intake/vacuum leaks and unmetered air per service information '
                '(basis: a common leak leans all cylinders).',
                'Verify fuel pressure and delivery against the manufacturer specification '
                '(basis: low shared fuel pressure mimics random misfire).',
                'Inspect the ignition system as a whole, not one cylinder '
                '(basis: a shared ignition fault affects every cylinder).',
            ),
            severity='caution',
        ),
        'random_stable': Node(
            'random_stable', 'outcome',
            'Random misfire code with steady idle',
            'The misfire may be intermittent or load-dependent. Reproduce it under the '
            'condition it appears before replacing parts.',
            actions=(
                'Re-run the session under the load/condition where the symptom appears '
                '(basis: intermittent faults need a reproducing condition).',
                'Review stored and pending code status after the re-run '
                '(basis: pending-to-confirmed transitions confirm the fault).',
            ),
            severity='info',
        ),
        'no_code': Node(
            'no_code', 'outcome',
            'Misfire symptom without a stored code',
            'A symptom without a code is not yet a confirmed fault. Capture evidence '
            'first; do not replace parts on a symptom alone.',
            actions=(
                'Continue the session and try to capture a pending or confirmed code '
                '(basis: the monitor may not have matured the code yet).',
                'Record the conditions (temperature, speed, load) when it happens '
                '(basis: conditions narrow the suspect system).',
            ),
            severity='info',
        ),
    },
)


ELECTRICAL = DiagnosticTree(
    id='electrical', version=1, symptom='Electrical',
    title='Electrical and charging symptom guide',
    provenance=_PROVENANCE,
    root='codes',
    nodes={
        'codes': Node(
            'codes', 'question',
            'What electrical evidence do you have?',
            'Use the codes and live data captured in this session. Control module voltage '
            'is a measurement, not proof of the fault; confirm with a service-information '
            'procedure before replacing components.',
            basis='Generic charging/voltage codes and the control-module voltage PID.',
            options=(
                Option('charging', 'A charging/voltage code is stored', 'charging_code',
                       suggested_when=({'evidence': 'voltage_codes'},)),
                Option('low', 'No code, but voltage looks low on the capture', 'low_voltage',
                       suggested_when=({'evidence': 'voltage_low'},)),
                Option('drain', 'Battery drains while the vehicle sits', 'parasitic'),
                Option('none', 'No electrical code and voltage looks normal', 'inconclusive'),
            ),
        ),
        'charging_code': Node(
            'charging_code', 'question',
            'Does control-module voltage change with engine speed?',
            'A charging fault often tracks engine speed. If voltage does not rise with rpm, '
            'suspect the charging circuit; if it does but a code remains, suspect sensing '
            'or wiring.',
            basis='Alternator output is speed-dependent; a flat response points at the circuit.',
            options=(
                Option('tracks', 'Yes, voltage rises with engine speed', 'charging_circuit'),
                Option('flat', 'No, voltage stays flat as engine speed changes', 'charging_sense'),
            ),
        ),
        'charging_circuit': Node(
            'charging_circuit', 'outcome',
            'Charging output looks present',
            'The charging circuit appears to respond. Confirm the circuit against the '
            'manufacturer procedure before replacing any part.',
            actions=(
                'Verify battery condition and connections per service information '
                '(basis: a weak battery or terminal can hold a charging code).',
                'Check the charging-circuit wiring and grounds per service information '
                '(basis: voltage drop across a connection mimics a failed component).',
            ),
            severity='caution',
        ),
        'charging_sense': Node(
            'charging_sense', 'outcome',
            'Charging output not confirmed',
            'Voltage did not rise with engine speed. Treat the charging circuit and its '
            'sensing path as the suspect, and test per service information.',
            actions=(
                'Test alternator output against the manufacturer specification '
                '(basis: the charging source must be measured directly, not inferred).',
                'Inspect the sensing/field wiring the code names '
                '(basis: a sensing fault sets a charging code without a real failure).',
            ),
            severity='warning',
        ),
        'low_voltage': Node(
            'low_voltage', 'outcome',
            'Low measured control-module voltage',
            'The capture shows low voltage. This is an observation; confirm it with a '
            'proper charging-system test before concluding a part has failed.',
            actions=(
                'Repeat the measurement with a known-good meter at the battery '
                '(basis: module voltage can read low through a poor connection).',
                'Charge or load-test the battery per service information '
                '(basis: state of charge changes the reading).',
                'If low voltage persists with the engine running, test the charging '
                'circuit per service information (basis: confirms source vs. load).',
            ),
            severity='warning',
        ),
        'parasitic': Node(
            'parasitic', 'outcome',
            'Battery drains while parked',
            'A parked drain is a current measurement problem, not a code problem.',
            actions=(
                'Measure parasitic current with the vehicle fully asleep, using the '
                'manufacturer procedure (basis: modules must be asleep before measuring).',
                'Check for aftermarket accessories or a lamp left on '
                '(basis: common non-fault drains).',
            ),
            severity='caution',
        ),
        'inconclusive': Node(
            'inconclusive', 'outcome',
            'No electrical fault confirmed',
            'Nothing in this session confirms an electrical fault. Capture the symptom '
            'under the condition it appears before acting.',
            actions=(
                'Reproduce the symptom and capture live data at that moment '
                '(basis: an intermittent fault needs its conditions captured).',
            ),
            severity='info',
        ),
    },
)


TREES = {tree.id: tree for tree in (MISFIRE, ELECTRICAL)}

# Every historical revision of each tree, keyed by (id, version). A saved guided
# run stays reviewable against the exact revision it used even after the current
# tree is updated. When a tree changes, copy the previous revision here and bump
# the version on the live tree above.
TREE_VERSIONS = {(tree.id, tree.version): tree for tree in TREES.values()}


def get_tree(tree_id, version=None):
    """Return the current tree, or a specific historical revision when given.

    Raises ValueError for an unknown tree id or an unavailable version, so a
    caller never silently falls back to a different revision than it asked for.
    """
    if version is None:
        tree = TREES.get(tree_id)
        if tree is None:
            raise ValueError(f'Unknown decision tree {tree_id}.')
        return tree
    tree = TREE_VERSIONS.get((tree_id, int(version)))
    if tree is None:
        raise ValueError(
            f'Decision tree {tree_id} version {version} is not available in this build.')
    return tree


def validate_tree(tree):
    """Structural validation, run at import-by-test time and on load."""
    if tree.version < 1:
        raise ValueError('Tree version must be positive.')
    if tree.root not in tree.nodes:
        raise ValueError(f'Tree {tree.id} root is missing.')
    if len(tree.nodes) > MAX_NODES:
        raise ValueError(f'Tree {tree.id} exceeds {MAX_NODES} nodes.')
    for node in tree.nodes.values():
        if node.kind not in NODE_KINDS:
            raise ValueError(f'Node {node.id} has an invalid kind.')
        if not node.title.strip() or not node.detail.strip():
            raise ValueError(f'Node {node.id} is missing text.')
        if node.kind == 'question':
            if not node.options or len(node.options) > MAX_OPTIONS:
                raise ValueError(f'Question {node.id} needs 1-{MAX_OPTIONS} options.')
            for option in node.options:
                if option.next not in tree.nodes:
                    raise ValueError(f'Option {option.id} of {node.id} points at a missing node.')
        if node.kind == 'outcome':
            if node.options:
                raise ValueError(f'Outcome {node.id} must not have options.')
            if not node.actions:
                raise ValueError(f'Outcome {node.id} needs at least one action.')
            if node.severity not in ('info', 'caution', 'warning'):
                raise ValueError(f'Outcome {node.id} needs a valid severity.')
    # Every node must be reachable from the root.
    seen, stack = set(), [tree.root]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(option.next for option in tree.nodes[current].options)
    if seen != set(tree.nodes):
        raise ValueError(f'Tree {tree.id} has unreachable nodes: {set(tree.nodes) - seen}.')
    return tree


for _tree in TREES.values():
    validate_tree(_tree)

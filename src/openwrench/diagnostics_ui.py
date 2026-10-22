"""Native diagnostic session screens: start, live sensors, review and cleanup.

Data acquisition runs in a worker thread (`SessionRunner`) and the GUI thread only
persists emitted batches. A custom `SensorGraph` plots one selectable sensor at a
time with labelled axes, so unrelated units are never overlaid; history is bounded
per PID. The page scrolls so no control is clipped at small sizes or high display
scaling. Simulated sessions are labelled unmistakably in the banner and session list.
"""

from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from openwrench.diagnostics import (
    DEFAULT_PIDS, PID_CATALOG, PRIMARY_PIDS, format_sample, pid_key, pid_meta,
)
from openwrench.diagnostic_guide import (
    choose, current_node, resume_run, run_history, start_run,
    suggested_options, transcript, tree_for_run,
)
from openwrench.diagnostic_trees import TREES
from openwrench.guide_service import GuideService
from openwrench.diagnostics_session import DiagnosticService
from openwrench.diagnostics_sim import MODE_LABELS, SCENARIOS, SimulatorAdapter
from openwrench.diagnostics_worker import SessionRunner
from openwrench.garage import Garage

SERIES_COLORS = ['#17a89b', '#e0a73c', '#d1644b', '#5b8def', '#9b6bd6', '#4aa96c']
# Live history is bounded per PID so a long session cannot grow the GUI without limit.
MAX_LIVE_POINTS = 900

# Which trees the captured evidence points at. Used only to *hint* when a user picks
# a guide that does not match the evidence; the user may always choose freely.
TREE_EVIDENCE_KEYS = {
    'misfire': ('cylinder_codes', 'random_misfire'),
    'electrical': ('voltage_codes', 'voltage_low'),
}


def plain(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def tree_matches_evidence(tree_id, evidence):
    """Whether any signature evidence key for a tree is present in the session."""
    return any(evidence.get(key) for key in TREE_EVIDENCE_KEYS.get(tree_id, ()))


class SensorGraph(QWidget):
    """Single selectable sensor plot with labelled axes, unit and time in seconds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Live sensor graph')
        self.title = 'No sensor selected'
        self.unit = ''
        self.points = []          # [(elapsed_ms, value)]

    def set_series(self, title, unit, points):
        self.title = title
        self.unit = unit
        self.points = list(points)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#0d141b'))
        width, height = self.width(), self.height()
        left, right, top, bottom = 74, 18, 34, 40
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)

        painter.setFont(QFont('Segoe UI', 9))
        painter.setPen(QPen(QColor('#edf4f7')))
        axis_label = f'{self.title}'
        if self.unit:
            axis_label += f'  ({self.unit})'
        painter.drawText(8, 20, axis_label)

        # Plot frame and horizontal grid lines.
        painter.setPen(QPen(QColor('#334859')))
        painter.drawRect(left, top, plot_w, plot_h)
        for fraction in (0.25, 0.5, 0.75):
            y = int(top + plot_h * fraction)
            painter.drawLine(left, y, left + plot_w, y)

        if len(self.points) < 2:
            painter.setPen(QPen(QColor('#acbcc9')))
            hint = 'Start a session to plot live sensors.' if not self.points else 'Waiting for more samples…'
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, hint)
            return

        values = [v for _, v in self.points]
        times = [t for t, _ in self.points]
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        t0, t1 = min(times), max(times)
        tspan = (t1 - t0) or 1

        # Y axis: max / mid / min with the real value beside each grid line.
        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QPen(QColor('#acbcc9')))
        metrics = painter.fontMetrics()
        for fraction, value in ((0.0, high), (0.5, (high + low) / 2), (1.0, low)):
            y = int(top + plot_h * fraction)
            text = f'{value:g}'
            painter.drawText(left - 8 - metrics.horizontalAdvance(text), y + 4, text)

        # X axis: elapsed seconds at start, middle and end.
        for fraction, ms in ((0.0, t0), (0.5, (t0 + t1) / 2), (1.0, t1)):
            x = int(left + plot_w * fraction)
            label = f'{ms / 1000:.1f}s'
            painter.drawText(x - metrics.horizontalAdvance(label) // 2, top + plot_h + 20, label)

        colour = QColor(SERIES_COLORS[0])
        painter.setPen(QPen(colour, 2))
        previous = None
        for ms, value in self.points:
            x = int(left + (ms - t0) / tspan * plot_w)
            y = int(top + plot_h - (value - low) / span * plot_h)
            if previous:
                painter.drawLine(previous[0], previous[1], x, y)
            previous = (x, y)
        painter.setPen(QPen(colour))
        painter.drawText(left + 6, top + 16, f'last {values[-1]:g} {self.unit}'.strip())


class DiagnosticsPage(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.service = DiagnosticService(store)
        self.runner = SessionRunner(self)
        self.session_id = None
        self.sequence = 1
        self.live = {}
        self.last_session = None
        self.run = None
        self._build()
        self.runner.batch.connect(self.on_batch)
        self.runner.codes.connect(self.on_codes)
        self.runner.changed.connect(lambda text: self.status.setText(text))
        self.runner.finished.connect(self.on_finished)
        self.timer = QTimer(self); self.timer.setInterval(150)
        self.timer.timeout.connect(self.redraw)
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        heading = plain('Diagnostics'); heading.setObjectName('title'); layout.addWidget(heading)
        self.banner = plain('SIMULATED DATA — a deterministic simulator, not a real vehicle.')
        self.banner.setObjectName('banner'); layout.addWidget(self.banner)

        # Session controls, grouped in a card with a labelled grid.
        controls = QFrame(); controls.setObjectName('card')
        control_layout = QGridLayout(controls)
        control_layout.setContentsMargins(16, 16, 16, 16)
        control_layout.setHorizontalSpacing(12); control_layout.setVerticalSpacing(6)
        control_layout.addWidget(self._muted('Vehicle'), 0, 0, 1, 2)
        self.vehicle = QComboBox(); self.vehicle.setAccessibleName('Diagnostic session vehicle')
        self.vehicle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        control_layout.addWidget(self.vehicle, 1, 0, 1, 2)
        control_layout.addWidget(self._muted('Scenario'), 0, 2, 1, 2)
        self.scenario = QComboBox(); self.scenario.setAccessibleName('Simulation scenario')
        for key, (label, _) in SCENARIOS.items():
            self.scenario.addItem(label, key)
        control_layout.addWidget(self.scenario, 1, 2, 1, 2)
        control_layout.addWidget(self._muted('Sample interval'), 0, 4)
        self.interval = QSpinBox(); self.interval.setRange(50, 2000); self.interval.setSingleStep(50)
        self.interval.setValue(100); self.interval.setSuffix(' ms'); self.interval.setAccessibleName('Sample interval')
        control_layout.addWidget(self.interval, 1, 4)
        self.hardware = QCheckBox('Use USB adapter'); self.hardware.setEnabled(False)
        self.hardware.setToolTip('Hardware is experimental and disabled by default. Enable it in Settings.')
        control_layout.addWidget(self.hardware, 1, 5)
        control_layout.setColumnStretch(1, 1); control_layout.setColumnStretch(3, 1)
        buttons = QHBoxLayout()
        self.start_button = QPushButton('Start session'); self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.start_button); buttons.addWidget(self.stop_button); buttons.addStretch()
        self.start_button.clicked.connect(self.start_session)
        self.stop_button.clicked.connect(self.stop_session)
        control_layout.addLayout(buttons, 2, 0, 1, 6)
        layout.addWidget(controls)

        # Readout grid: fixed 3 columns so labels never overlap.
        readouts = QFrame(); readouts.setObjectName('card')
        readout_layout = QGridLayout(readouts)
        readout_layout.setContentsMargins(16, 16, 16, 16)
        readout_layout.setHorizontalSpacing(18); readout_layout.setVerticalSpacing(2)
        self.readout_labels = {}
        for index, pid in enumerate(PRIMARY_PIDS):
            label, unit, *_ = pid_meta(pid)
            row, column = divmod(index, 3)
            name = plain(label); name.setObjectName('muted')
            value = plain(f'— {unit}'); value.setObjectName('heading')
            readout_layout.addWidget(name, row * 2, column)
            readout_layout.addWidget(value, row * 2 + 1, column)
            readout_layout.setColumnStretch(column, 1)
            self.readout_labels[pid_key(pid)] = value
        layout.addWidget(readouts)

        # Sensor graph with a PID selector and a captured-sensor legend.
        graph_card = QFrame(); graph_card.setObjectName('card')
        graph_layout = QVBoxLayout(graph_card)
        graph_layout.setContentsMargins(16, 16, 16, 16); graph_layout.setSpacing(8)
        picker = QHBoxLayout()
        picker.addWidget(self._muted('Graph sensor'))
        self.graph_pid = QComboBox(); self.graph_pid.setAccessibleName('Graph sensor')
        for pid in DEFAULT_PIDS:
            label, unit, *_ = pid_meta(pid)
            self.graph_pid.addItem(f'{label} ({unit})', pid_key(pid))
        self.graph_pid.currentIndexChanged.connect(self.redraw)
        picker.addWidget(self.graph_pid, 1)
        graph_layout.addLayout(picker)
        self.graph = SensorGraph(); graph_layout.addWidget(self.graph, 1)
        self.legend = plain('One sensor at a time. Use the selector to switch sensors.')
        self.legend.setObjectName('muted'); graph_layout.addWidget(self.legend)
        layout.addWidget(graph_card)

        self.status = plain('Choose a vehicle and start a session.'); layout.addWidget(self.status)

        layout.addWidget(self._section_label('Diagnostic codes'))
        self.codes = QListWidget()
        self.codes.setMinimumHeight(120)
        self.codes.setAccessibleName('Diagnostic codes')
        layout.addWidget(self.codes)
        layout.addWidget(self._section_label('Saved sessions'))
        self.sessions = QListWidget()
        self.sessions.setMinimumHeight(150)
        self.sessions.setAccessibleName('Saved diagnostic sessions')
        layout.addWidget(self.sessions)
        actions = QHBoxLayout()
        for title, callback in [('Review session', self.review), ('Delete session', self.delete_session), ('Refresh', self.refresh)]:
            button = QPushButton(title); button.clicked.connect(callback); actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.detail = plain(''); self.detail.setMinimumHeight(40); layout.addWidget(self.detail)

        self._build_guide(layout)
        layout.addStretch()

    @staticmethod
    def _section_label(text):
        label = plain(text); label.setObjectName('heading')
        return label

    @staticmethod
    def _muted(text):
        label = plain(text); label.setObjectName('muted')
        return label

    def _build_guide(self, layout):
        """Milestone 5 guided decision trees. Authored reasoning aids, not procedures."""
        layout.addWidget(self._section_label('Guided diagnosis'))
        self.guide_banner = plain(
            'Authored reasoning aid using this session\'s captured evidence. Not a manufacturer '
            'procedure. Confirm every test value in official service information.')
        self.guide_banner.setObjectName('banner'); layout.addWidget(self.guide_banner)
        picker = QHBoxLayout()
        self.guide_tree = QComboBox()
        for tree in TREES.values():
            self.guide_tree.addItem(f'{tree.title} (v{tree.version})', tree.id)
        self.guide_tree.setAccessibleName('Decision tree')
        picker.addWidget(self.guide_tree, 1)
        self.guide_start = QPushButton('Start guide'); self.guide_start.clicked.connect(self.start_guide)
        self.guide_resume = QPushButton('Resume saved run'); self.guide_resume.clicked.connect(self.resume_guide)
        self.guide_save = QPushButton('Save run'); self.guide_save.setEnabled(False)
        self.guide_save.clicked.connect(self.save_guide)
        picker.addWidget(self.guide_start); picker.addWidget(self.guide_resume); picker.addWidget(self.guide_save)
        layout.addLayout(picker)
        self.guide_node = self._section_label('Choose a session in Review, then start a guide.')
        layout.addWidget(self.guide_node)
        self.guide_detail = plain(''); layout.addWidget(self.guide_detail)
        self.guide_evidence = plain(''); self.guide_evidence.setObjectName('muted')
        layout.addWidget(self.guide_evidence)
        self.guide_note = plain(''); self.guide_note.setObjectName('banner')
        self.guide_note.setVisible(False); layout.addWidget(self.guide_note)
        self.guide_options = QVBoxLayout(); self.guide_options.setSpacing(6)
        layout.addLayout(self.guide_options)
        self.guide_history = plain(''); self.guide_history.setObjectName('muted')
        layout.addWidget(self.guide_history)
        self.guide_outcome = plain(''); layout.addWidget(self.guide_outcome)
        layout.addWidget(self._section_label('Saved guided runs'))
        self.guide_runs = QListWidget(); self.guide_runs.setMinimumHeight(110)
        self.guide_runs.setAccessibleName('Saved guided runs'); layout.addWidget(self.guide_runs)

    # -- lifecycle ---------------------------------------------------------
    def refresh(self):
        current = self.vehicle.currentData()
        self.vehicle.clear()
        for vehicle in Garage(self.store).vehicles():
            self.vehicle.addItem(vehicle['nickname'], vehicle['id'])
        index = self.vehicle.findData(current) if current else 0
        self.vehicle.setCurrentIndex(max(0, index))
        self.hardware.setEnabled(self.store.hardware_enabled)
        if not self.store.hardware_enabled:
            self.hardware.setChecked(False)
        self.reload_sessions()

    def start_session(self):
        identifier = self.vehicle.currentData()
        if not identifier:
            QMessageBox.information(self, 'No vehicle', 'Add a Garage vehicle before starting a session.')
            return
        scenario = self.scenario.currentData()
        simulated = not self.hardware.isChecked()
        adapter = 'simulator' if simulated else 'elm327'
        self.session_id = self.service.start(identifier, adapter, scenario, simulated)
        self.sequence = 1; self.live = {}
        self.banner.setText(
            'SIMULATED DATA — deterministic simulator, not a real vehicle.'
            if simulated else
            'EXPERIMENTAL USB ADAPTER — read-only requests. Compatibility is unverified.')
        self.banner.setStyleSheet('color:#e0a73c;' if not simulated else '')
        factory = (lambda: SimulatorAdapter(scenario)) if simulated else self._hardware_factory
        try:
            self.runner.start(factory, DEFAULT_PIDS, self.interval.value(), scan_codes=True)
        except ValueError as error:
            self.service.finish(self.session_id, 'failed')
            QMessageBox.critical(self, 'Diagnostics', str(error))
            return
        self.start_button.setEnabled(False); self.stop_button.setEnabled(True)
        self.timer.start()
        self.status.setText('Session running in a worker thread.')

    def reset_after_restore(self):
        """Discard selections and unsaved guides belonging to the replaced data."""
        self.session_id = self.last_session = self.run = None
        self.live = {}
        self.codes.clear()
        self.detail.clear()
        self.guide_runs.clear()
        self.guide_save.setEnabled(False)
        for label in (self.guide_node, self.guide_detail, self.guide_evidence,
                      self.guide_history, self.guide_outcome):
            label.clear()
        self.guide_note.setVisible(False)
        while self.guide_options.count():
            item = self.guide_options.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for label in self.readout_labels.values():
            if label is not None:
                label.setText('—')
        self.status.setText('Workspace restored. Select a session to review.')
        self.refresh()
        self.redraw()

    def _hardware_factory(self):
        from openwrench.diagnostics_hardware import ElmAdapter, SerialTransport, default_ports
        ports = default_ports()
        if not ports:
            raise ValueError('No serial port found. Connect a read-only USB adapter or use the simulator.')
        return ElmAdapter(SerialTransport(ports[0]))

    def stop_session(self):
        if self.runner.active:
            self.runner.stop()
        self.timer.stop()
        self.start_button.setEnabled(True); self.stop_button.setEnabled(False)

    def on_finished(self, status):
        self.timer.stop()
        self.start_button.setEnabled(True); self.stop_button.setEnabled(False)
        if self.session_id:
            # Map the recorder's final state onto the stored session vocabulary
            # without mislabelling a lost link or an error as a clean completion.
            if status == 'completed':
                final = 'completed'
            elif status == 'disconnected' or status.startswith('failed') or status.startswith('Adapter unavailable'):
                final = 'failed'
            else:
                final = 'interrupted'
            try:
                self.service.finish(self.session_id, final)
            except ValueError:
                pass
        self.last_session = self.session_id
        self.status.setText(f'Session {status}. {self._count()} samples stored.')
        self.session_id = None
        self.reload_sessions()

    def _count(self):
        if not self.last_session:
            return 0
        return self.store.connection.execute(
            'SELECT COUNT(*) FROM diagnostic_samples WHERE session_id=?', (self.last_session,)).fetchone()[0]

    # -- live data ---------------------------------------------------------
    def on_batch(self, samples, elapsed_ms):
        if not self.session_id:
            return
        try:
            self.sequence = self.service.append(self.session_id, samples, self.sequence, elapsed_ms)
        except ValueError as error:
            self.stop_session()
            self.status.setText(str(error)); return
        for sample in samples:
            key = pid_key(sample.pid)
            # Capture history for every PID that reports a value, even without a
            # readout label, so the graph can show any supported sensor.
            if sample.status == 'ok' and sample.value is not None:
                self.live.setdefault(key, deque(maxlen=MAX_LIVE_POINTS)).append((elapsed_ms, sample.value))
            # Only update a label that actually exists; never call setText on None.
            label = self.readout_labels.get(key)
            if label is not None:
                label.setText(format_sample(sample))

    def on_codes(self, results):
        """Store and display codes with their real response mode (03/07/0A)."""
        for mode, codes in results:
            for code in codes:
                status = getattr(code, 'status', None) or MODE_LABELS.get(mode, mode)
                description = getattr(code, 'description', '') or ''
                value = getattr(code, 'code', code)
                line = f'{value} · {status} · mode {mode}'
                if description:
                    line += f' · {description}'
                self.codes.addItem(line)
                if self.session_id:
                    self.service.add_codes(self.session_id, [code], mode)

    def redraw(self):
        key = self.graph_pid.currentData()
        points = list(self.live.get(key, ()))
        entry = PID_CATALOG.get(int(key, 16)) if key else None
        if entry:
            label, unit = entry[0], entry[1]
        else:
            label, unit = key or 'No sensor', ''
        self.graph.set_series(label, unit, points)
        available = []
        for pid in DEFAULT_PIDS:
            sample_label, sample_unit, *_ = pid_meta(pid)
            count = len(self.live.get(pid_key(pid), ()))
            if count:
                available.append(f'{sample_label} ({count})')
        self.legend.setText('Captured this session: ' + (', '.join(available) if available else 'none yet'))

    # -- history -----------------------------------------------------------
    def reload_sessions(self):
        self.sessions.clear()
        identifier = self.vehicle.currentData()
        for row in self.service.sessions(identifier):
            tag = 'SIMULATED' if row['simulated'] else 'USB'
            started = (row['started_at'] or '')[:19].replace('T', ' ')
            item = QListWidgetItem(f'{started} · {tag} · {row["scenario"]} · {row["status"]}')
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.sessions.addItem(item)

    def review(self):
        item = self.sessions.currentItem()
        if not item:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        self.last_session = row['id']
        self.codes.clear()
        for code in self.service.codes(row['id']):
            self.codes.addItem(
                f'{code["code"]} · {code["status"]} · mode {code["mode"]} · {code["description"]}')
        lines = [f'{row["adapter"]} · {row["scenario"]} · {row["status"]} · started {row["started_at"]}']
        for pid in DEFAULT_PIDS:
            points = self.service.series(row['id'], pid)
            if points:
                label, unit, *_ = pid_meta(pid)
                values = [v for _, v in points]
                lines.append(f'{label}: {len(values)} samples, last {values[-1]:g} {unit}, min {min(values):g}, max {max(values):g}')
        stored = self.service.samples(row['id'])
        lines.append(f'{len(stored)} stored sample rows; {len(self.service.codes(row["id"]))} codes.')
        self.detail.setText('\n'.join(lines))
        # Reflect the saved session in the graph: load stored points for every
        # default PID so a reviewed session plots exactly what was recorded.
        self.live = {}
        for pid in DEFAULT_PIDS:
            points = self.service.series(row['id'], pid)
            if points:
                self.live[pid_key(pid)] = deque(points, maxlen=MAX_LIVE_POINTS)
        self.redraw()
        self.reload_guide_runs(row['id'])

    def delete_session(self):
        item = self.sessions.currentItem()
        if not item:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, 'Delete session?', 'Delete this diagnostic session and its samples? Garage records stay intact.',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.service.delete(row['id']); self.codes.clear(); self.detail.setText(''); self.reload_sessions()

    # -- guided decision trees (Milestone 5) -------------------------------
    def start_guide(self):
        if not self.last_session:
            QMessageBox.information(self, 'No session', 'Review a diagnostic session first, then start a guide.')
            return
        try:
            self.run = start_run(self.service, self.last_session, self.guide_tree.currentData())
        except ValueError as error:
            QMessageBox.information(self, 'Guided diagnosis', str(error)); return
        self.guide_save.setEnabled(True)
        self.show_node()

    def resume_guide(self):
        item = self.guide_runs.currentItem()
        stored = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not stored:
            QMessageBox.information(self, 'No saved run', 'Select an unfinished saved run to resume.')
            return
        try:
            self.run = resume_run(self.service, stored)
        except ValueError as error:
            QMessageBox.information(self, 'Guided diagnosis', str(error)); return
        self.guide_save.setEnabled(True)
        self.show_node()

    def show_node(self):
        while self.guide_options.count():
            item = self.guide_options.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tree = tree_for_run(self.run)
        node = current_node(tree, self.run)
        self.guide_node.setText(f'{tree.title} (v{tree.version}) — {node.title}')
        self.guide_detail.setText(node.detail)
        evidence = ', '.join(sorted(k for k, v in self.run['evidence'].items() if v)) or 'none'
        self.guide_evidence.setText(
            f'Basis: {node.basis}\nEvidence from this session ({self._session_label()}): {evidence}')
        self._update_guide_note(tree)
        self._update_guide_history()
        if node.kind == 'outcome':
            self.guide_outcome.setText(
                f'Outcome [{node.severity}]:\n' + '\n'.join(f'• {action}' for action in node.actions))
            self.guide_save.setEnabled(True)
            return
        self.guide_outcome.setText('')
        suggested = set(suggested_options(node, self.run['evidence']))
        for option in node.options:
            marker = '   (suggested by captured data)' if option.id in suggested else ''
            button = QPushButton(f'{option.label}{marker}')
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            button.setStyleSheet('text-align:left; padding:10px;')
            button.setAccessibleName(f'Answer: {option.label}')
            button.clicked.connect(lambda _=False, oid=option.id: self.choose_option(oid))
            self.guide_options.addWidget(button)

    def _update_guide_note(self, tree):
        """Explain a mismatch when the chosen guide does not match the evidence.

        This never blocks a legitimate manual selection; it only informs.
        """
        matched = tree_matches_evidence(tree.id, self.run['evidence'])
        others = [other for other in TREES.values()
                  if other.id != tree.id and tree_matches_evidence(other.id, self.run['evidence'])]
        if matched or not others:
            self.guide_note.setVisible(False)
            return
        self.guide_note.setText(
            'Heads up: the captured evidence for this session points at '
            + ', '.join(f'"{other.title}"' for other in others)
            + '. You can continue with this guide, or switch and start the matching one.')
        self.guide_note.setVisible(True)

    def _update_guide_history(self):
        steps = run_history(self.run)
        if not steps:
            self.guide_history.setText('No answers recorded yet.')
            return
        self.guide_history.setText(
            'Your answers: ' + ' → '.join(label for _, _, label in steps))

    def _session_label(self):
        """Short human label for the session a guided run belongs to."""
        if not self.run or not self.run.get('session_id'):
            return 'no session'
        try:
            row = self.service.session(self.run['session_id'])
        except ValueError:
            return 'deleted session'
        started = (row['started_at'] or '')[:19].replace('T', ' ')
        tag = 'simulated' if row['simulated'] else 'USB'
        return f'{tag} {row["scenario"]} session, started {started}'

    def choose_option(self, option_id):
        tree = tree_for_run(self.run)
        choose(tree, self.run, option_id)
        self.show_node()

    def save_guide(self):
        if not self.run:
            return
        try:
            GuideService(self.store).save(self.run)
        except ValueError as error:
            QMessageBox.critical(self, 'Guided diagnosis', str(error)); return
        self.guide_node.setText('Run saved.' if self.run['finished'] else 'Run saved. You can resume it later.')
        self.guide_detail.setText(transcript(tree_for_run(self.run), self.run))
        self.guide_save.setEnabled(False)
        self.reload_guide_runs(self.run['session_id'])

    def reload_guide_runs(self, session_id):
        self.guide_runs.clear()
        if not session_id:
            return
        for row in GuideService(self.store).runs(session_id, decoded=True):
            state = 'complete' if row['finished'] else 'in progress — resumable'
            label = f'{row["tree_id"]} v{row["tree_version"]} · {row["outcome"] or "(no outcome)"} · {state}'
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.guide_runs.addItem(item)

    def stop(self):
        if self.runner.active:
            self.runner.stop()
        self.timer.stop()

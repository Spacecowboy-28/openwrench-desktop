"""Native diagnostic session screens: start, live sensors, review and cleanup.

Data acquisition runs in a worker thread (`SessionRunner`) and the GUI thread only
persists emitted batches. The custom `SensorGraph` plots stored samples without a
charting dependency, keeping the packaged bundle small and the license surface flat.
Simulated sessions are labelled unmistakably in the banner and session list.
"""

from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from openwrench.diagnostics import (
    DEFAULT_PIDS, PID_CATALOG, PRIMARY_PIDS, format_sample, pid_key, pid_meta,
)
from openwrench.diagnostic_guide import (
    choose, current_node, evidence_from_session, start_run, suggested_options, transcript,
)
from openwrench.diagnostic_trees import TREES
from openwrench.guide_service import GuideService
from openwrench.diagnostics_session import DiagnosticService
from openwrench.diagnostics_sim import SCENARIOS, SimulatorAdapter
from openwrench.diagnostics_worker import SessionRunner
from openwrench.garage import Garage

SERIES_COLORS = ['#17a89b', '#e0a73c', '#d1644b', '#5b8def', '#9b6bd6', '#4aa96c']


def plain(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class SensorGraph(QWidget):
    """Normalized multi-series plot. Each series scales to its own observed range."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.series = {}   # 'PID' -> (label, unit, [(ms, value)])
        self.setAccessibleName('Live sensor graph')

    def set_series(self, series):
        self.series = series
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#0d141b'))
        pen = QPen(QColor('#334859')); painter.setPen(pen)
        for fraction in (0.25, 0.5, 0.75):
            y = int(self.height() * fraction)
            painter.drawLine(0, y, self.width(), y)
        if not self.series:
            painter.setPen(QPen(QColor('#acbcc9')))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Start a session to plot live sensors.')
            return
        painter.setFont(QFont('Segoe UI', 8))
        for index, (key, (label, unit, points)) in enumerate(sorted(self.series.items())):
            if len(points) < 2:
                continue
            values = [v for _, v in points]
            low, high = min(values), max(values)
            span = (high - low) or 1.0
            times = [t for t, _ in points]
            tspan = (max(times) - min(times)) or 1
            color = QColor(SERIES_COLORS[index % len(SERIES_COLORS)])
            painter.setPen(QPen(color, 2))
            previous = None
            for ms, value in points:
                x = int((ms - min(times)) / tspan * (self.width() - 1))
                y = int(self.height() - 20 - (value - low) / span * (self.height() - 40))
                if previous:
                    painter.drawLine(previous[0], previous[1], x, y)
                previous = (x, y)
            painter.setPen(QPen(color))
            painter.drawText(6, 14 + index * 14, f'{label}  {values[-1]:g} {unit}')


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
        self._build()
        self.runner.batch.connect(self.on_batch)
        self.runner.codes.connect(self.on_codes)
        self.runner.changed.connect(lambda text: self.status.setText(text))
        self.runner.finished.connect(self.on_finished)
        self.timer = QTimer(self); self.timer.setInterval(120)
        self.timer.timeout.connect(self.redraw)
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        heading = plain('Diagnostics'); heading.setObjectName('title'); layout.addWidget(heading)
        self.banner = plain('SIMULATED DATA — a deterministic simulator, not a real vehicle.')
        self.banner.setObjectName('banner'); layout.addWidget(self.banner)
        controls = QHBoxLayout()
        self.vehicle = QComboBox(); self.vehicle.setAccessibleName('Diagnostic session vehicle')
        controls.addWidget(self.vehicle, 1)
        self.scenario = QComboBox()
        for key, (label, _) in SCENARIOS.items():
            self.scenario.addItem(label, key)
        controls.addWidget(self.scenario)
        self.interval = QSpinBox(); self.interval.setRange(50, 2000); self.interval.setSingleStep(50)
        self.interval.setValue(100); self.interval.setSuffix(' ms'); self.interval.setAccessibleName('Sample interval')
        controls.addWidget(self.interval)
        self.hardware = QCheckBox('Use USB adapter'); self.hardware.setEnabled(False)
        self.hardware.setToolTip('Hardware is experimental and disabled by default. Enable it in Settings.')
        controls.addWidget(self.hardware)
        layout.addLayout(controls)
        buttons = QHBoxLayout()
        self.start_button = QPushButton('Start session'); self.stop_button = QPushButton('Stop')
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.start_button); buttons.addWidget(self.stop_button)
        self.start_button.clicked.connect(self.start_session)
        self.stop_button.clicked.connect(self.stop_session)
        layout.addLayout(buttons)
        self.readouts = QHBoxLayout(); layout.addLayout(self.readouts)
        self.readout_labels = {}
        for index, pid in enumerate(PRIMARY_PIDS):
            label, unit, *_ = pid_meta(pid)
            box = QVBoxLayout()
            name = plain(label); name.setObjectName('heading')
            value = plain(f'— {unit}'); value.setObjectName('muted')
            box.addWidget(name); box.addWidget(value)
            self.readouts.addLayout(box)
            self.readout_labels[pid_key(pid)] = value
        self.graph = SensorGraph(); layout.addWidget(self.graph, 2)
        self.status = plain('Choose a vehicle and start a session.'); layout.addWidget(self.status)
        row = QHBoxLayout()
        self.codes = QListWidget(); self.codes.setMaximumHeight(120)
        row.addWidget(self.codes, 1)
        self.sessions = QListWidget(); row.addWidget(self.sessions, 1)
        layout.addLayout(row)
        actions = QHBoxLayout()
        for title, callback in [('Review session', self.review), ('Delete session', self.delete_session), ('Refresh', self.refresh)]:
            button = QPushButton(title); button.clicked.connect(callback); actions.addWidget(button)
        layout.addLayout(actions)
        self.detail = plain(''); layout.addWidget(self.detail)
        self._build_guide(layout)

    def _build_guide(self, layout):
        """Milestone 5 guided decision trees. Authored reasoning aids, not procedures."""
        heading = plain('Guided diagnosis'); heading.setObjectName('heading'); layout.addWidget(heading)
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
        self.guide_save = QPushButton('Save run'); self.guide_save.setEnabled(False)
        self.guide_save.clicked.connect(self.save_guide)
        picker.addWidget(self.guide_start); picker.addWidget(self.guide_save)
        layout.addLayout(picker)
        self.guide_node = plain('Choose a session in Review, then start a guide.')
        self.guide_node.setObjectName('heading'); layout.addWidget(self.guide_node)
        self.guide_detail = plain(''); layout.addWidget(self.guide_detail)
        self.guide_evidence = plain(''); self.guide_evidence.setObjectName('muted')
        layout.addWidget(self.guide_evidence)
        self.guide_options = QVBoxLayout(); layout.addLayout(self.guide_options)
        self.guide_outcome = plain(''); layout.addWidget(self.guide_outcome)
        self.guide_runs = QListWidget(); self.guide_runs.setMaximumHeight(90)
        self.guide_runs.setAccessibleName('Saved guided runs'); layout.addWidget(self.guide_runs)
        self.run = None

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

    def _hardware_factory(self):
        from openwrench.diagnostics_hardware import ElmAdapter, SerialTransport, default_ports
        ports = default_ports()
        if not ports:
            raise ValueError('No serial port found. Connect a read-only USB adapter or use the simulator.')
        return ElmAdapter(SerialTransport(ports[0]))

    def stop_session(self):
        if self.runner.active:
            status = 'interrupted'
            self.runner.stop()
        self.timer.stop()
        self.start_button.setEnabled(True); self.stop_button.setEnabled(False)

    def on_finished(self, status):
        self.timer.stop()
        self.start_button.setEnabled(True); self.stop_button.setEnabled(False)
        if self.session_id:
            try:
                self.service.finish(self.session_id, 'completed' if status == 'completed' else 'interrupted')
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
            if sample.status == 'ok':
                self.live.setdefault(pid_key(sample.pid), []).append((elapsed_ms, sample.value))
            self.readout_labels.setdefault(pid_key(sample.pid), None)
            if pid_key(sample.pid) in self.readout_labels:
                self.readout_labels[pid_key(sample.pid)].setText(
                    f'{format_sample(sample)}')

    def on_codes(self, codes):
        for code in codes:
            self.codes.addItem(f'{code.code} · {code.status} · {code.description}')
        if self.session_id and codes:
            self.service.add_codes(self.session_id, codes, '03')

    def redraw(self):
        series = {}
        for key, points in self.live.items():
            entry = PID_CATALOG.get(int(key, 16))
            if entry:
                series[key] = (entry[0], entry[1], points)
        self.graph.set_series(series)

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
            self.codes.addItem(f'{code["code"]} · {code["status"]} · {code["mode"]} · {code["description"]}')
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

    def show_node(self):
        while self.guide_options.count():
            item = self.guide_options.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tree = TREES[self.run['tree_id']]
        node = current_node(tree, self.run)
        self.guide_node.setText(node.title)
        self.guide_detail.setText(node.detail)
        evidence = ', '.join(sorted(k for k, v in self.run['evidence'].items() if v)) or 'none'
        self.guide_evidence.setText(f'Basis: {node.basis}\nEvidence from this session: {evidence}')
        if node.kind == 'outcome':
            self.guide_outcome.setText(
                f'Outcome [{node.severity}]:\n' + '\n'.join(f'• {action}' for action in node.actions))
            self.guide_save.setEnabled(True)
            return
        self.guide_outcome.setText('')
        suggested = set(suggested_options(node, self.run['evidence']))
        for option in node.options:
            marker = '  (suggested by captured data)' if option.id in suggested else ''
            button = QPushButton(f'{option.label}{marker}')
            button.clicked.connect(lambda _=False, oid=option.id: self.choose_option(oid))
            self.guide_options.addWidget(button)

    def choose_option(self, option_id):
        tree = TREES[self.run['tree_id']]
        choose(tree, self.run, option_id)
        self.show_node()

    def save_guide(self):
        if not self.run:
            return
        try:
            GuideService(self.store).save(self.run)
        except ValueError as error:
            QMessageBox.critical(self, 'Guided diagnosis', str(error)); return
        self.guide_node.setText('Run saved.')
        self.guide_detail.setText(transcript(TREES[self.run['tree_id']], self.run))
        self.guide_save.setEnabled(False)
        self.guide_runs.clear()
        for row in GuideService(self.store).runs(self.run['session_id']):
            self.guide_runs.addItem(f'{row["tree_id"]} v{row["tree_version"]} · {row["outcome"] or "(in progress)"}')

    def stop(self):
        if self.runner.active:
            self.runner.stop()
        self.timer.stop()

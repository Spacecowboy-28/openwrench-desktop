"""Off-GUI-thread acquisition for diagnostic sessions.

A `Recorder` runs inside a worker `QThread` and owns the adapter. It never touches
SQLite; it only reads the adapter and emits `SensorSample` batches. The GUI thread
persists those batches, so a blocking serial read can never freeze the interface
and no SQLite connection crosses a thread boundary.
"""

from datetime import datetime, timezone

from PySide6.QtCore import QObject, QThread, Signal

from openwrench.diagnostics import (
    MAX_SESSION_SECONDS,
    AdapterCapabilities,
    SensorSample,
    pid_key,
)


def acquire_batch(adapter, pids, last_good, disconnected=False):
    """Read one sample per PID. Pure helper so it is testable without a thread.

    A timeout that follows a good reading is reported as `stale` with the last
    known value, so the UI can distinguish "no data yet" from "data went flat".
    """
    samples = []
    for pid in pids:
        key = pid_key(pid)
        if disconnected:
            samples.append(SensorSample(key, None, '', _now(), 'disconnected'))
            continue
        sample = adapter.read_pid(key)
        if sample.status == 'ok' and sample.value is not None:
            last_good[key] = (sample.value, sample.unit)
            samples.append(sample)
        elif sample.status in ('timeout', 'unsupported') and key in last_good:
            value, unit = last_good[key]
            samples.append(SensorSample(key, value, unit, _now(), 'stale'))
        else:
            samples.append(sample)
    return samples


def _now():
    return datetime.now(timezone.utc).isoformat()


class Recorder(QObject):
    """Lives in a worker thread. Emits batches; the GUI thread stores them."""

    batch = Signal(object, int)      # (samples, elapsed_ms)
    codes = Signal(object)           # list[DiagnosticCode]
    changed = Signal(str)            # human-readable status line
    stopped = Signal(str)            # final status: completed/interrupted/failed

    def __init__(self, adapter_factory, pids, interval_ms=100, max_seconds=MAX_SESSION_SECONDS,
                 scan_codes=True, parent=None):
        super().__init__(parent)
        self._factory = adapter_factory
        self._pids = tuple(pid_key(p) for p in pids)
        self._interval = max(20, int(interval_ms))
        self._max_seconds = min(int(max_seconds), MAX_SESSION_SECONDS)
        self._scan_codes = bool(scan_codes)
        self._running = False
        self._cancelled = False
        self.capabilities = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Execute inside the worker thread. Configured before `started` fires."""
        try:
            adapter = self._factory()
            self.capabilities: AdapterCapabilities = adapter.connect()
            self.changed.emit('Adapter connected: ' + self.capabilities.adapter_id)
        except Exception as error:
            self.stopped.emit(f'Adapter unavailable: {error}')
            return
        self._running = True
        last_good = {}
        elapsed = 0
        deadline = self._max_seconds * 1000
        try:
            if self._scan_codes:
                for mode in ('03', '07', '0A'):
                    rows = adapter.codes() if hasattr(adapter, 'codes') else ()
                    self.codes.emit(rows)
                    break  # one consolidated read is enough for the simulator
            while self._running and elapsed < deadline:
                if self._cancelled:
                    break
                disconnected = not getattr(adapter, 'connected', True)
                samples = acquire_batch(adapter, self._pids, last_good, disconnected)
                self.batch.emit(samples, elapsed)
                if disconnected:
                    self.stopped.emit('completed')
                    return
                QThread.msleep(self._interval)
                elapsed += self._interval
        except Exception as error:
            self.stopped.emit(f'failed: {error}')
            return
        finally:
            try:
                adapter.disconnect()
            except Exception:
                pass
            self._running = False
        self.stopped.emit('interrupted' if self._cancelled else 'completed')


class SessionRunner(QObject):
    """GUI-thread coordinator. Owns the QThread and forwards recorder signals."""

    batch = Signal(object, int)
    codes = Signal(object)
    changed = Signal(str)
    finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.recorder = None

    @property
    def active(self):
        return bool(self.thread and self.thread.isRunning())

    def start(self, adapter_factory, pids, interval_ms=100, max_seconds=MAX_SESSION_SECONDS,
              scan_codes=True):
        if self.active:
            raise ValueError('A diagnostic session is already running.')
        self.thread = QThread()
        self.recorder = Recorder(adapter_factory, pids, interval_ms, max_seconds, scan_codes)
        self.recorder.moveToThread(self.thread)
        self.recorder.batch.connect(self.batch)
        self.recorder.codes.connect(self.codes)
        self.recorder.changed.connect(self.changed)
        self.recorder.stopped.connect(self._done)
        self.thread.started.connect(self.recorder.run)
        self.thread.start()

    def _done(self, status):
        self.finished.emit(status)
        if self.thread:
            self.thread.quit()

    def stop(self, wait_ms=3000):
        if self.recorder:
            self.recorder.cancel()
        if self.thread:
            self.thread.quit()
            self.thread.wait(wait_ms)
            self.thread = None
        self.recorder = None

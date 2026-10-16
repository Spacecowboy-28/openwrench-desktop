"""Read-only diagnostic contracts, catalog and shared validation helpers.

The original read-only contract is preserved. Milestone 4 adds a versioned PID
catalog, an explicit sample-status vocabulary and diagnostic-code records, so the
simulator and any future hardware adapter share one vocabulary. No write,
actuation or DTC-clearing command exists anywhere in this module.
"""

from dataclasses import dataclass
from typing import Protocol

# Read-only OBD-II service modes only. Mode 04 (clear DTCs) is deliberately absent.
READ_ONLY_MODES = frozenset({'01', '02', '03', '07', '09', '0A'})
DTC_MODES = frozenset({'03', '07', '0A'})

# pid: (label, unit, minimum, maximum) for the PIDs this application understands.
PID_CATALOG = {
    0x04: ('Calculated engine load', '%', 0.0, 100.0),
    0x05: ('Engine coolant temperature', '\u00b0C', -40.0, 215.0),
    0x0A: ('Fuel pressure', 'kPa', 0.0, 765.0),
    0x0B: ('Intake manifold absolute pressure', 'kPa', 0.0, 255.0),
    0x0C: ('Engine speed', 'rpm', 0.0, 16383.75),
    0x0D: ('Vehicle speed', 'km/h', 0.0, 255.0),
    0x0E: ('Timing advance', '\u00b0', -64.0, 63.5),
    0x0F: ('Intake air temperature', '\u00b0C', -40.0, 215.0),
    0x10: ('Mass air flow rate', 'g/s', 0.0, 655.35),
    0x11: ('Throttle position', '%', 0.0, 100.0),
    0x42: ('Control module voltage', 'V', 0.0, 65.535),
}
PRIMARY_PIDS = (0x0C, 0x05, 0x0D, 0x11, 0x42)
DEFAULT_PIDS = (0x0C, 0x05, 0x0D, 0x11, 0x42, 0x0F, 0x10, 0x0B, 0x0E, 0x04)

SAMPLE_STATUSES = ('ok', 'unsupported', 'stale', 'timeout', 'disconnected')
SESSION_STATUSES = ('running', 'completed', 'interrupted', 'failed')

# Bounds that keep a live session and a restore from exhausting memory or disk.
MAX_SESSION_SECONDS = 300
MAX_SESSION_SAMPLES = 20_000
MAX_RESTORE_SAMPLES = 2_000_000
MAX_RESTORE_SESSIONS = 100_000


def pid_key(pid):
    """Canonical two-hex-digit uppercase key, e.g. 0x0C -> '0C'."""
    value = int(pid, 16) if isinstance(pid, str) else int(pid)
    return f'{value:02X}'


def pid_meta(pid):
    """Return (label, unit, minimum, maximum) or raise for an unknown PID."""
    key = pid_key(pid)
    entry = PID_CATALOG.get(int(key, 16))
    if entry is None:
        raise ValueError(f'Unsupported PID {key}.')
    return entry


@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_id: str
    simulated: bool
    protocol: str | None
    supported_pids: frozenset[str]
    supported_dtc_modes: frozenset[str]


@dataclass(frozen=True)
class SensorSample:
    pid: str
    value: float | None
    unit: str
    timestamp_utc: str
    status: str  # ok, unsupported, stale, timeout, or disconnected


@dataclass(frozen=True)
class DiagnosticCode:
    code: str
    description: str
    status: str  # e.g. Pending, Confirmed, Permanent
    severity: str = ''


class ReadOnlyAdapter(Protocol):
    def connect(self) -> AdapterCapabilities: ...
    def read_codes(self, mode: str) -> tuple[str, ...]: ...
    def read_pid(self, pid: str) -> SensorSample: ...
    def disconnect(self) -> None: ...


def format_sample(sample) -> str:
    """Human-readable value for the UI. Never hides a fault state."""
    if sample.status != 'ok':
        return sample.status
    if sample.value is None:
        return 'unsupported'
    return f'{sample.value:g} {sample.unit}'.strip()

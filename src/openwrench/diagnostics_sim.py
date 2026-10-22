"""Deterministic read-only OBD-II simulator.

Values are produced by a fixed seed and an integer tick, so a scenario replays
identically on any machine. The simulator never claims to describe a real
vehicle; scenarios are labelled and the UI shows them as simulated. No write,
actuation or DTC-clearing command is implemented.
"""

from datetime import datetime, timezone
import random

from openwrench.diagnostics import (
    DEFAULT_PIDS,
    DTC_MODES,
    DiagnosticCode,
    PID_CATALOG,
    READ_ONLY_MODES,
    AdapterCapabilities,
    SensorSample,
    pid_key,
    pid_meta,
)

# scenario -> (label, description)
SCENARIOS = {
    'normal': ('Normal operation', 'Steady idle with a short rev and a brief drive.'),
    'misfire': ('Misfire symptoms', 'Rough idle, unstable RPM and a pending misfire code.'),
    'electrical': ('Electrical / voltage fault', 'Low charging voltage with an intermittent drop-out.'),
    'comms': ('Communication failure', 'The adapter stops responding partway through the session.'),
    'codes': ('Code statuses', 'Stored, pending and permanent codes present together.'),
}

# Communication-failure scenario timeline (in adapter reads): the adapter first
# stops answering (timeouts, reported as stale), then is treated as disconnected.
COMMS_TIMEOUT_AFTER = 40
COMMS_DISCONNECT_AFTER = 45

# Mode -> the human meaning of the response. Kept here so the simulator, the
# hardware adapter and the UI agree on one vocabulary.
MODE_LABELS = {'03': 'Stored', '07': 'Pending', '0A': 'Permanent'}
STATUS_FOR_MODE = {'03': 'Stored', '07': 'Pending', '0A': 'Permanent'}


def matches_mode(status, mode):
    """Whether a code with this status is returned by a read-only DTC mode.

    Mode 03 reports stored (confirmed) codes, mode 07 pending codes and mode 0A
    permanent codes. Permanent codes are also visible in mode 03 on most ECUs.
    """
    if mode == '0A':
        return status == 'Permanent'
    if mode == '07':
        return status == 'Pending'
    return status != 'Pending'



class SimulatorAdapter:
    """Deterministic in-process adapter. Thread-safe because it holds no handles."""

    def __init__(self, scenario='normal', seed=20261016, pids=DEFAULT_PIDS, connect=True):
        if scenario not in SCENARIOS:
            raise ValueError(f'Unknown simulation scenario {scenario!r}.')
        self.scenario = scenario
        self.seed = int(seed)
        self.capabilities = AdapterCapabilities(
            adapter_id='simulator',
            simulated=True,
            protocol='SIM-OBD-II',
            supported_pids=frozenset(pid_key(p) for p in pids),
            supported_dtc_modes=frozenset(DTC_MODES),
        )
        self._connected = bool(connect)
        self._tick = 0

    # -- lifecycle ---------------------------------------------------------
    def connect(self):
        self._connected = True
        self._tick = 0
        return self.capabilities

    def disconnect(self):
        self._connected = False

    @property
    def connected(self):
        return self._connected

    # -- read-only requests ------------------------------------------------
    def read_pid(self, pid):
        key = pid_key(pid)
        now = datetime.now(timezone.utc).isoformat()
        if not self._connected:
            return SensorSample(key, None, self._unit(key), now, 'disconnected')
        if key not in self.capabilities.supported_pids:
            return SensorSample(key, None, self._unit(key), now, 'unsupported')
        value = self.value(key, self._tick)
        self._tick += 1
        if not self._connected:
            # value() may have marked the link dropped during this read.
            return SensorSample(key, None, self._unit(key), now, 'disconnected')
        if value is None:
            return SensorSample(key, None, self._unit(key), now, 'timeout')
        return SensorSample(key, value, self._unit(key), now, 'ok')

    def read_codes(self, mode):
        if mode not in READ_ONLY_MODES or mode not in self.capabilities.supported_dtc_modes:
            raise ValueError('Only read-only diagnostic modes are supported.')
        if not self._connected:
            return ()
        return tuple(c.code for c in self.codes() if matches_mode(c.status, mode))

    def code_details(self, mode):
        """Full code records for a read-only mode (description/basis preserved)."""
        if mode not in READ_ONLY_MODES or mode not in self.capabilities.supported_dtc_modes:
            raise ValueError('Only read-only diagnostic modes are supported.')
        if not self._connected:
            return ()
        return tuple(c for c in self.codes() if matches_mode(c.status, mode))

    def codes(self):
        if self.scenario == 'misfire':
            return (DiagnosticCode('P0301', 'Cylinder 1 misfire detected', 'Pending', 'warning'),
                    DiagnosticCode('P0300', 'Random/multiple cylinder misfire detected', 'Pending', 'warning'))
        if self.scenario == 'electrical':
            return (DiagnosticCode('P0562', 'System voltage low', 'Confirmed', 'warning'),)
        if self.scenario == 'codes':
            return (DiagnosticCode('P0420', 'Catalyst system efficiency below threshold', 'Stored', 'warning'),
                    DiagnosticCode('P0301', 'Cylinder 1 misfire detected', 'Pending', 'warning'),
                    DiagnosticCode('P0455', 'Evaporative emission system leak detected', 'Permanent', 'caution'))
        return ()

    # -- deterministic measurement model -----------------------------------
    @staticmethod
    def _unit(key):
        entry = PID_CATALOG.get(int(key, 16))
        return entry[1] if entry else ''

    def value(self, key, tick):
        """Return a value for a PID at a tick, or None to force a timeout."""
        number = int(key, 16)
        if self.scenario == 'comms' and tick >= COMMS_DISCONNECT_AFTER:
            # The adapter has fully dropped off the bus, so report a dropped link
            # rather than a mere timeout: mark the connection closed.
            self._connected = False
            return None
        if self.scenario == 'comms' and tick >= COMMS_TIMEOUT_AFTER:
            return None  # the adapter "stops responding" but is still connected
        if self.scenario == 'electrical' and number == 0x42:
            # Deterministic dipping charging voltage.
            return round(12.1 + 0.05 * ((tick // 3) % 35), 2)
        rng = random.Random(f'{self.seed}:{self.scenario}:{number}:{tick}')
        if number == 0x0C:
            base = 790 if self.scenario == 'normal' else 640
            jitter = rng.randint(-40, 40) if self.scenario == 'normal' else rng.randint(-160, 160)
            return float(max(0, base + jitter + (900 if tick % 60 in (30, 31, 32) else 0)))
        if number == 0x05:
            base = 88 if self.scenario == 'normal' else 96
            return float(min(215, base + (tick // 5) % 4))
        if number == 0x0D:
            return float(min(120, (tick % 90))) if self.scenario == 'normal' else 0.0
        if number == 0x11:
            return float(rng.randint(0, 22))
        if number == 0x42:
            return round(14.2 - (tick % 11) * 0.01, 2)
        if number in (0x0F,):
            return float(24 + (tick // 7) % 5)
        if number in (0x0B,):
            return float(30 + rng.randint(0, 12))
        if number in (0x0E,):
            return round(rng.uniform(-10, 25), 1)
        if number == 0x10:
            return round(rng.uniform(2.0, 9.0), 2)
        if number == 0x04:
            return float(rng.randint(10, 40))
        if number == 0x0A:
            return round(rng.uniform(280.0, 320.0), 1)
        entry = PID_CATALOG.get(number)
        if entry is None:
            return None
        low, high = entry[2], entry[3]
        return round(low + (high - low) * rng.random(), 2)

"""Read-only ELM327/STN (OBD-II) adapter over a serial transport.

Design points, deliberately conservative:

* Hardware is **optional and disabled by default**. The user must enable it in
  Settings and choose a port; nothing is opened automatically.
* Only read-only OBD-II service modes are ever transmitted. Any other mode -- in
  particular 04 (clear DTCs) -- raises before a byte reaches the port, so the
  application cannot issue an actuation or programming command.
* No claim of real hardware compatibility is made. The protocol layer is unit
  tested with a fake transport; a physical vehicle/adapter is required for real
  acceptance, and none has been performed here.
* The serial library is imported lazily so the rest of the app runs without it.
"""

from datetime import datetime, timezone
import re
import time

from openwrench.diagnostics import (
    DEFAULT_PIDS,
    DTC_MODES,
    PID_CATALOG,
    READ_ONLY_MODES,
    AdapterCapabilities,
    SensorSample,
    pid_key,
)

# Response formulas for the catalog PIDs. Missing entries are unsupported.
_FORMULAS = {
    0x04: lambda a, b: a * 100.0 / 255.0,
    0x05: lambda a, b: a - 40.0,
    0x0A: lambda a, b: a * 3.0,
    0x0B: lambda a, b: float(a),
    0x0C: lambda a, b: (a * 256 + b) / 4.0,
    0x0D: lambda a, b: float(a),
    0x0E: lambda a, b: a / 2.0 - 64.0,
    0x0F: lambda a, b: a - 40.0,
    0x10: lambda a, b: (a * 256 + b) / 100.0,
    0x11: lambda a, b: a * 100.0 / 255.0,
    0x42: lambda a, b: (a * 256 + b) / 1000.0,
}


def decode_dtc(byte_high, byte_low):
    prefix = 'PCBU'[(byte_high >> 6) & 0b11]
    number = ((byte_high & 0x3F) << 8) | byte_low
    return f'{prefix}{number:04X}'


def parse_dtcs(text, mode='03'):
    """Parse mode 03/07/0A data bytes into codes. Tolerates ELM noise lines.

    The first returned byte is the mode with bit 6 set (e.g. 0x43 for mode 03),
    so it is stripped before pairing the remaining bytes.
    """
    clean = re.sub(r'[^0-9A-Fa-f]', '', _strip_echo(text)).upper()
    response = f'{int(str(mode).upper().zfill(2), 16) + 0x40:02X}'
    if clean.startswith(response):
        clean = clean[len(response):]
    if len(clean) < 4:
        return ()
    codes = []
    for index in range(0, len(clean) - 3, 4):
        high, low = int(clean[index:index + 2], 16), int(clean[index + 2:index + 4], 16)
        if high == 0 and low == 0:
            continue  # padding
        codes.append(decode_dtc(high, low))
    return tuple(codes)


def _strip_echo(text):
    """Remove ELM prompt/echo and status lines, joining multi-frame data lines.

    An ELM327 splits long responses across lines (and may echo the request), so
    every data line is concatenated rather than only the first.
    """
    parts = []
    for line in re.split(r'[\r\n]+', text):
        value = line.strip()
        if not value or value == '>':
            continue
        if _is_status_line(value):
            continue
        parts.append(value)
    return ''.join(parts)


def _is_status_line(value):
    upper = value.upper()
    return any(token in upper for token in
               ('SEARCHING', 'NO DATA', 'UNABLE TO CONNECT', 'BUS INIT', 'STOPPED', 'ERROR', '?'))


def parse_pid_response(mode, pid, text):
    """Return data bytes for a Mode 01 response, or () when unavailable."""
    if mode != '01':
        raise ValueError('Only Mode 01 sensor requests are decoded here.')
    clean = re.sub(r'[^0-9A-Fa-f]', '', _strip_echo(text))
    if len(clean) < 4:
        return ()
    expected = f'41{pid_key(pid)}'
    if not clean.upper().startswith(expected):
        return ()
    payload = clean[len(expected):]
    return tuple(int(payload[i:i + 2], 16) for i in range(0, len(payload) - 1, 2))


class UnsupportedRequest(ValueError):
    pass


class ElmAdapter:
    """Read-only adapter. The transport is any object with send()/readline()/close()."""

    def __init__(self, transport, pids=DEFAULT_PIDS, timeout=2.0):
        self.transport = transport
        self.requested_pids = {pid_key(p) for p in pids}
        self.timeout = float(timeout)
        self.capabilities = AdapterCapabilities(
            adapter_id='elm327', simulated=False, protocol=None,
            supported_pids=frozenset(), supported_dtc_modes=frozenset(DTC_MODES))
        self._connected = False

    # -- lifecycle ---------------------------------------------------------
    def connect(self):
        self._reset()
        version = self.query('ATI') or 'ELM/STN'
        protocol = self.query('ATDP') or 'unknown'
        supported = self._negotiate_pids()
        self.capabilities = AdapterCapabilities(
            adapter_id=version.strip()[:40] or 'ELM/STN', simulated=False,
            protocol=protocol.strip()[:40] or None,
            supported_pids=frozenset(supported & self.requested_pids),
            supported_dtc_modes=frozenset(DTC_MODES))
        self._connected = True
        return self.capabilities

    def disconnect(self):
        try:
            self.transport.close()
        finally:
            self._connected = False

    @property
    def connected(self):
        return self._connected

    # -- low-level ---------------------------------------------------------
    def _reset(self):
        self.transport.write(b'ATZ\r')
        time.sleep(0.1)
        self.transport.read_all()
        for command in ('ATE0', 'ATL0', 'ATS0', 'ATH0', 'ATSP0'):
            self.transport.write((command + '\r').encode('ascii'))
            time.sleep(0.05)
            self.transport.read_all()

    def query(self, command, timeout=None):
        """Send a raw AT/OBD command and return the joined text response."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        self.transport.write((command + '\r').encode('ascii'))
        chunks = []
        while time.monotonic() < deadline:
            line = self.transport.readline()
            if line is None:
                time.sleep(0.01)
                continue
            text = line.decode('ascii', 'replace').strip()
            if text.endswith('>') or text == '':
                chunks.append(text.rstrip('>').strip())
                if text.endswith('>'):
                    break
                continue
            chunks.append(text)
        return '\n'.join(c for c in chunks if c)

    # -- read-only requests ------------------------------------------------
    def _request(self, mode, pid=None):
        mode = str(mode).upper().zfill(2)
        if mode not in READ_ONLY_MODES:
            raise UnsupportedRequest('Only read-only diagnostic modes are enabled.')
        command = mode if pid is None else mode + pid_key(pid)
        return self.query(command)

    def read_pid(self, pid):
        key = pid_key(pid)
        now = datetime.now(timezone.utc).isoformat()
        unit = PID_CATALOG.get(int(key, 16), (None, '', 0, 0))[1]
        if not self._connected:
            return SensorSample(key, None, unit, now, 'disconnected')
        if key not in self.capabilities.supported_pids:
            return SensorSample(key, None, unit, now, 'unsupported')
        data = parse_pid_response('01', key, self._request('01', key))
        formula = _FORMULAS.get(int(key, 16))
        if not data or formula is None:
            return SensorSample(key, None, unit, now, 'timeout')
        high = data[0]
        low = data[1] if len(data) > 1 else 0
        return SensorSample(key, round(formula(high, low), 3), unit, now, 'ok')

    def read_codes(self, mode):
        mode = str(mode).upper().zfill(2)
        if mode not in DTC_MODES:
            raise UnsupportedRequest('Only read-only DTC modes 03/07/0A are enabled.')
        return parse_dtcs(self._request(mode), mode)

    def codes(self):
        found = []
        for mode in ('03', '07', '0A'):
            for code in self.read_codes(mode):
                found.append(code)
        return tuple(found)

    def _negotiate_pids(self):
        """Read the 01/20/40/60 support bitmasks and return supported PID keys."""
        supported = set()
        for base in (0x00, 0x20, 0x40, 0x60):
            data = parse_pid_response('01', f'{base:02X}', self._request('01', f'{base:02X}'))
            if len(data) < 4:
                break
            bits = 0
            for byte in data[:4]:
                bits = (bits << 8) | byte
            for offset in range(1, 33):
                if bits & (1 << (32 - offset)):
                    supported.add(f'{base + offset:02X}')
            if not (bits & 1):  # bit 0 marks more PIDs supported
                break
        return supported


class SerialTransport:
    """Thin pyserial wrapper. Imported lazily; hardware stays disabled by default."""

    def __init__(self, port, baudrate=38400, read_timeout=0.2):
        try:
            import serial  # noqa: F401  (pyserial, optional)
        except ImportError as error:  # pragma: no cover - exercised only with hardware
            raise ValueError(
                'The optional serial library is not installed. Install pyserial to use a '
                'USB adapter, or keep using the simulator.') from error
        import serial
        self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=read_timeout)

    def write(self, payload):
        self._serial.write(payload)

    def readline(self):
        return self._serial.readline()

    def read_all(self):
        pending = getattr(self._serial, 'in_waiting', 0)
        return self._serial.read(pending) if pending else b''

    def close(self):
        self._serial.close()


def default_ports():
    """Best-effort port listing. Returns [] when pyserial is unavailable."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]

"""Read-only contracts for milestone 4. No hardware implementation ships yet."""

from dataclasses import dataclass
from typing import Protocol


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
    status: str  # ok, unsupported, timeout, or disconnected


class ReadOnlyAdapter(Protocol):
    def connect(self) -> AdapterCapabilities: ...
    def read_codes(self, mode: str) -> tuple[str, ...]: ...
    def read_pid(self, pid: str) -> SensorSample: ...
    def disconnect(self) -> None: ...

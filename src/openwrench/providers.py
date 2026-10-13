"""Repair-provider contract, independent of vehicle brands and the interface."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VehicleIdentity:
    year: int
    make: str
    model: str
    engine: str | None = None
    trim: str | None = None


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    reference: str
    license: str
    applicability: VehicleIdentity
    verification: str  # unverified or verified


class RepairProvider(Protocol):
    def search(self, vehicle: VehicleIdentity, query: str) -> tuple[SourceRecord, ...]: ...

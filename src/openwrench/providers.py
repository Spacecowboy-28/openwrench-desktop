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
    drivetrain: str | None = None
    transmission: str | None = None
    engine_code: str | None = None


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

# Reference matching is deliberately conservative: no inferred engine/drivetrain.
MATCH_FIELDS = ('year', 'make', 'model', 'engine', 'trim', 'drivetrain', 'transmission', 'engine_code')


def applicability(vehicle, requirement, verified=False):
    supplied = [key for key in MATCH_FIELDS if requirement.get(key) not in ('', None)]
    if not supplied:
        return 'Unknown applicability'
    missing = False
    for key in supplied:
        actual = vehicle.get(key)
        if actual in ('', None):
            missing = True
        elif str(actual).strip().casefold() != str(requirement[key]).strip().casefold():
            return 'Not applicable'
    if missing or not all(requirement.get(k) for k in ('year', 'make', 'model')):
        return 'Partial match'
    if verified and any(not vehicle.get(k) for k in ('engine', 'drivetrain')):
        return 'Partial match'
    return 'Verified applicability' if verified else 'Candidate match'


@dataclass(frozen=True)
class OnlineReference:
    source: str
    title: str
    url: str
    requirements: dict
    content_type: str = 'Manual reference'
    access_method: str = 'External browser'
    availability: str = 'Availability not checked live'
    rights: str = 'Reuse permission unconfirmed; external links only'
    verification: str = 'Third-party information'
    reviewed_at: str = '2026-10-14'
    publication: str = ''


class LemonProvider:
    def references(self, vehicle):
        result = [OnlineReference('LEMON', 'Browse LEMON catalog', 'https://lemon-manuals.la/', {})]
        if (vehicle.get('year'), vehicle.get('make', '').casefold(), vehicle.get('model', '').casefold()) == (2015, 'lexus', 'gs 350'):
            for drive in ('AWD', 'RWD'):
                result.append(OnlineReference('LEMON', f'2015 Lexus GS 350 F Sport {drive}',
                    f'https://lemon-manuals.la/Lexus/2015/GS%20350%20F%20Sport%2C%20{drive}/',
                    dict(year=2015, make='Lexus', model='GS 350', trim='F Sport', drivetrain=drive),
                    availability='Listed in provider catalog; procedure coverage unverified'))
        return result


class CharmProvider:
    def references(self, vehicle):
        result = [OnlineReference('Operation CHARM', 'Browse CHARM catalog', 'https://charm.li/', {},
                                  availability='Intermittent access during research; coverage varies')]
        if (vehicle.get('year'), vehicle.get('make', '').casefold(), vehicle.get('model', '').casefold()) == (2006, 'ford', 'f-150'):
            for drive in ('2WD', '4WD'):
                result.append(OnlineReference('Operation CHARM', f'2006 F-150 4.6L VIN W {drive}',
                    f'https://charm.li/Ford/2006/F%20150%20{drive}%20Pickup%20V8-4.6L%20VIN%20W/',
                    dict(year=2006, make='Ford', model='F-150', engine='4.6L V8', drivetrain=drive, engine_code='VIN W'),
                    availability='Indexed reference; live access intermittent'))
        return result


class NhtsaProvider:
    def references(self, vehicle):
        return [OnlineReference('NHTSA', 'Recalls and manufacturer communications', 'https://www.nhtsa.gov/recalls', {},
                                content_type='Official safety search, not a full service manual', rights='See NHTSA data policy',
                                verification='Official NHTSA portal'),
                OnlineReference('NHTSA', 'Manufacturer communications datasets and publication references',
                    'https://www.nhtsa.gov/nhtsa-datasets-and-apis#manufacturer-communications', {},
                    content_type='Manufacturer communications / TSB references', rights='See NHTSA data policy',
                    verification='Official NHTSA portal')]


class ReferenceProvider(Protocol):
    def references(self, vehicle: dict) -> list[OnlineReference]: ...


PROVIDERS = (LemonProvider(), CharmProvider(), NhtsaProvider())


def online_references(vehicle, providers=PROVIDERS):
    records, errors = [], []
    for provider in providers:
        try:
            records.extend(provider.references(vehicle))
        except Exception as error:
            errors.append(f'{type(provider).__name__} unavailable: {type(error).__name__}')
    return records, errors


def safe_url(value):
    from urllib.parse import urlsplit
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
        raise ValueError('Use a complete HTTPS reference URL without credentials.')
    return value

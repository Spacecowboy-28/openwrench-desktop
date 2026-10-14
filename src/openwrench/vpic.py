"""Explicit, asynchronous NHTSA lookup with bounded requests and local cache."""

from datetime import datetime, timedelta, timezone
import json

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from openwrench.garage import integer, normalize_vin

MAX_BYTES = 1_000_000


def parse_response(payload, vin):
    try:
        rows = payload['Results']
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError
        row = rows[0]
        def field(key):
            value = row.get(key, '')
            if value is None:
                return ''
            if not isinstance(value, (str, int, float)) or len(str(value)) > 4000:
                raise ValueError
            return str(value).strip()
        if field('VIN') and field('VIN').upper() != vin:
            raise ValueError
        codes = field('ErrorCode')
        valid = bool(codes) and all(c.strip() == '0' for c in codes.split(','))
        engine = []
        if field('DisplacementL'):
            engine.append(field('DisplacementL') + ' L')
        if field('EngineCylinders'):
            engine.append(field('EngineCylinders') + ' cylinders')
        if field('EngineConfiguration'):
            engine.append(field('EngineConfiguration'))
        fields = {'year': field('ModelYear'), 'make': field('Make'), 'model': field('Model'),
                  'engine': ', '.join(engine), 'trim': field('Trim')}
        return {'fields': fields, 'valid': valid, 'error_codes': codes,
                'message': field('ErrorText') or 'No decode status supplied by NHTSA.'}
    except (KeyError, TypeError, ValueError):
        raise ValueError('NHTSA returned an invalid response. Manual entry is still available.') from None


class VinLookup(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expired)

    def start(self, vin, year=''):
        self.cancel()
        vin = normalize_vin(vin)
        if not vin:
            raise ValueError('Enter a VIN before requesting a decode.')
        year = integer(year, 'Year', 1886, datetime.now().year + 1) if str(year).strip() else 0
        self.vin, self.year = vin, year
        cached = self.store.connection.execute('SELECT payload,fetched_at FROM vin_cache WHERE vin=? AND model_year=?', (vin, year)).fetchone()
        if cached:
            try:
                fetched = datetime.fromisoformat(cached['fetched_at'])
                if datetime.now(timezone.utc) - timedelta(days=30) <= fetched <= datetime.now(timezone.utc):
                    result = parse_response(json.loads(cached['payload']), vin)
                    result.update(cached=True, fetched_at=cached['fetched_at'])
                    self.completed.emit(result)
                    return
            except (ValueError, TypeError, json.JSONDecodeError):
                pass  # A broken or expired cache never prevents a fresh request.
        url = QUrl(f'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}')
        query = QUrlQuery()
        query.addQueryItem('format', 'json')
        if year:
            query.addQueryItem('modelyear', str(year))
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setTransferTimeout(10000)
        # Never send a VIN to a redirect target, even another HTTPS host.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b'User-Agent', b'OpenWrench/0.2.0')
        self.reply = self.manager.get(request)
        self.reply.finished.connect(self.finish)
        self.reply.downloadProgress.connect(self.progress)
        self.timer.start(15000)

    def progress(self, received, total):
        if received > MAX_BYTES or total > MAX_BYTES:
            self.cancel()
            self.failed.emit('NHTSA response exceeded the size limit. Use manual entry.')

    def expired(self):
        self.cancel()
        self.failed.emit('NHTSA request timed out. Your manual entries are unchanged.')

    def cancel(self):
        self.timer.stop()
        if self.reply is not None:
            reply, self.reply = self.reply, None
            reply.finished.disconnect(self.finish)
            reply.downloadProgress.disconnect(self.progress)
            reply.abort()
            reply.deleteLater()

    def finish(self):
        reply, self.reply = self.reply, None
        self.timer.stop()
        if reply is None:
            return
        reply.downloadProgress.disconnect(self.progress)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError or reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) != 200:
                self.failed.emit('NHTSA is unavailable. Check your connection or enter the vehicle manually.')
                return
            raw = bytes(reply.readAll())
            if len(raw) > MAX_BYTES:
                raise ValueError('NHTSA response exceeded the size limit.')
            payload = json.loads(raw)
            result = parse_response(payload, self.vin)
            fetched_at = datetime.now(timezone.utc).isoformat()
            with self.store.connection:
                self.store.connection.execute('INSERT OR REPLACE INTO vin_cache VALUES (?,?,?,?)',
                                              (self.vin, self.year, json.dumps(payload), fetched_at))
            result.update(cached=False, fetched_at=fetched_at)
            self.completed.emit(result)
        except (ValueError, UnicodeError):
            self.failed.emit('NHTSA returned unreadable data. Your manual entries are unchanged.')
        except Exception:
            # Do not log network errors or response contents containing VINs.
            self.failed.emit('Unable to save the decode result. Use manual entry and check local storage.')
        finally:
            reply.deleteLater()

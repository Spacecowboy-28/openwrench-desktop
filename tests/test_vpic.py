from datetime import datetime, timezone
import json

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

from openwrench.storage import Store
from openwrench.vpic import VinLookup, parse_response

VIN = 'TEST0000000000001'


def payload(**changes):
    return {'Results': [dict(VIN=VIN, ModelYear='2001', Make='TOYOTA',Model='Tundra',ErrorCode='0', ErrorText='Decoded', **changes)]}


def test_parser_keeps_unknown_fields_blank():
    result = parse_response(payload(),VIN)
    assert result['valid']
    assert result['fields']['engine'] == ''
    assert result['fields']['trim'] == ''


def test_partial_decode_is_not_approved():
    data = payload()
    data['Results'][0].update(ErrorCode='1,14',ErrorText='VIN errors')
    result = parse_response(data,VIN)
    assert not result['valid']
    assert result['error_codes'] == '1,14'
    assert result['message'] == 'VIN errors'


@pytest.mark.parametrize('data',[{}, {'Results':[]},{'Results':['bad']},{'Results':[{'VIN':'OTHER'}]}, {'Results':[{'Make':[]}]}])
def test_malformed_response(data):
    with pytest.raises(ValueError):
        parse_response(data,VIN)


class FakeReply(QObject):
    finished = Signal()
    downloadProgress = Signal(int,int)
    def __init__(self, body, status=200, error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.body, self.status, self.err = body, status, error
        self.aborted = False
    def error(self): return self.err
    def attribute(self,key): return self.status
    def readAll(self): return self.body
    def abort(self): self.aborted=True


class FakeManager:
    def __init__(self,reply): self.reply=reply
    def get(self,request): self.request=request; return self.reply


@pytest.fixture
def lookup(app,tmp_path):
    store=Store(tmp_path/'app.sqlite3')
    instance=VinLookup(store)
    yield instance
    instance.cancel()
    store.close()


def test_request_result_and_cache_work_offline(lookup):
    reply=FakeReply(json.dumps(payload()).encode())
    manager=FakeManager(reply)
    lookup.manager=manager
    results=[]
    lookup.completed.connect(results.append)
    lookup.start(VIN,'2001')
    assert manager.request.url().host() == 'vpic.nhtsa.dot.gov'
    assert 'modelyear=2001' in manager.request.url().query()
    reply.finished.emit()
    assert results[0]['cached'] is False
    lookup.manager=None  # A fresh cache does not need any network manager.
    lookup.start(VIN,'2001')
    assert results[1]['cached'] is True


@pytest.mark.parametrize('status,error',[(503,QNetworkReply.NetworkError.NoError),(302,QNetworkReply.NetworkError.NoError),(0,QNetworkReply.NetworkError.HostNotFoundError)])
def test_network_and_http_errors_leave_manual_entry_available(lookup,status,error):
    reply=FakeReply(b'',status,error)
    lookup.manager=FakeManager(reply)
    errors=[]
    lookup.failed.connect(errors.append)
    lookup.start(VIN)
    reply.finished.emit()
    assert errors and lookup.reply is None
    assert lookup.store.connection.execute('SELECT COUNT(*) FROM vin_cache').fetchone()[0] == 0


def test_deadline_cancels_without_late_result(lookup):
    reply=FakeReply(json.dumps(payload()).encode())
    lookup.manager=FakeManager(reply)
    errors,results=[],[]
    lookup.failed.connect(errors.append)
    lookup.completed.connect(results.append)
    lookup.start(VIN)
    lookup.expired()
    reply.finished.emit()
    assert reply.aborted and errors and not results


def test_invalid_json(lookup):
    reply=FakeReply(b'not json')
    lookup.manager=FakeManager(reply)
    errors=[]
    lookup.failed.connect(errors.append)
    lookup.start(VIN)
    reply.finished.emit()
    assert errors


def test_expired_cache_and_oversized_response(lookup):
    with lookup.store.connection:
        lookup.store.connection.execute('INSERT INTO vin_cache VALUES (?,?,?,?)',(VIN,0,json.dumps(payload()),'2000-01-01T00:00:00+00:00'))
    reply=FakeReply(b'')
    lookup.manager=FakeManager(reply)
    errors=[]
    lookup.failed.connect(errors.append)
    lookup.start(VIN)
    assert lookup.reply is reply
    reply.downloadProgress.emit(1000001,1000001)
    assert reply.aborted and errors and lookup.reply is None

"""Explicit NHTSA year/make/model recall requests. No VIN or bulk lookups."""
import json
import re
from urllib.parse import urlencode
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply


def parse_recalls(content):
    if len(content)>2_000_000:raise ValueError('NHTSA response exceeds 2 MB.')
    data=json.loads(content)
    if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise ValueError('Unexpected NHTSA response.')
    rows=[]
    for result in data['results']:
        if not isinstance(result,dict):raise ValueError('Invalid NHTSA record.')
        campaign=result.get('NHTSACampaignNumber','')
        if not isinstance(campaign,str) or not re.fullmatch('[A-Za-z0-9-]{1,30}',campaign):raise ValueError('Invalid campaign identifier.')
        row=dict(campaign=campaign)
        for target,source in [('date','ReportReceivedDate'),('component','Component'),('summary','Summary')]:
            value=result.get(source,'')
            if not isinstance(value,str) or len(value)>100000:raise ValueError('Invalid recall field.')
            row[target]=value
        rows.append(row)
    return rows


class RecallClient(QObject):
    completed=Signal(object,str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.manager=QNetworkAccessManager(self)
        self.reply=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.timeout)
        self.content=bytearray()

    def fetch(self,vehicle):
        self.cancel()
        url='https://api.nhtsa.gov/recalls/recallsByVehicle?'+urlencode(dict(make=vehicle['make'],model=vehicle['model'],modelYear=vehicle['year']))
        request=QNetworkRequest(QUrl(url));request.setTransferTimeout(10000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        self.reply=self.manager.get(request);reply=self.reply
        self.content=bytearray()
        reply.readyRead.connect(lambda:self.read(reply));reply.finished.connect(lambda:self.finish(reply));self.timer.start(15000)

    def read(self,reply):
        if reply is not self.reply:return
        self.content.extend(bytes(reply.readAll()))
        if len(self.content)>2_000_000:
            self.cancel();self.completed.emit([],'NHTSA response exceeds 2 MB.')

    def finish(self,reply):
        if reply is not self.reply:return
        self.read(reply)
        if reply is not self.reply:return
        self.timer.stop();self.reply=None
        try:
            status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error()!=QNetworkReply.NetworkError.NoError or status!=200:
                raise ValueError('NHTSA unavailable. Check your connection or use the official browser link.')
            rows=parse_recalls(bytes(self.content))
            self.completed.emit(rows,'' if rows else 'NHTSA returned no records for this query. This does not establish VIN recall status.')
        except (ValueError,TypeError) as exc:self.completed.emit([],str(exc))
        finally:reply.deleteLater()

    def cancel(self):
        self.timer.stop()
        if self.reply:
            reply,self.reply=self.reply,None
            reply.abort();reply.deleteLater()

    def timeout(self):
        self.cancel();self.completed.emit([],'NHTSA request timed out. Local documents remain available.')

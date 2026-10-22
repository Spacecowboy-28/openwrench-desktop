"""QProcess jobs isolate PDF parsing/rendering and permit bounded cancellation."""
import json
from pathlib import Path
import sys
import tempfile
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class DocumentTask(QObject):
    progress = Signal(int,int)
    finished = Signal(object,str)

    def __init__(self,store,operation,parameters,parent=None):
        super().__init__(parent)
        self.temporary = tempfile.TemporaryDirectory(prefix='openwrench-pdf-')
        self.directory = Path(self.temporary.name)
        self.job = dict(parameters,database=str(store.path),operation=operation,output=str(self.directory/'render.raw'))
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.complete)
        self.process.errorOccurred.connect(self.failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda:self.cancel('Document operation timed out.'))
        self.buffer,self.result,self.error,self.done,self.bundle,self.notice = '',None,'',False,None,None

    def start(self):
        file=self.directory/'job.json'
        file.write_text(json.dumps(self.job),'utf-8')
        args=['--pdf-worker',str(file)] if getattr(sys,'frozen',False) else ['-m','openwrench.pdf_worker',str(file)]
        # Rendering one page is quick; indexing/materializing a large manual is not,
        # so only 'render' keeps the short bound.
        self.timer.start(30000 if self.job['operation']=='render' else 600000)
        self.process.start(sys.executable,args)

    def read_output(self):
        self.buffer+=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            try:
                value=json.loads(line)
                if 'progress' in value:self.progress.emit(value['progress'],value['total'])
                if 'result' in value:self.result=value['result']
                if 'bundle' in value:self.bundle=value['bundle']
                if 'notice' in value:self.notice=value['notice']
                if 'error' in value:self.error=value['error']
            except (ValueError,TypeError):
                self.error='Invalid document worker response.'

    def failed(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.error='Unable to start document worker.'
            self.complete(-1)

    def cancel(self,message='Document operation cancelled. Any committed import remains in the library.'):
        if self.done:return
        self.error=message
        self.process.kill()
        self.process.waitForFinished(1500)
        if not self.done:self.complete(-1)

    def complete(self,code=0,*args):
        if self.done:return
        self.read_output()
        self.done=True
        self.timer.stop()
        error=self.error or ('Document worker failed. Existing records were preserved.' if code or self.result is None else '')
        self.finished.emit(self.result,error)
        self.temporary.cleanup()

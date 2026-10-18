"""Static QTextBrowser viewer. All resource loading is denied unless explicitly allowed."""
from pathlib import PurePosixPath
from urllib.parse import unquote
from PySide6.QtCore import QUrl, QByteArray, QSize
from PySide6.QtGui import QImage, QImageReader, QPainter, QTextDocument
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QTextBrowser,QComboBox
from openwrench.html_bundle import StaticHTML, safe_path, safe_svg, read_bundle_dir, HTML, TRUNCATED
from openwrench.library_tasks import DocumentTask


class OfflineBrowser(QTextBrowser):
    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
    def doSetSource(self, url, resource_type=QTextDocument.ResourceType.UnknownResource):
        # QTextBrowser's default file/qrc fallback must never run.
        return
    def loadResource(self, resource_type, url):
        if resource_type != QTextDocument.ResourceType.ImageResource or url.scheme() != 'bundle' or url.host():
            return QByteArray()
        try:
            name = safe_path(unquote(url.path().lstrip('/')))
            data = self.files.get(name)
            if data is None: return QByteArray()
            if name.lower().endswith('.svg'):
                renderer = QSvgRenderer(QByteArray(safe_svg(data)))
                size = renderer.defaultSize()
                if not renderer.isValid() or size.isEmpty() or size.width()*size.height()>16000000:
                    return QByteArray()
                image = QImage(size,QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                return image
            if PurePosixPath(name).suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.bmp','.ico','.webp'):
                return QByteArray()
            buffer = QBuffer()
            buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            format_name = PurePosixPath(name).suffix.lower().lstrip('.')
            if format_name == 'jpg': format_name = 'jpeg'
            reader = QImageReader(buffer,QByteArray(format_name.encode('ascii')))
            reader.setAutoDetectImageFormat(False)
            size = reader.size()
            if size.isEmpty() or size.width()*size.height()>16000000: return QByteArray()
            return reader.read()
        except Exception:
            # Malformed user images are unavailable resources, never fallback URLs.
            return QByteArray()


class HtmlViewer(QDialog):
    # Rendered pages are cached so Back/Forward/Home and anchor jumps do not
    # re-parse. The cache is dropped whole once it exceeds the budget, which
    # keeps memory bounded for very large manuals at the cost of a re-parse.
    RENDER_CACHE_BYTES = 32 * 1024 * 1024

    def __init__(self, library, identifier, page=1, parent=None):
        super().__init__(parent)
        self.library,self.identifier = library,identifier
        self.doc = library.document(identifier)
        self.sections = library.html_sections(identifier)
        self.history,self.position = [],-1
        self.current = None
        self.rendered = {}
        self.rendered_bytes = 0
        self.setWindowTitle(self.doc['title']+' — Offline HTML')
        self.resize(1000,750)
        layout = QVBoxLayout(self);bar = QHBoxLayout();layout.addLayout(bar)
        self.browser = OfflineBrowser({},self)
        self.status = QLabel('Loading validated bundle…');self.status.setWordWrap(True)
        self.location = QComboBox()
        for row in self.sections:
            self.location.addItem(f"{row['page']}: {row['path']}"+(f" #{row['anchor']}" if row['anchor'] else ''),row)
        self.location.activated.connect(lambda index:self.navigate(self.sections[index]['path'],self.sections[index]['anchor']))
        for label,callback in [('Back',lambda:self.move(-1)),('Forward',lambda:self.move(1)),('Home',lambda:self.show_section(1)),
                               ('Zoom +',lambda:self.browser.zoomIn(1)),('Zoom −',lambda:self.browser.zoomOut(1)),('Bookmark',self.bookmark)]:
            button=QPushButton(label);button.clicked.connect(callback);bar.addWidget(button)
        layout.addWidget(self.location);layout.addWidget(self.status);layout.addWidget(self.browser,1)
        self.browser.anchorClicked.connect(self.follow)
        self.task = DocumentTask(library.store,'materialize',dict(id=identifier),self)
        def loaded(result,message):
            if message:self.status.setText(message);return
            try:
                # The worker already read and inspected the validated bundle, so
                # only the cheap directory load happens here on the GUI thread.
                bundle = self.task.bundle or {}
                root = bundle.get('root') or (result.get('root') if isinstance(result,dict) else result)
                self.browser.files = read_bundle_dir(root)
                issues = result.get('issues',[]) if isinstance(result,dict) else []
                self.report = issues
                truncated = any(i['reason']==TRUNCATED for i in issues)
                shown = sum(1 for i in issues if i['reason']!=TRUNCATED)
                self.status.setText((f'{shown}+' if truncated else f'{shown}')+' missing/blocked references. Completeness is not guaranteed. Scripts disabled; static layout only.')
                self.status.setToolTip('\n'.join(f"{r['page']}: {r['reason']} — {r['reference']}" for r in issues))
                report = QPushButton('Resource report',self)
                bar.addWidget(report)
                report.clicked.connect(self.show_report)
                self.show_section(page)
            except (ValueError,OSError) as error:self.status.setText(str(error))
        self.task.finished.connect(loaded);self.task.start()
    def show_report(self):
        dialog=QDialog(self);dialog.setWindowTitle('Resource report');dialog.resize(800,500)
        layout=QVBoxLayout(dialog);view=QTextBrowser(dialog)
        view.setPlainText('Static references only. Missing script-generated pages cannot be detected.\n\n'+'\n'.join(f"{r['page']}: {r['reason']} — {r['reference']}" for r in self.report))
        layout.addWidget(view);dialog.exec()
    def show_section(self,page):
        row=self.sections[max(0,min(page-1,len(self.sections)-1))]
        self.navigate(row['path'],row['anchor'])
    def navigate(self,path,anchor='',record=True):
        if path not in self.browser.files or PurePosixPath(path).suffix.lower() not in HTML:
            self.status.setText('Missing or unsupported internal document: '+path);return
        if not self.current or self.current[0]!=path:
            html = self.rendered.get(path)
            if html is None:
                parsed=StaticHTML(path,self.browser.files)
                html=''.join(parsed.output)
                if len(html) > self.RENDER_CACHE_BYTES or self.rendered_bytes+len(html) > self.RENDER_CACHE_BYTES:
                    self.rendered.clear();self.rendered_bytes=0
                if len(html) <= self.RENDER_CACHE_BYTES:
                    self.rendered[path]=html;self.rendered_bytes+=len(html)
            self.browser.setHtml(html)
        self.browser.scrollToAnchor(anchor)
        self.current=(path,anchor)
        if record:
            self.history=self.history[:self.position+1]+[self.current];self.position=len(self.history)-1
        matching=[(n,r) for n,r in enumerate(self.sections) if r['path']==path]
        selected=next((n for n,r in matching if r['anchor']==anchor),matching[0][0])
        self.location.setCurrentIndex(selected)
    def follow(self,url):
        if url.scheme()!='bundle' or url.host():
            self.status.setText('External navigation blocked.');return
        try:self.navigate(safe_path(unquote(url.path().lstrip('/'))),url.fragment())
        except ValueError as error:self.status.setText(str(error))
    def move(self,delta):
        target=self.position+delta
        if 0<=target<len(self.history):
            self.position=target;self.navigate(*self.history[target],record=False)
    def bookmark(self):
        if self.current:
            row=self.location.currentData()
            self.library.bookmark(self.doc['title']+' — '+row['path'],document_id=self.identifier,page=row['page'],source=self.doc['source'])
            self.status.setText('Section bookmarked.')
    def reject(self):
        self.task.cancel();super().reject()
    def closeEvent(self,event):
        self.task.cancel();super().closeEvent(event)

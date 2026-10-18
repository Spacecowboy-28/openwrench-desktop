"""Native document library, provenance forms, PDF viewer and maintenance controls."""
from datetime import date
import json
import sqlite3
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,
    QLabel,QPushButton,QComboBox,QLineEdit,QListWidget,QListWidgetItem,QDialogButtonBox,
    QMessageBox,QFileDialog,QTabWidget,QCheckBox,QSpinBox,QGraphicsView,QGraphicsScene,QProgressBar,QScrollArea)
from openwrench.garage import Garage
from openwrench.library import Library,VERIFICATIONS
from openwrench.library_schema import CATEGORIES
from openwrench.library_tasks import DocumentTask
from openwrench.maintenance import Maintenance
from openwrench.providers import MATCH_FIELDS,applicability,online_references,safe_url


def plain(value):
    widget=QLabel(value)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def error(parent,message):
    QMessageBox.critical(parent,'Repair Library',str(message))


def open_url(parent,url):
    try:
        safe_url(url)
        if not QDesktopServices.openUrl(QUrl(url)):
            raise ValueError('No browser opened. Check your default browser and connection.')
    except ValueError as exc:error(parent,exc)


class FieldsDialog(QDialog):
    def __init__(self,title,parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680,680)
        self.outer=QVBoxLayout(self)
        self.scroll=QScrollArea()
        self.scroll.setWidgetResizable(True)
        page=QWidget()
        self.form=QFormLayout(page)
        self.scroll.setWidget(page)
        self.outer.addWidget(self.scroll)
        self.fields={}
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.outer.addWidget(self.buttons)

    def field(self,key,label,value='',choices=None):
        widget=QComboBox() if choices is not None else QLineEdit()
        if choices is not None:
            widget.addItems(choices)
            widget.setCurrentText(str(value))
        else:widget.setText(str(value or ''))
        widget.setAccessibleName(label)
        self.form.addRow(label,widget)
        self.fields[key]=widget
        return widget

    def values(self):
        return {key:(w.currentText() if isinstance(w,QComboBox) else w.text()) for key,w in self.fields.items()}

    def configuration_fields(self,values):
        for key in MATCH_FIELDS:
            self.field('match_'+key,'Applicability: '+key.replace('_',' '),values.get(key,''))

    def configuration(self,values):
        result={key:values.pop('match_'+key) for key in MATCH_FIELDS}
        result={k:v for k,v in result.items() if v.strip()}
        if result.get('year'):result['year']=int(result['year'])
        return result


class DocumentDialog(FieldsDialog):
    def __init__(self,library,selected=None,document=None,parent=None):
        super().__init__('Document details and vehicle associations',parent)
        self.library=library
        d=document or dict(category=CATEGORIES[0],rights='User supplied; redistribution not authorized',
                           verification=VERIFICATIONS[0],reviewed_at=date.today().isoformat(),document_type='Service manual')
        self.form.addRow(plain('Import only documents you have permission to use. Vehicle associations are personal links, not factory verification.'))
        for key in ('title','description','source','publisher','publication_date','rights','reviewed_at','document_type'):
            self.field(key,key.replace('_',' ').capitalize(),d.get(key,''))
        self.field('category','Category',d.get('category'),CATEGORIES)
        self.field('verification','Verification',d.get('verification'),VERIFICATIONS)
        self.configuration_fields(json.loads(d.get('applicability','{}')))
        self.vehicles=QListWidget()
        associated=library.associations(d['id']) if d.get('id') else [selected]
        for vehicle in Garage(library.store).vehicles():
            item=QListWidgetItem(vehicle['nickname'])
            item.setData(Qt.ItemDataRole.UserRole,vehicle['id'])
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if vehicle['id'] in associated else Qt.CheckState.Unchecked)
            self.vehicles.addItem(item)
        self.form.addRow('Associate vehicles',self.vehicles)
        self.payload=None

    def accept(self):
        from openwrench.library import metadata
        try:
            values=self.values()
            values['applicability']=self.configuration(values)
            metadata(values)
            vehicles=[self.vehicles.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.vehicles.count())
                      if self.vehicles.item(i).checkState()==Qt.CheckState.Checked]
            self.payload=(values,vehicles)
        except (ValueError,TypeError) as exc:
            error(self,exc);return
        super().accept()


class PdfViewer(QDialog):
    def __init__(self,library,identifier,page=1,parent=None):
        super().__init__(parent)
        self.library,self.identifier=library,identifier
        self.setWindowTitle(library.document(identifier)['title'])
        self.resize(900,720)
        layout=QVBoxLayout(self)
        controls=QHBoxLayout()
        self.page=QSpinBox();self.page.setRange(1,library.document(identifier)['page_count']);self.page.setValue(page)
        self.page.setAccessibleName('PDF page')
        self.zoom=QComboBox();self.zoom.addItems(['50%','100%','150%','200%','300%','400%']);self.zoom.setCurrentText('100%')
        controls.addWidget(plain('Page'));controls.addWidget(self.page);controls.addWidget(plain('Zoom'));controls.addWidget(self.zoom)
        bookmark=QPushButton('Bookmark page');bookmark.clicked.connect(self.bookmark)
        controls.addWidget(bookmark)
        external=QPushButton('Open in system viewer');external.clicked.connect(self.external)
        controls.addWidget(external)
        layout.addLayout(controls)
        self.find=QLineEdit();self.find.setPlaceholderText('Find extracted text in this document, then press Enter')
        self.find.returnPressed.connect(self.search);layout.addWidget(self.find)
        self.hits=QComboBox();self.hits.activated.connect(lambda index:self.page.setValue(self.hits.itemData(index)));layout.addWidget(self.hits)
        self.status=plain('Drag the page to pan.');layout.addWidget(self.status)
        self.scene=QGraphicsScene(self);self.view=QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag);layout.addWidget(self.view,1)
        self.task=None
        self.page.valueChanged.connect(self.render);self.zoom.currentIndexChanged.connect(self.render)
        self.render()

    def render(self,*args):
        if self.task and not self.task.done:self.task.cancel()
        self.task=DocumentTask(self.library.store,'render',dict(id=self.identifier,page=self.page.value(),scale=int(self.zoom.currentText()[:-1])/100),self)
        task=self.task
        def complete(result,message):
            if self.task is not task:return
            if message:self.status.setText(message);return
            content=Path(task.job['output']).read_bytes()
            image=QImage(content,result['width'],result['height'],result['stride'],QImage.Format.Format_ARGB32).copy()
            self.scene.clear();self.scene.addPixmap(QPixmap.fromImage(image));self.scene.setSceneRect(self.scene.itemsBoundingRect())
            self.status.setText('Drag the page to pan. Text search uses the local index.')
        task.finished.connect(complete);task.start()

    def search(self):
        self.hits.clear()
        for row in self.library.search(self.find.text(),document_id=self.identifier):
            self.hits.addItem(f"Page {row['page']}: {row['excerpt']}",row['page'])
        if self.hits.count():self.page.setValue(self.hits.currentData())
        else:self.status.setText('No indexed text matches. Scanned pages need OCR, which is not included.')

    def bookmark(self):
        self.library.bookmark(self.windowTitle(),document_id=self.identifier,page=self.page.value(),source='Local document')
        self.status.setText('Page bookmarked.')

    def external(self):
        if self.task and not self.task.done:self.task.cancel()
        self.task=DocumentTask(self.library.store,'materialize',dict(id=self.identifier),self)
        def opened(result,message):
            if message:error(self,message);return
            root=result.get('root') if isinstance(result,dict) else result
            QDesktopServices.openUrl(QUrl.fromLocalFile(root))
        self.task.finished.connect(opened)
        self.task.start()

    def reject(self):
        if self.task and not self.task.done:self.task.cancel()
        super().reject()

    def closeEvent(self,event):
        if self.task and not self.task.done:self.task.cancel()
        super().closeEvent(event)


class ScheduleDialog(FieldsDialog):
    def __init__(self,library,vehicle_id,row=None,parent=None):
        super().__init__('Maintenance schedule',parent)
        self.library,self.vehicle_id=library,vehicle_id
        self.original=row or {}
        self.form.addRow(plain('No factory intervals are preloaded. Enter your own schedule or cite a manufacturer publication you verified. Due dates need a completion record or baseline.'))
        for key,label in [('title','Service name'),('distance_interval','Distance interval'),('months_interval','Month interval'),
                          ('source','Original source'),('publication','Publication / page reference'),('publisher','Publisher'),
                          ('publication_date','Publication date (if known)'),('rights','Usage rights'),('reviewed_at','Last reviewed (YYYY-MM-DD)'),('conditions','Severe-service conditions'),
                          ('specification','Verified fluid / part specification'),('baseline_date','Baseline date (YYYY-MM-DD)'),('baseline_odometer','Baseline odometer')]:
            self.field(key,label,self.original.get(key,''))
        self.field('origin','Schedule source',self.original.get('origin','User-defined'),['User-defined','Manufacturer source (user verified)'])
        self.field('unit','Distance unit',self.original.get('unit',library.vehicle(vehicle_id)['unit']),['mi','km'])
        self.configuration_fields(json.loads(self.original.get('applicability','{}')))
        self.entry=QComboBox();self.entry.addItem('Use explicit baseline',None)
        for row in Garage(library.store).entries(vehicle_id):
            if row['kind']=='service':self.entry.addItem(f"{row['date']} · {row['title']}",row['id'])
        self.entry.setCurrentIndex(max(0,self.entry.findData(self.original.get('last_entry_id'))))
        self.form.addRow('Last completed service',self.entry)
        self.procedure=QComboBox();self.procedure.addItem('No procedure linked',None)
        for doc in library.documents():self.procedure.addItem(doc['title'],doc['id'])
        self.procedure.setCurrentIndex(max(0,self.procedure.findData(self.original.get('procedure_id'))))
        self.form.addRow('Procedure document',self.procedure)
        self.reminder=QCheckBox('Show due reminder in Repair Library');self.reminder.setChecked(bool(self.original.get('reminder',True)))
        self.form.addRow(self.reminder)

    def accept(self):
        try:
            values=self.values();values['applicability']=self.configuration(values)
            values.update(vehicle_id=self.vehicle_id,last_entry_id=self.entry.currentData(),procedure_id=self.procedure.currentData(),reminder=self.reminder.isChecked())
            Maintenance(self.library.store).save(values,self.original.get('id'))
        except (ValueError,sqlite3.Error) as exc:error(self,exc);return
        super().accept()


class RepairLibraryPage(QWidget):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store,self.library=store,Library(store)
        self.task=None
        self.viewers=[]
        layout=QVBoxLayout(self)
        layout.setContentsMargins(24,24,24,24)
        heading=plain('Repair Library');heading.setObjectName('title');layout.addWidget(heading)
        row=QHBoxLayout()
        self.vehicle=QComboBox();self.vehicle.setAccessibleName('Repair Library vehicle')
        row.addWidget(self.vehicle,1)
        configure=QPushButton('Vehicle configuration');configure.clicked.connect(self.configure);row.addWidget(configure)
        refresh=QPushButton('Refresh');refresh.clicked.connect(self.refresh);row.addWidget(refresh)
        layout.addLayout(row)
        self.reminders=plain('');layout.addWidget(self.reminders)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.local=QWidget();local_layout=QVBoxLayout(self.local);self.tabs.addTab(self.local,'Local manuals')
        filters=QHBoxLayout()
        self.query=QLineEdit();self.query.setPlaceholderText('Search title or repair term, then press Enter')
        self.query.setAccessibleName('Repair document search');self.query.returnPressed.connect(self.reload)
        filters.addWidget(self.query,1)
        self.category=QComboBox();self.category.addItems(['All categories',*CATEGORIES]);self.category.currentIndexChanged.connect(self.reload)
        filters.addWidget(self.category)
        self.all_documents=QCheckBox('All vehicles');self.all_documents.toggled.connect(self.reload);filters.addWidget(self.all_documents)
        local_layout.addLayout(filters)
        self.documents=QListWidget();self.documents.currentItemChanged.connect(self.details);self.documents.itemDoubleClicked.connect(self.open_document)
        local_layout.addWidget(self.documents,1)
        self.detail=plain('Import a lawful PDF to begin. No repair specifications are preloaded.');local_layout.addWidget(self.detail)
        actions=QGridLayout();self.document_buttons=[]
        for index,(title,callback) in enumerate([('Import PDF / HTML / ZIP',self.import_pdf),('Open document',self.open_document),('Edit details / vehicles',self.edit_document),
            ('Rebuild index',self.reindex),('Locate original',self.locate),('Remove document',self.delete_document)]):
            button=QPushButton(title);button.clicked.connect(callback);actions.addWidget(button,index//3,index%3);self.document_buttons.append(button)
        local_layout.addLayout(actions)
        online=QWidget();online_layout=QVBoxLayout(online);self.tabs.addTab(online,'Online sources')
        online_layout.addWidget(plain('Browser links require internet. Listed references do not prove procedure applicability. Confirm engine, drivetrain and transmission before use.'))
        self.sources=QListWidget();self.sources.currentItemChanged.connect(self.source_details);online_layout.addWidget(self.sources,1)
        self.source_detail=plain('');online_layout.addWidget(self.source_detail)
        actions=QHBoxLayout()
        for title,callback in [('Open source',self.open_source),('Bookmark reference',self.bookmark_source),('Fetch NHTSA recalls',self.fetch_recalls)]:
            button=QPushButton(title);button.clicked.connect(callback);actions.addWidget(button)
        online_layout.addLayout(actions)
        self.recall_status=plain('NHTSA requests send only selected year/make/model, never your VIN.');online_layout.addWidget(self.recall_status)
        self.recalls=QListWidget();self.recalls.setMaximumHeight(140);self.recalls.itemDoubleClicked.connect(self.open_recall);online_layout.addWidget(self.recalls)
        bookmarks=QWidget();bookmark_layout=QVBoxLayout(bookmarks);self.tabs.addTab(bookmarks,'Bookmarks')
        self.bookmarks=QListWidget();bookmark_layout.addWidget(self.bookmarks)
        actions=QHBoxLayout()
        for title,callback in [('Open bookmark',self.open_bookmark),('Remove bookmark',self.delete_bookmark)]:
            button=QPushButton(title);button.clicked.connect(callback);actions.addWidget(button)
        bookmark_layout.addLayout(actions)
        maintenance=QWidget();maintenance_layout=QVBoxLayout(maintenance);self.tabs.addTab(maintenance,'Maintenance')
        maintenance_layout.addWidget(plain('Factory schedule coverage is empty until you supply a verified publication. User-defined reminders use your Garage readings and explicitly linked service records.'))
        self.schedules=QListWidget();maintenance_layout.addWidget(self.schedules,1)
        self.schedule_detail=plain('');maintenance_layout.addWidget(self.schedule_detail)
        self.schedules.currentItemChanged.connect(self.show_schedule)
        actions=QHBoxLayout()
        for title,callback in [('Add schedule',self.add_schedule),('Edit / record completion',self.edit_schedule),('Open procedure',self.open_procedure),('Delete schedule',self.delete_schedule)]:
            button=QPushButton(title);button.clicked.connect(callback);actions.addWidget(button)
        maintenance_layout.addLayout(actions)
        self.status=plain('Ready');layout.addWidget(self.status)
        progress=QHBoxLayout();self.progress=QProgressBar();self.progress.hide();progress.addWidget(self.progress)
        self.cancel=QPushButton('Cancel document task');self.cancel.hide();self.cancel.clicked.connect(lambda:self.task.cancel() if self.task else None);progress.addWidget(self.cancel)
        layout.addLayout(progress)
        from openwrench.recalls import RecallClient
        self.recall_client=RecallClient(self)
        self.recall_client.completed.connect(self.got_recalls)
        self.vehicle.currentIndexChanged.connect(self.changed_vehicle)
        self.tabs.currentChanged.connect(lambda _:self.reload_bookmarks())
        self.refresh()

    @property
    def busy(self):
        return bool(self.task and not self.task.done)

    def refresh(self,selected=None):
        current=selected or self.vehicle.currentData()
        self.vehicle.blockSignals(True);self.vehicle.clear()
        for vehicle in Garage(self.store).vehicles():self.vehicle.addItem(vehicle['nickname'],vehicle['id'])
        self.vehicle.setCurrentIndex(max(0,self.vehicle.findData(current)))
        self.vehicle.blockSignals(False)
        self.changed_vehicle()

    def changed_vehicle(self,*args):
        self.recall_client.cancel()
        self.recalls.clear()
        self.reload()
        self.sources.clear()
        identifier=self.vehicle.currentData()
        refs,errors=online_references(self.library.vehicle(identifier) if identifier else {})
        for ref in refs:
            item=QListWidgetItem(ref.source+' · '+ref.title);item.setData(Qt.ItemDataRole.UserRole,ref);self.sources.addItem(item)
        if errors:self.status.setText('\n'.join(errors))
        if self.sources.count():self.sources.setCurrentRow(0)
        self.reload_schedules();self.reload_bookmarks()

    def configure(self):
        identifier=self.vehicle.currentData()
        if not identifier:return
        vehicle=self.library.vehicle(identifier)
        dialog=FieldsDialog('Vehicle configuration',self)
        dialog.form.addRow(plain('Leave unknown values blank. These fields do not change the Garage engine or trim.'))
        for key in ('drivetrain','transmission','engine_code'):dialog.field(key,key.replace('_',' ').capitalize(),vehicle.get(key,''))
        if dialog.exec():
            try:self.library.configure(identifier,**dialog.values());self.changed_vehicle()
            except ValueError as exc:error(self,exc)

    def reload(self,*args):
        self.documents.clear()
        vehicle=None if self.all_documents.isChecked() else self.vehicle.currentData()
        category=self.category.currentText() if self.category.currentIndex()>0 else ''
        query=self.query.text().strip()
        try:
            rows=self.library.documents(vehicle,category,query)
            for row in rows:
                item=QListWidgetItem(f"{row['title']} · {row['category']} · {row['index_status']}")
                item.setData(Qt.ItemDataRole.UserRole,(row['id'],1));self.documents.addItem(item)
            if query:
                for row in self.library.search(query,vehicle,category):
                    label='section' if row['format']=='html' else 'page'
                    location=''
                    if row['format']=='html':
                        location=f" · {row['path']}#{row['anchor']}"
                    item=QListWidgetItem(f"{row['title']} · {label} {row['page']}{location}\n{row['excerpt']}")
                    item.setData(Qt.ItemDataRole.UserRole,(row['id'],row['page']));self.documents.addItem(item)
        except (ValueError,sqlite3.Error) as exc:error(self,exc)
        if self.documents.count():self.documents.setCurrentRow(0)

    def selected_document(self):
        item=self.documents.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def details(self,*args):
        selected=self.selected_document()
        if not selected:self.detail.setText('No document selected.');return
        doc=self.library.document(selected[0])
        vehicle=self.library.vehicle(self.vehicle.currentData()) if self.vehicle.currentData() else {}
        match=applicability(vehicle,json.loads(doc['applicability']),doc['verification']==VERIFICATIONS[-1])
        self.detail.setText(f"{match} · User association is not factory verification.\n{doc['description']}\nSource: {doc['source'] or 'Unknown'} · Publisher: {doc['publisher'] or 'Unknown'}\n{doc['verification']} · Rights: {doc['rights']}\nPublished: {doc['publication_date'] or 'Unknown'} · Reviewed: {doc['reviewed_at'] or 'Unknown'}")

    def run_task(self,operation,parameters):
        if self.busy:return
        self.task=DocumentTask(self.store,operation,parameters,self)
        self.local.setEnabled(False);self.cancel.show();self.progress.show();self.progress.setRange(0,0)
        self.status.setText('Processing document in a separate process…')
        self.task.progress.connect(lambda n,total:(self.progress.setRange(0,total),self.progress.setValue(n)))
        def complete(result,message):
            self.local.setEnabled(True);self.cancel.hide();self.progress.hide()
            self.status.setText(message or 'Document operation complete.');self.reload()
        self.task.finished.connect(complete);self.task.start()

    def import_pdf(self):
        source,_=QFileDialog.getOpenFileName(self,'Import a lawful document','','Supported documents (*.pdf *.html *.htm *.zip);;All files (*)')
        if not source:return
        dialog=DocumentDialog(self.library,self.vehicle.currentData(),parent=self)
        dialog.fields['title'].setText(Path(source).stem)
        if dialog.exec():
            values,vehicles=dialog.payload
            self.run_task('import',dict(source=source,metadata=values,vehicles=vehicles))

    def edit_document(self):
        selected=self.selected_document()
        if not selected:return
        dialog=DocumentDialog(self.library,document=self.library.document(selected[0]),parent=self)
        if dialog.exec():
            try:self.library.save_metadata(selected[0],*dialog.payload);self.reload()
            except (ValueError,sqlite3.Error) as exc:error(self,exc)

    def open_document(self,*args):
        selected=self.selected_document()
        if selected:self.show_pdf(*selected)

    def show_pdf(self,identifier,page=1):
        if self.library.document(identifier)['format']=='html':
            from openwrench.html_ui import HtmlViewer
            viewer=HtmlViewer(self.library,identifier,page,self)
        else:
            viewer=PdfViewer(self.library,identifier,page,self)
        self.viewers.append(viewer)
        viewer.finished.connect(lambda _:self.reload_bookmarks())
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.destroyed.connect(lambda:self.viewers.remove(viewer) if viewer in self.viewers else None)
        viewer.show()

    def reindex(self):
        selected=self.selected_document()
        if selected:self.run_task('index',dict(id=selected[0]))

    def locate(self):
        selected=self.selected_document()
        if not selected:return
        if self.library.document(selected[0])['format']=='html':
            error(self,'Restore a complete SQLite backup to recover an HTML bundle.');return
        source,_=QFileDialog.getOpenFileName(self,'Locate the exact original PDF','','PDF (*.pdf);;All files (*)')
        if source:self.run_task('locate',dict(id=selected[0],source=source))

    def delete_document(self):
        selected=self.selected_document()
        if not selected:return
        if QMessageBox.question(self,'Remove document?',
            'Remove this document, its index, associations and bookmarks? Original files stay untouched. Any local viewing copy stays in the document folder. Save a SQLite backup first to retain all metadata.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.library.delete(selected[0]);self.reload();self.reload_bookmarks();self.reload_schedules()

    def source_details(self,*args):
        item=self.sources.currentItem()
        if not item:return
        ref=item.data(Qt.ItemDataRole.UserRole)
        vehicle=self.library.vehicle(self.vehicle.currentData()) if self.vehicle.currentData() else {}
        self.source_detail.setText(f"{applicability(vehicle,ref.requirements)}\n{ref.content_type} · {ref.access_method}\n{ref.availability}\n{ref.rights}\nReviewed: {ref.reviewed_at}\n{ref.url}")

    def open_source(self):
        item=self.sources.currentItem()
        if item:open_url(self,item.data(Qt.ItemDataRole.UserRole).url)

    def bookmark_source(self):
        item=self.sources.currentItem()
        if item:
            ref=item.data(Qt.ItemDataRole.UserRole)
            self.library.bookmark(ref.title,self.vehicle.currentData(),url=ref.url,source=ref.source)
            self.status.setText('Reference bookmarked.');self.reload_bookmarks()

    def fetch_recalls(self):
        if self.vehicle.currentData():
            self.recall_status.setText('Contacting NHTSA…')
            self.recall_client.fetch(self.library.vehicle(self.vehicle.currentData()))

    def got_recalls(self,rows,message):
        self.recalls.clear();self.recall_status.setText(message or 'NHTSA year/make/model results. Confirm VIN applicability with NHTSA or the manufacturer.')
        for row in rows:
            item=QListWidgetItem(f"{row['campaign']} · {row['date']} · {row['component']}\n{row['summary']}")
            item.setData(Qt.ItemDataRole.UserRole,row);self.recalls.addItem(item)

    def open_recall(self,item):
        row=item.data(Qt.ItemDataRole.UserRole)
        open_url(self,'https://www.nhtsa.gov/recalls?nhtsaId='+row['campaign'])

    def reload_bookmarks(self):
        self.bookmarks.clear()
        for row in self.store.connection.execute('SELECT * FROM bookmarks WHERE vehicle_id IS NULL OR vehicle_id=? ORDER BY title',(self.vehicle.currentData(),)):
            row=dict(row);item=QListWidgetItem(row['title']+(f" · page {row['page']}" if row['page'] else ''))
            item.setData(Qt.ItemDataRole.UserRole,row);self.bookmarks.addItem(item)

    def open_bookmark(self):
        item=self.bookmarks.currentItem()
        if not item:return
        row=item.data(Qt.ItemDataRole.UserRole)
        if row['document_id']:self.show_pdf(row['document_id'],row['page'])
        else:open_url(self,row['url'])

    def delete_bookmark(self):
        item=self.bookmarks.currentItem()
        if item:
            with self.store.connection:self.store.connection.execute('DELETE FROM bookmarks WHERE id=?',(item.data(Qt.ItemDataRole.UserRole)['id'],))
            self.reload_bookmarks()

    def reload_schedules(self):
        self.schedules.clear();self.reminders.setText('');identifier=self.vehicle.currentData()
        if not identifier:return
        maintenance=Maintenance(self.store)
        due_count=0
        for row in maintenance.rows(identifier):
            due=maintenance.due(row)
            if row['reminder'] and due['status']=='Due':due_count+=1
            item=QListWidgetItem(f"{row['title']} · {row['origin']} · {due['status']}\nNext: {due['next_date'] or 'date unknown'} / {due['next_distance'] if due['next_distance'] is not None else 'distance unknown'} {due['unit']}"+(' · Reminder enabled' if row['reminder'] else ''))
            item.setData(Qt.ItemDataRole.UserRole,row);self.schedules.addItem(item)
        if due_count:self.reminders.setText(f'{due_count} maintenance reminder(s) due. Open Maintenance to review.')
        if self.schedules.count():self.schedules.setCurrentRow(0)

    def show_schedule(self,*args):
        item=self.schedules.currentItem()
        if not item:self.schedule_detail.setText('No schedule selected.');return
        row=item.data(Qt.ItemDataRole.UserRole)
        match=applicability(self.library.vehicle(row['vehicle_id']),json.loads(row['applicability']))
        self.schedule_detail.setText(f"{match}\nLast baseline: {row['baseline_date'] or 'Unknown date'} / {row['baseline_odometer'] if row['baseline_odometer'] is not None else 'Unknown reading'} {row['unit']}\nSource: {row['source'] or 'User-defined'} · Publication: {row['publication'] or 'None'}\nConditions: {row['conditions'] or 'Unspecified'}\nSpecification: {row['specification'] or 'No verified specification supplied'}")

    def add_schedule(self):
        if self.vehicle.currentData() and ScheduleDialog(self.library,self.vehicle.currentData(),parent=self).exec():self.reload_schedules()

    def edit_schedule(self):
        item=self.schedules.currentItem()
        if item and ScheduleDialog(self.library,self.vehicle.currentData(),item.data(Qt.ItemDataRole.UserRole),self).exec():self.reload_schedules()

    def open_procedure(self):
        item=self.schedules.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole)['procedure_id']:self.show_pdf(item.data(Qt.ItemDataRole.UserRole)['procedure_id'])

    def delete_schedule(self):
        item=self.schedules.currentItem()
        if item and QMessageBox.question(self,'Delete schedule?','Delete this schedule? Service history stays intact.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            with self.store.connection:self.store.connection.execute('DELETE FROM schedules WHERE id=?',(item.data(Qt.ItemDataRole.UserRole)['id'],))
            self.reload_schedules()

    def stop(self):
        self.recall_client.cancel()
        if self.busy:self.task.cancel()
        for viewer in self.viewers[:]:viewer.close()

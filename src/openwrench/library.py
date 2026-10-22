"""Local document metadata, atomic imports, FTS search and recoverable PDF files."""
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from uuid import uuid4

from openwrench.garage import Garage, text, integer
from openwrench.html_bundle import _is_link
from openwrench.library_schema import CATEGORIES
from openwrench.providers import MATCH_FIELDS, safe_url

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 5000
MAX_TEXT = 20 * 1024 * 1024
VERIFICATIONS = ('User-imported documentation', 'Third-party repair information',
                 'Community information awaiting verification', 'Verified manufacturer information')


def validate_applicability(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or set(value) - set(MATCH_FIELDS):
        raise ValueError('Applicability must contain supported vehicle fields.')
    for key, item in value.items():
        if key == 'year':
            integer(item, 'Year', 1886, date.today().year + 1)
        else:
            text(item, key)
    return value


def metadata(data):
    result = {key: text(data.get(key, ''), key, 4000 if key == 'description' else 500)
              for key in ('title', 'description', 'category', 'source', 'publisher', 'publication_date',
                          'rights', 'verification', 'reviewed_at', 'document_type')}
    if not result['title'] or result['category'] not in CATEGORIES:
        raise ValueError('Enter a document title and category.')
    if not result['rights'] or result['verification'] not in VERIFICATIONS:
        raise ValueError('Record usage rights and verification status.')
    for key in ('publication_date', 'reviewed_at'):
        if result[key]:
            if date.fromisoformat(result[key]).isoformat() != result[key]:
                raise ValueError('Use ISO dates (YYYY-MM-DD).')
    if result['verification'] == VERIFICATIONS[-1] and not all(result[k] for k in ('source', 'publisher', 'reviewed_at')):
        raise ValueError('Manufacturer verification needs a source, publisher and review date.')
    result['applicability'] = json.dumps(validate_applicability(data.get('applicability', {})), sort_keys=True)
    return result


class Library:
    def __init__(self, store):
        self.store, self.db = store, store.connection
        self.directory = store.path.parent / (store.path.stem + '.documents')

    def vehicle(self, identifier):
        row = Garage(self.store).vehicle(identifier)
        extra = self.db.execute('SELECT * FROM vehicle_configuration WHERE vehicle_id=?', (identifier,)).fetchone()
        if extra:
            row.update(dict(extra))
        return row

    def configure(self, identifier, drivetrain='', transmission='', engine_code=''):
        Garage(self.store).vehicle(identifier)
        values = [text(v, 'Configuration') for v in (drivetrain, transmission, engine_code)]
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO vehicle_configuration VALUES (?,?,?,?)', (identifier, *values))

    def document(self, identifier):
        row = self.db.execute('SELECT * FROM documents WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Document no longer exists.')
        return dict(row)

    def documents(self, vehicle_id=None, category='', query=''):
        sql, args = 'SELECT d.* FROM documents d WHERE 1=1', []
        if vehicle_id:
            sql += ' AND EXISTS(SELECT 1 FROM document_vehicles v WHERE v.document_id=d.id AND v.vehicle_id=?)'
            args.append(vehicle_id)
        if category:
            sql += ' AND d.category=?'
            args.append(category)
        if query:
            sql += ' AND (instr(lower(d.title),lower(?)) OR instr(lower(d.description),lower(?)))'
            args += [query, query]
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY d.title', args)]

    def associations(self, identifier):
        return [r[0] for r in self.db.execute('SELECT vehicle_id FROM document_vehicles WHERE document_id=?', (identifier,))]

    def save_metadata(self, identifier, data, vehicles):
        self.document(identifier)
        values = metadata(data)
        for vehicle in vehicles:
            Garage(self.store).vehicle(vehicle)
        with self.db:
            self.db.execute('UPDATE documents SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), identifier))
            self.db.execute('DELETE FROM document_vehicles WHERE document_id=?', (identifier,))
            self.db.executemany('INSERT INTO document_vehicles VALUES (?,?)', [(identifier, v) for v in set(vehicles)])

    def import_document(self, source, data, vehicles, progress=lambda *a: None, cancelled=lambda: False, notice=None):
        path = Path(source)
        if path.is_dir() or path.suffix.lower() in ('.html','.htm','.zip'):
            identifier, report = self.import_html(source, data, vehicles, progress, cancelled)
            # Optional out-parameter keeps the historical single-identifier return
            # value while still letting the worker carry the import report.
            if notice is not None:
                notice.clear()
                if report: notice.update(report)
            return identifier
        from openwrench.pdf_engine import extract
        values = metadata(data)
        for vehicle in vehicles:
            Garage(self.store).vehicle(vehicle)
        path = Path(source)
        with path.open('rb') as handle:
            content = handle.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES or not content.startswith(b'%PDF-'):
            raise ValueError('Choose a PDF up to 50 MiB with a valid PDF signature.')
        digest = hashlib.sha256(content).hexdigest()
        existing = self.db.execute('SELECT id FROM documents WHERE sha256=?', (digest,)).fetchone()
        if existing:
            raise ValueError('This PDF already exists. Edit its vehicle associations instead.')
        pages = extract(content, progress, cancelled)
        if cancelled():
            raise InterruptedError('Import cancelled.')
        identifier = str(uuid4())
        # All bytes, metadata and indexing commit together. Cancellation/crash before
        # commit leaves no partial document. Original user file is never modified.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = ('id', 'sha256', *values, 'page_count', 'index_status', 'created_at')
            args = (identifier, digest, *values.values(), len(pages),
                    'Searchable' if any(p.strip() for p in pages) else 'No extractable text; OCR unavailable',
                    datetime.now(timezone.utc).isoformat())
            self.db.execute('INSERT INTO documents ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')', args)
            self.db.execute('INSERT INTO document_files VALUES (?,?)', (identifier, content))
            self.db.executemany('INSERT INTO document_vehicles VALUES (?,?)', [(identifier,v) for v in set(vehicles)])
            self._pages(identifier, pages)
        return identifier

    def import_html(self, source, data, vehicles, progress=lambda *a: None, cancelled=lambda: False):
        from openwrench.html_bundle import import_source, read_bundle_folder, describe_bundle, pack, index, _is_link
        values = metadata(data)
        for vehicle in vehicles: Garage(self.store).vehicle(vehicle)
        # A folder import reuses the same bundle pipeline; only the reader differs.
        if Path(source).is_dir() and not _is_link(source):
            files, report = read_bundle_folder(source, cancelled, progress)
        else:
            files, report = import_source(source, cancelled)
            # describe_bundle() parses the pages once to detect the entry page and
            # note dropped active content; it runs in the worker, never on the GUI.
            report = describe_bundle(files, report)
        progress(1,3)
        content, sections = pack(files), index(files)
        digest = hashlib.sha256(content).hexdigest()
        if self.db.execute('SELECT 1 FROM documents WHERE sha256=?',(digest,)).fetchone():
            raise ValueError('This HTML bundle already exists. Edit its associations instead.')
        if cancelled(): raise InterruptedError('Import cancelled.')
        identifier = str(uuid4())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = ('id','sha256',*values,'page_count','index_status','created_at','format')
            args = (identifier,digest,*values.values(),len(sections),'Searchable',datetime.now(timezone.utc).isoformat(),'html')
            self.db.execute('INSERT INTO documents ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',args)
            self.db.execute('INSERT INTO document_files VALUES (?,?)',(identifier,content))
            self.db.executemany('INSERT INTO document_vehicles VALUES (?,?)',[(identifier,v) for v in set(vehicles)])
            self._html_index(identifier,sections)
        progress(3,3)
        return identifier, report

    def _html_index(self, identifier, sections):
        self._pages(identifier,[s['text'] for s in sections])
        self.db.execute('DELETE FROM html_sections WHERE document_id=?',(identifier,))
        self.db.executemany('INSERT INTO html_sections VALUES (?,?,?,?)',
            [(identifier,n,s['path'],s['anchor']) for n,s in enumerate(sections,1)])
        self.db.execute('UPDATE documents SET page_count=?,index_status=? WHERE id=?',(len(sections),'Searchable',identifier))

    def html_files(self, identifier):
        from openwrench.html_bundle import read_zip
        doc = self.document(identifier)
        row = self.db.execute('SELECT content FROM document_files WHERE document_id=?',(identifier,)).fetchone()
        if doc['format'] != 'html' or not row or hashlib.sha256(row[0]).hexdigest() != doc['sha256']:
            raise ValueError('Missing or damaged HTML bundle.')
        return read_zip(row[0])[0]

    def html_sections(self, identifier):
        return [dict(r) for r in self.db.execute('SELECT * FROM html_sections WHERE document_id=? ORDER BY page',(identifier,))]

    def materialize_html(self, identifier):
        # Original bytes remain in SQLite. Extract only validated entries, into a
        # fresh staging directory, then rename. Never follow preexisting files.
        import shutil
        files = self.html_files(identifier)
        root = self.directory
        if _is_link(root): raise ValueError('Document directory is a symbolic link or junction.')
        root.mkdir(parents=True,exist_ok=True)
        destination = root / (self.document(identifier)['sha256']+'.html-bundle')
        if _is_link(destination): raise ValueError('Bundle directory is a symbolic link or junction.')
        if destination.exists():
            actual = set()
            for path in destination.rglob('*'):
                if _is_link(path): raise ValueError('Cached bundle contains a symbolic link or junction.')
                if path.is_file():
                    name = path.relative_to(destination).as_posix()
                    if name not in files or path.stat().st_size != len(files[name]) or path.read_bytes() != files[name]:
                        raise ValueError('Cached bundle changed. Move it aside to recover stored content.')
                    actual.add(name)
            if actual != set(files): raise ValueError('Cached bundle is incomplete. Move it aside to recover stored content.')
            return destination
        staging = Path(tempfile.mkdtemp(prefix='.html-',dir=root))
        try:
            for name,content in files.items():
                path = staging / name
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as output: output.write(content)
            staging.rename(destination)
        finally:
            if staging.exists(): shutil.rmtree(staging)
        return destination

    def _pages(self, identifier, pages):
        self.db.execute('DELETE FROM library_fts WHERE document_id=?', (identifier,))
        self.db.execute('DELETE FROM document_pages WHERE document_id=?', (identifier,))
        rows = [(identifier, n, value) for n,value in enumerate(pages,1)]
        self.db.executemany('INSERT INTO document_pages VALUES (?,?,?)', rows)
        self.db.executemany('INSERT INTO library_fts VALUES (?,?,?)', rows)

    def reindex(self, identifier, progress=lambda *a: None, cancelled=lambda: False):
        from openwrench.pdf_engine import extract
        if self.document(identifier)['format'] == 'html':
            files = self.html_files(identifier)
            from openwrench.html_bundle import index
            sections = index(files)
            if cancelled(): raise InterruptedError('Indexing cancelled.')
            with self.db:
                self._html_index(identifier, sections)
            return
        row = self.db.execute('SELECT content FROM document_files WHERE document_id=?', (identifier,)).fetchone()
        if not row:
            raise ValueError('Document bytes are missing. Restore a complete backup.')
        pages = extract(row[0], progress, cancelled)
        if cancelled():
            raise InterruptedError('Indexing cancelled.')
        with self.db:
            self._pages(identifier, pages)
            self.db.execute('UPDATE documents SET page_count=?,index_status=? WHERE id=?',
                (len(pages), 'Searchable' if any(p.strip() for p in pages) else 'No extractable text; OCR unavailable', identifier))

    def local_path(self, identifier):
        document = self.document(identifier)
        if document['format'] == 'html':
            return self.materialize_html(identifier)
        digest = document['sha256']
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid document identity.')
        root = self.directory
        if _is_link(root):
            raise ValueError('The document directory must not be a symbolic link or junction.')
        root.mkdir(parents=True, exist_ok=True)
        path = root / (digest + '.pdf')
        if _is_link(path):
            raise ValueError('The document file must not be a symbolic link or junction.')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Local PDF changed. Move it aside, then recover the stored copy.')
            return path
        content = self.db.execute('SELECT content FROM document_files WHERE document_id=?', (identifier,)).fetchone()
        if not content or hashlib.sha256(content[0]).hexdigest() != digest:
            raise ValueError('Document content is missing or damaged. Restore a backup or locate the original.')
        with path.open('xb') as output:
            try:
                output.write(content[0])
                output.flush()
                os.fsync(output.fileno())
            except Exception:
                output.close()
                path.unlink(missing_ok=True)
                raise
        return path

    def locate(self, identifier, source):
        doc = self.document(identifier)
        with Path(source).open('rb') as handle:
            content = handle.read(MAX_PDF_BYTES+1)
        if len(content) > MAX_PDF_BYTES or hashlib.sha256(content).hexdigest() != doc['sha256']:
            raise ValueError('Select the exact original PDF. Its content hash must match.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO document_files VALUES (?,?)', (identifier,content))

    def delete(self, identifier):
        doc = self.document(identifier)
        # Keep any materialized file in a recoverable local folder, never touch source.
        path = self.directory / (doc['sha256']+('.html-bundle' if doc['format']=='html' else '.pdf'))
        with self.db:
            self.db.execute('DELETE FROM library_fts WHERE document_id=?', (identifier,))
            self.db.execute('DELETE FROM documents WHERE id=?', (identifier,))
        # Cached copy stays deliberately. UI explains retention before confirmation.
        return path

    def search(self, query, vehicle_id=None, category='', document_id=None):
        tokens = re.findall(r'\w+', text(query, 'Search', 200), re.UNICODE)
        if not tokens:
            return []
        expression = ' AND '.join('"'+t+'"' for t in tokens)
        sql = '''SELECT d.id,d.title,d.category,d.source,d.publisher,d.format,h.path,h.anchor,CAST(f.page AS INTEGER) AS page,
                 snippet(library_fts,2,'[',']',' … ',24) AS excerpt
                 FROM library_fts f JOIN documents d ON d.id=f.document_id
                 LEFT JOIN html_sections h ON h.document_id=d.id AND h.page=CAST(f.page AS INTEGER)
                 WHERE library_fts MATCH ?'''
        args = [expression]
        if vehicle_id:
            sql += ' AND EXISTS(SELECT 1 FROM document_vehicles v WHERE v.document_id=d.id AND v.vehicle_id=?)'
            args.append(vehicle_id)
        if category:
            sql += ' AND d.category=?'; args.append(category)
        if document_id:
            sql += ' AND d.id=?'; args.append(document_id)
        return [dict(r) for r in self.db.execute(sql+' ORDER BY rank LIMIT 200', args)]

    def bookmark(self, title, vehicle_id=None, document_id=None, page=None, url='', source=''):
        if vehicle_id:
            Garage(self.store).vehicle(vehicle_id)
        if document_id:
            doc = self.document(document_id)
            page = integer(page or 1, 'Page', 1, doc['page_count'])
        else:
            safe_url(url)
        identifier = str(uuid4())
        with self.db:
            self.db.execute('INSERT INTO bookmarks VALUES (?,?,?,?,?,?,?)',
                (identifier, vehicle_id, document_id, page, text(title,'Title',500,True),url,text(source,'Source',500)))
        return identifier


def validate_library_records(data, include_content=True):
    """Validate restore payload without interpreting imported executable schema."""
    from openwrench.transfers import valid_id, valid_timestamp
    documents = {}
    vehicles = {r['id']:r for r in data['vehicles']}
    entries = {r['id']:r for r in data['entries']}
    for doc in data['documents']:
        valid_id(doc['id'])
        metadata(doc)
        valid_timestamp(doc['created_at'])
        integer(doc['page_count'],'Page count',1,MAX_PAGES)
        if not re.fullmatch('[0-9a-f]{64}',doc['sha256']):
            raise ValueError('Invalid PDF hash.')
        if doc['format'] not in ('pdf','html'): raise ValueError('Unsupported document format.')
        if doc['index_status'] not in ('Searchable','No extractable text; OCR unavailable'):
            raise ValueError('Invalid indexing status.')
        documents[doc['id']] = doc
    files = set()
    for row in data.get('document_files',[]):
        doc = documents.get(row['document_id'])
        value = row['content']
        if not doc or not isinstance(value,bytes) or len(value)>MAX_PDF_BYTES or (doc['format']=='pdf' and not value.startswith(b'%PDF-')) or hashlib.sha256(value).hexdigest()!=doc['sha256']:
            raise ValueError('Missing or damaged document content.')
        if doc['format']=='html':
            from openwrench.html_bundle import read_zip, index
            sections = index(read_zip(value)[0])
            actual = [dict(path=r['path'],anchor=r['anchor'],page=r['page']) for r in data['html_sections'] if r['document_id']==doc['id']]
            expected = [dict(path=r['path'],anchor=r['anchor'],page=n) for n,r in enumerate(sections,1)]
            if sorted(actual,key=lambda r:r['page']) != expected or len(sections)!=doc['page_count']:
                raise ValueError('HTML section metadata does not match bundle.')
        files.add(doc['id'])
    if include_content and files != set(documents):
        raise ValueError('Backup lacks document content.')
    for row in data.get('html_sections',[]):
        from openwrench.html_bundle import safe_path
        doc = documents.get(row['document_id'])
        if not doc or doc['format']!='html': raise ValueError('Orphan HTML section.')
        safe_path(row['path'])
        integer(row['page'],'Section',1,doc['page_count'])
        text(row['anchor'],'Anchor',500)
    sizes = {}
    for row in data.get('document_pages',[]):
        doc = documents.get(row['document_id'])
        if not doc:
            raise ValueError('Orphan document page.')
        integer(row['page'],'Page',1,doc['page_count'])
        text(row['text'],'Page text',MAX_TEXT)
        sizes[doc['id']] = sizes.get(doc['id'],0)+len(row['text'].encode('utf-8'))
        if sizes[doc['id']]>MAX_TEXT:
            raise ValueError('Excessive indexed text.')
    for row in data['vehicle_configuration']:
        if row['vehicle_id'] not in vehicles:
            raise ValueError('Orphan vehicle configuration.')
        for key in ('drivetrain','transmission','engine_code'):
            text(row[key],key)
    for row in data['document_vehicles']:
        if row['vehicle_id'] not in vehicles or row['document_id'] not in documents:
            raise ValueError('Orphan document association.')
    for row in data['bookmarks']:
        valid_id(row['id'])
        text(row['title'],'Bookmark',500,True)
        text(row['source'],'Source',500)
        if row['vehicle_id'] and row['vehicle_id'] not in vehicles:
            raise ValueError('Orphan bookmark.')
        if row['document_id']:
            if row['document_id'] not in documents:
                raise ValueError('Orphan bookmark.')
            integer(row['page'],'Page',1,documents[row['document_id']]['page_count'])
        else:
            safe_url(row['url'])
    for row in data['schedules']:
        valid_id(row['id'])
        if row['vehicle_id'] not in vehicles or row['unit'] not in ('mi','km'):
            raise ValueError('Invalid schedule owner or units.')
        for key in ('title','source','publication','publisher','publication_date','rights','reviewed_at','conditions','specification'):
            text(row[key],key,2000,key=='title')
        if row['origin'] not in ('User-defined','Manufacturer source (user verified)'):
            raise ValueError('Invalid schedule source type.')
        if row['origin']!='User-defined' and not all(row[k] for k in ('source','publication','publisher','rights','reviewed_at')):
            raise ValueError('Missing manufacturer source.')
        for key,maximum in (('distance_interval',10000000),('months_interval',1200)):
            if row[key] is not None:
                integer(row[key],key,1,maximum)
        if row['distance_interval'] is None and row['months_interval'] is None:
            raise ValueError('Missing schedule interval.')
        from openwrench.garage import validated_date
        for key in ('baseline_date','publication_date','reviewed_at'):
            if row[key]:validated_date(row[key])
        if row['baseline_odometer'] is not None:
            integer(row['baseline_odometer'],'Odometer',0,10000000)
        if row['last_entry_id']:
            entry = entries.get(row['last_entry_id'])
            if not entry or entry['vehicle_id']!=row['vehicle_id'] or entry['kind']!='service':
                raise ValueError('Invalid completed service association.')
        if row['procedure_id'] and row['procedure_id'] not in documents:
            raise ValueError('Missing procedure.')
        if row['reminder'] not in (0,1):
            raise ValueError('Invalid reminder.')
        validate_applicability(row['applicability'])

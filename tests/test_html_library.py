"""Entirely original HTML and diagrams. No third-party service manual content."""
from contextlib import closing
from io import BytesIO
from pathlib import Path
import json
import sqlite3
import stat
import zipfile
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument, QImage
from openwrench.html_bundle import read_zip, pack, resolve, inspect, StaticHTML, safe_svg, import_source
from openwrench.html_ui import OfflineBrowser, HtmlViewer
from openwrench.library import Library
from openwrench.garage import Garage
from openwrench.storage import Store
from openwrench.transfers import export_garage, garage_document
from test_library import details, synthetic_pdf, library


def synthetic_html(path):
    files = {
        'index.html': b'<link rel="stylesheet" href="assets/style.css"><h1>Original training manual</h1><a href="procedures/brake.htm#check">Inspect brakes</a><img src="assets/diagram.svg"><script src="assets/app.js">secret_script</script>',
        'procedures/brake.htm': b'<a href="../index.html">Home</a><h2 id="check">Synthetic caliper inspection</h2><p>Measure fictional clearance.</p><a href="missing.htm">Absent procedure</a><a href="../index.html#absent">Absent anchor</a><img src="https://example.invalid/tracker.png">',
        'assets/style.css': b'h1 {color: blue; background-image: url(missing.png)}',
        'assets/app.js': b'fetch("https://example.invalid")',
        'assets/diagram.svg': b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40"><rect x="2" y="2" width="40" height="20" fill="blue"/></svg>',
    }
    path.write_bytes(pack(files))
    return path


@pytest.mark.parametrize('name',['../escape.html','/absolute.html','C:/file.html','a\\b.html','CON.html','a/../b.html','a./b.html','a:stream.html'])
def test_unsafe_archive_paths(name):
    output=BytesIO()
    stored_name = name.replace('\\','/')
    with zipfile.ZipFile(output,'w') as z:z.writestr(stored_name,b'<p>test</p>')
    # Windows ZipInfo normalizes backslashes on write. Patch both ZIP headers
    # so every OS tests the same actual unsafe archive, not a normalized fixture.
    raw = output.getvalue().replace(stored_name.encode(),name.encode())
    with pytest.raises(ValueError):read_zip(raw)


def test_zip_symlink_duplicate_collision_and_bomb():
    for mode in ('link','duplicate','collision','bomb'):
        output=BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('index.html',b'<p>test</p>')
            if mode=='link':
                info=zipfile.ZipInfo('link.html');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,b'/etc/passwd')
            elif mode=='duplicate':z.writestr('INDEX.HTML',b'duplicate')
            elif mode=='collision':z.writestr('index.html/child.html',b'bad')
            else:z.writestr('huge.txt',b'x'*(2*1024*1024))
        with pytest.raises(ValueError):read_zip(output.getvalue())
    with pytest.raises(ValueError):read_zip(b'not zip')


def test_links_report_and_sections(tmp_path):
    files=read_zip(synthetic_html(tmp_path/'manual.zip').read_bytes())
    assert resolve('procedures/brake.htm','../index.html')==('index.html','')
    for link in ('../../outside','file:///etc/passwd','https://example.org','//example.org/a','%2fetc/passwd','%2e%2e/%2e%2e/x'):
        with pytest.raises(ValueError):resolve('procedures/brake.htm',link)
    issues=inspect(files)
    assert {r['reason'] for r in issues}=={'Missing resource','Missing anchor','Blocked external or unsafe URL'}
    assert any(r['reference']=='missing.png' for r in issues)
    parsed=StaticHTML('procedures/brake.htm',files)
    assert any(s['anchor']=='check' and 'caliper' in s['text'] for s in parsed.sections)
    rendered=''.join(StaticHTML('index.html',files).output)
    assert '<script' not in rendered and 'secret_script' not in rendered and 'color: blue' in rendered


def test_html_import_search_vehicle_export_restore(library,tmp_path):
    lib,vehicle=library
    other=Garage(lib.store).save_vehicle(dict(year=2001,make='Toyota',model='Tundra'))
    source=synthetic_html(tmp_path/'manual.zip')
    identifier=lib.import_document(source,details(),[vehicle])
    result=lib.search('caliper',vehicle)[0]
    assert result['id']==identifier and result['source']=='Synthetic test' and result['format']=='html'
    assert not lib.search('caliper',other)
    section=lib.html_sections(identifier)[result['page']-1]
    assert section['path']=='procedures/brake.htm' and section['anchor']=='check'
    lib.bookmark('Test',vehicle,identifier,result['page'])
    with pytest.raises(ValueError,match='already exists'):lib.import_document(source,details(),[vehicle])
    root=lib.local_path(identifier)
    assert (root/'assets/diagram.svg').read_bytes()==lib.html_files(identifier)['assets/diagram.svg']
    exported=garage_document(lib.store)
    assert exported['database_schema']==4 and exported['format_version']==3
    assert exported['repair_library']['html_sections'][result['page']-1]['path']==section['path']
    assert 'fictional clearance' not in json.dumps(exported) and '<svg' not in json.dumps(exported)
    csv=export_garage(lib.store,tmp_path/'export.zip','csv')
    with zipfile.ZipFile(csv) as z:
        assert 'html_sections.csv' in z.namelist()
        assert not any(name.endswith(('.html','.svg','.js')) for name in z.namelist())
    backup=lib.store.backup(tmp_path/'backup.sqlite3')
    with closing(Store(tmp_path/'restored.sqlite3')) as target:
        target.restore(backup);recovered=Library(target)
        assert recovered.html_files(identifier)==lib.html_files(identifier)
        assert recovered.local_path(identifier).is_dir()
        assert recovered.search('caliper')[0]['page']==result['page']
        assert target.connection.execute('SELECT page FROM bookmarks').fetchone()[0]==result['page']
    lib.reindex(identifier)
    assert lib.search('caliper')[0]['page']==result['page']


def test_cancel_and_failed_import_leave_no_records(library,tmp_path):
    lib,vehicle=library;source=synthetic_html(tmp_path/'manual.zip')
    with pytest.raises(InterruptedError):lib.import_document(source,details(),[vehicle],cancelled=lambda:True)
    assert lib.documents()==[] and not lib.directory.exists()
    source.write_bytes(b'broken')
    with pytest.raises(ValueError):lib.import_document(source,details(),[vehicle])
    assert lib.documents()==[]


def test_standalone_html_collects_reachable_only(tmp_path):
    root=tmp_path/'manual';root.mkdir()
    (root/'index.htm').write_text('<a href="page.html">Next</a><img src="missing.png"><a href="../private.txt">Outside</a>')
    (root/'page.html').write_text('<p>Linked original page</p>')
    (root/'unrelated.txt').write_text('Private record')
    files=import_source(root/'index.htm')
    assert set(files)=={'index.htm','page.html'}
    assert len(inspect(files))==2


def test_static_renderer_blocks_active_content_and_local_files(app,tmp_path):
    files={'index.html':b'<style>p {color:red} @import "file:///secret";</style><p onclick="bad()">Visible</p><iframe src="file:///secret">hidden</iframe><img src="file:///secret"><a href="javascript:bad()">link</a>'}
    parsed=StaticHTML('index.html',files);html=''.join(parsed.output)
    assert all(v not in html for v in ('onclick','file:','javascript:','iframe','hidden','@import'))
    assert 'color:red' in html
    assert all('color' not in s['text'] for s in parsed.sections)
    browser=OfflineBrowser(files)
    for url in ('file:///etc/passwd','https://example.org/x','qrc:/secret','bundle:/../secret'):
        assert browser.loadResource(QTextDocument.ResourceType.ImageResource,QUrl(url)).isEmpty()
    browser.setSource(QUrl('file:///etc/passwd'))
    assert not browser.toPlainText()
    browser.close()


def test_svg_original_diagram_and_active_svg(app,tmp_path):
    files=read_zip(synthetic_html(tmp_path/'manual.zip').read_bytes())
    browser=OfflineBrowser(files)
    image=browser.loadResource(QTextDocument.ResourceType.ImageResource,QUrl('bundle:/assets/diagram.svg'))
    assert isinstance(image,QImage) and image.width()==60
    for data in (b'<!DOCTYPE svg><svg/>', b'<svg><script/></svg>',b'<svg><image href="file:///etc/passwd"/></svg>'):
        with pytest.raises(ValueError):safe_svg(data)
    browser.close()


def test_cached_tampering_detected(library,tmp_path):
    lib,vehicle=library;identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    root=lib.local_path(identifier);(root/'index.html').write_text('changed')
    with pytest.raises(ValueError,match='changed'):lib.local_path(identifier)
    assert b'Original training' in lib.html_files(identifier)['index.html']


def test_restore_rejects_mismatched_html_metadata(library,tmp_path):
    lib,vehicle=library;identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    backup=lib.store.backup(tmp_path/'bad.sqlite3')
    with closing(sqlite3.connect(backup)) as db:
        db.execute("UPDATE html_sections SET path='../escape.html'");db.commit()
    with pytest.raises(ValueError):lib.store.restore(backup)
    assert lib.search('caliper')[0]['id']==identifier and Garage(lib.store).vehicle(vehicle)


def test_schema3_migration_and_restore_pdf_preservation(tmp_path):
    from types import SimpleNamespace
    from openwrench.library_schema import create_library
    old=tmp_path/'v3.sqlite3'
    with closing(sqlite3.connect(old)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')");db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db));create_library(db);db.commit()
    original=old.read_bytes()
    with closing(Store(tmp_path/'new.sqlite3')) as store:
        store.restore(old)
        assert store.theme=='light' and old.read_bytes()==original
        lib=Library(store);identifier=lib.import_document(synthetic_pdf(tmp_path/'original.pdf'),details(),[])
        assert lib.document(identifier)['format']=='pdf' and lib.search('brake')[0]['id']==identifier
    with closing(Store(old)) as migrated:
        assert migrated.connection.execute('PRAGMA user_version').fetchone()[0]==4
        assert list(tmp_path.glob('v3.pre-v4-*.sqlite3'))


def test_native_navigation_bookmarks(library,tmp_path,app):
    from PySide6.QtTest import QTest
    lib,vehicle=library;identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    viewer=HtmlViewer(lib,identifier)
    for _ in range(300):
        app.processEvents();QTest.qWait(10)
        if viewer.current:break
    assert viewer.current==('index.html','')
    viewer.follow(QUrl('bundle:/procedures/brake.htm#check'))
    assert 'caliper' in viewer.browser.toPlainText()
    viewer.bookmark()
    assert lib.store.connection.execute('SELECT page FROM bookmarks').fetchone()[0]==lib.search('caliper')[0]['page']
    viewer.move(-1);assert viewer.current==('index.html','')
    viewer.move(1);assert viewer.current==('procedures/brake.htm','check')
    viewer.browser.zoomIn();viewer.browser.zoomOut()
    viewer.follow(QUrl('https://example.invalid'));assert viewer.current[0]=='procedures/brake.htm'
    viewer.close();app.processEvents()


def test_html_restore_failure_rolls_back(library,tmp_path,monkeypatch):
    lib,vehicle=library;identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    backup=lib.store.backup(tmp_path/'snapshot.sqlite3')
    original=lib.store._replace_records
    def failing(records):
        original(records)
        raise OSError('Simulated post-replacement failure')
    monkeypatch.setattr(lib.store,'_replace_records',failing)
    with pytest.raises(ValueError,match='rolled back'):lib.store.restore(backup)
    assert lib.search('caliper')[0]['id']==identifier
    assert lib.html_files(identifier)['assets/diagram.svg']
    assert list(tmp_path.glob('workspace.pre-restore-*.sqlite3'))


def test_offline_import_and_search(library,tmp_path,monkeypatch):
    import socket
    def network_forbidden(*args,**kwargs):raise AssertionError('Network attempted')
    monkeypatch.setattr(socket,'create_connection',network_forbidden)
    lib,vehicle=library
    identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    assert lib.search('caliper')[0]['id']==identifier


def test_schema4_migration_failure_rolls_back(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from openwrench import library_schema
    path=tmp_path/'old.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','dark')");db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db));library_schema.create_library(db);db.commit()
    def failing(db):
        db.execute("ALTER TABLE documents ADD COLUMN format TEXT NOT NULL DEFAULT 'pdf'")
        raise OSError('Simulated migration failure')
    monkeypatch.setattr(library_schema,'create_html',failing)
    with pytest.raises(OSError):Store(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert 'format' not in [r[1] for r in db.execute('PRAGMA table_info(documents)')]
    assert list(tmp_path.glob('old.pre-v4-*.sqlite3'))


def test_archive_size_and_case_alias_limits(monkeypatch):
    from openwrench import html_bundle
    output=BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('A/index.html',b'<p>test</p>');z.writestr('a/other.html',b'test')
    with pytest.raises(ValueError,match='Case-ambiguous'):read_zip(output.getvalue())
    content=pack({'index.html':b'<p>test</p>'})
    monkeypatch.setattr(html_bundle,'MAX_TOTAL',1)
    with pytest.raises(ValueError,match='expansion'):read_zip(content)


def test_cancel_after_parsing_is_atomic(library,tmp_path):
    lib,vehicle=library;source=synthetic_html(tmp_path/'manual.zip')
    cancel=[False]
    def progress(*args):cancel[0]=True
    with pytest.raises(InterruptedError):lib.import_document(source,details(),[vehicle],progress,lambda:cancel[0])
    assert lib.documents()==[] and source.is_file()


def test_local_symlink_is_rejected(tmp_path):
    folder=tmp_path/'manual';folder.mkdir()
    (folder/'index.html').write_text('<a href="linked.html">Next</a>')
    outside=tmp_path/'outside.html';outside.write_text('Private')
    try:(folder/'linked.html').symlink_to(outside)
    except OSError:pytest.skip('OS denies creating symlinks for this user')
    with pytest.raises(ValueError,match='Symbolic'):import_source(folder/'index.html')


def test_svg_disguised_as_raster_cannot_bypass_sanitizer(app):
    browser=OfflineBrowser({'image.png':b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="file:///private.png"/></svg>'})
    result=browser.loadResource(QTextDocument.ResourceType.ImageResource,QUrl('bundle:/image.png'))
    assert result.isEmpty() if hasattr(result,'isEmpty') else result.isNull()
    browser.close()

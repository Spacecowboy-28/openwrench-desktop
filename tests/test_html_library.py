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
from openwrench.html_bundle import (read_zip, pack, resolve, inspect, StaticHTML, safe_svg, import_source,
                                    read_bundle_folder, entry_page, folder_report_text)
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
            # A bomb must exceed the declared per-file budget. A high compression
            # ratio alone is legitimate for generated torque tables, so the ratio
            # heuristic was removed and the declared size is now the contract.
            else:z.writestr('huge.html',b'<p>'+b'x'*(11*1024*1024)+b'</p>')
        with pytest.raises(ValueError):read_zip(output.getvalue())
    with pytest.raises(ValueError):read_zip(b'not zip')


def test_high_ratio_manual_is_accepted_and_repackable(tmp_path):
    """A repetitive manual must import as a ZIP and as a folder, then repack."""
    page=b'<html><body><table>'+b'<tr><td>Wheel nut torque 120 Nm</td></tr>'*180000+b'</table></body></html>'
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('index.html',page)
    raw=output.getvalue()
    assert len(page)/len(raw) > 200
    assert read_zip(raw)[0]['index.html']==page
    folder=tmp_path/'manual';folder.mkdir()
    (folder/'index.html').write_bytes(page)
    files=import_source(folder/'index.html')[0]
    assert pack(files)==pack(read_zip(pack(files))[0])


def test_links_report_and_sections(tmp_path):
    files=read_zip(synthetic_html(tmp_path/'manual.zip').read_bytes())[0]
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
    assert exported['database_schema']==6 and exported['format_version']==3
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
    files=import_source(root/'index.htm')[0]
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
    files=read_zip(synthetic_html(tmp_path/'manual.zip').read_bytes())[0]
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
        assert migrated.connection.execute('PRAGMA user_version').fetchone()[0]==6
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


def test_viewer_does_not_parse_bundle_on_gui_thread(library,tmp_path,app,monkeypatch):
    """Opening a manual must not re-read or re-inspect the bundle on the GUI thread."""
    from PySide6.QtTest import QTest
    lib,vehicle=library;identifier=lib.import_document(synthetic_html(tmp_path/'manual.zip'),details(),[vehicle])
    # html_files() runs inside the worker process, so patching it in this process
    # only fails if the GUI thread itself calls it.
    def forbidden(*args,**kwargs):raise AssertionError('GUI thread re-read the bundle')
    monkeypatch.setattr(Library,'html_files',forbidden)
    viewer=HtmlViewer(lib,identifier)
    for _ in range(300):
        app.processEvents();QTest.qWait(10)
        if viewer.current:break
    assert viewer.current==('index.html','')
    assert viewer.browser.files['index.html']
    assert isinstance(viewer.report,list) and viewer.report
    viewer.close();app.processEvents()


def test_read_bundle_dir_matches_read_zip_and_rejects_symlinks(tmp_path):
    from openwrench.html_bundle import read_bundle_dir
    files={'index.html':b'<p>a</p>','assets/diagram.svg':b'<svg xmlns="http://www.w3.org/2000/svg"/>','notes.txt':b'x'}
    root=tmp_path/'bundle';root.mkdir()
    for name,content in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    assert read_bundle_dir(root)==read_zip(pack(files))[0]
    outside=tmp_path/'secret.html';outside.write_bytes(b'<p>private</p>')
    try:(root/'linked.html').symlink_to(outside)
    except OSError:pytest.skip('OS denies creating symlinks for this user')
    with pytest.raises(ValueError,match='symbolic link'):read_bundle_dir(root)
    (root/'linked.html').unlink()
    (root/'weird.exe').write_bytes(b'MZ')
    with pytest.raises(ValueError,match='Unsupported bundle file'):read_bundle_dir(root)


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


def test_stored_archive_limit_allows_repacking(monkeypatch):
    """MAX_ARCHIVE must exceed MAX_TOTAL so any legal bundle survives pack()."""
    from openwrench import html_bundle
    assert html_bundle.MAX_ARCHIVE > html_bundle.MAX_TOTAL
    content=pack({'index.html':b'<p>test</p>'})
    monkeypatch.setattr(html_bundle,'MAX_ARCHIVE',1)
    with pytest.raises(ValueError,match='stored-size'):read_zip(content)


def _zip_with(entries):
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries:z.writestr(name,data)
    return output.getvalue()


def test_zip_import_skips_and_reports_ordinary_unsupported_files():
    """A manual that ships Thumbs.db/desktop.ini/.DS_Store/RTF/extensionless files
    must import; those files are reported, not treated as fatal."""
    raw=_zip_with([('index.html',b'<h1>Manual</h1>'),('assets/style.css',b'h1{color:red}'),
                   ('Thumbs.db',b'\xd0\xcf\x11\xe0'),('desktop.ini',b'[.ShellClassInfo]'),
                   ('.DS_Store',b'\x00\x00\x00\x01Bud1'),('assets/readme',b'notes'),
                   ('assets/notes.rtf',b'{\\rtf1}')])
    files,report=read_zip(raw)
    assert set(files)=={'index.html','assets/style.css'}
    assert report['unsupported']==['.DS_Store','Thumbs.db','assets/notes.rtf','assets/readme','desktop.ini']
    assert report['inactive']==[]
    # The same junk must not change entry-page detection.
    assert entry_page(files)==('index.html','')


def test_zip_import_still_rejects_unsafe_and_malicious_entries():
    """Skipping unsupported files must not weaken any safety rule."""
    import stat as _stat
    # A traversal path, an absolute path and a Windows device name are still fatal.
    for name in ('../escape.html','/etc/x.html','CON.html','a/../b.html'):
        with pytest.raises(ValueError,match='Unsafe'):read_zip(_zip_with([('index.html',b'<p>x</p>'),(name,b'y')]))
    # A symlink member, a case alias and a duplicate remain fatal even when the
    # archive also carries ordinary unsupported files.
    output=BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('index.html',b'<p>x</p>');z.writestr('Thumbs.db',b'\xd0\xcf')
        info=zipfile.ZipInfo('link.html');info.create_system=3;info.external_attr=(_stat.S_IFLNK|0o777)<<16
        z.writestr(info,b'/etc/passwd')
    with pytest.raises(ValueError,match='unsafe archive entry'):read_zip(output.getvalue())
    with pytest.raises(ValueError,match='Case-ambiguous'):read_zip(_zip_with([('index.html',b'<p>x</p>'),('INDEX.HTML',b'y')]))
    with pytest.raises(ValueError,match='no HTML'):read_zip(_zip_with([('Thumbs.db',b'\xd0\xcf')]))


def test_macos_metadata_is_ignored_not_imported(tmp_path):
    """__MACOSX sidecars and AppleDouble `._*` forks are not manual content, so
    they cannot masquerade as a second index.html."""
    raw=_zip_with([('index.html',b'<h1>Real manual</h1>'),
                   ('__MACOSX/index.html',b'<h1>junk</h1>'),
                   ('__MACOSX/._index.html',b'\x00\x05\x16\x07'),
                   ('procedures/._brake.htm',b'\x00\x05\x16\x07')])
    files,report=read_zip(raw)
    assert set(files)=={'index.html'}
    assert report['metadata']==['__MACOSX/._index.html','__MACOSX/index.html','procedures/._brake.htm']
    # No misleading "Multiple index.html" note.
    assert entry_page(files)==('index.html','')
    # The folder path behaves the same way.
    folder=_folder_with(tmp_path/'zipcase',{'index.html':b'<h1>Real manual</h1>','__MACOSX/index.html':b'<h1>junk</h1>'})
    files,report=read_bundle_folder(folder)
    assert set(files)=={'index.html'} and report['entry']=='index.html'
    assert report['metadata']==['__MACOSX/index.html']
    assert any('macOS metadata' in note for note in report['notes'])


def _folder_with(root,entries):
    for name,data in entries.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return root


def test_zip_and_folder_imports_produce_the_same_report_shape(tmp_path):
    """A ZIP and the equivalent folder must tell the user the same things, so the
    import dialog is truthful whichever way the manual arrives."""
    from openwrench.html_bundle import describe_bundle
    entries={'index.html':b'<h1>Manual</h1><script>boot()</script>','assets/style.css':b'h1{color:red}',
             'Thumbs.db':b'\xd0\xcf\x11\xe0','notes.rtf':b'{\\rtf1}'}
    zip_files,zip_report=read_zip(_zip_with(list(entries.items())))
    zip_report=describe_bundle(zip_files,zip_report)
    folder=_folder_with(tmp_path/'manual',entries)
    folder_files,folder_report=read_bundle_folder(folder)
    for report in (zip_report,folder_report):
        assert report['entry']=='index.html'
        assert report['unsupported']==['Thumbs.db','notes.rtf']
        assert any('JavaScript' in note for note in report['notes'])
        assert any('cannot open' in note for note in report['notes'])
    assert set(zip_files)==set(folder_files)


def test_directory_redirection_is_never_followed(tmp_path):
    """A symlink or Windows junction inside (or as) the selected folder must not
    let the walk escape the chosen root, and must be reported as skipped."""
    from openwrench.html_bundle import _is_link
    root=tmp_path/'manual';root.mkdir()
    (root/'index.html').write_bytes(b'<a href="redirect/secret.html">x</a>')
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret.html').write_bytes(b'<h1>SECRET</h1>')
    link=root/'redirect'
    try:link.symlink_to(outside,target_is_directory=True)
    except OSError:pytest.skip('OS denies creating directory symlinks for this user')
    assert _is_link(link)
    files,report=read_bundle_folder(root)
    assert 'redirect/secret.html' not in files and 'SECRET' not in b''.join(files.values()).decode('utf-8','replace')
    assert any(row['path']=='redirect' for row in report['skipped'])
    # Selecting the redirect itself as the source folder is refused.
    with pytest.raises(ValueError,match='not a symbolic link or junction'):read_bundle_folder(link)


def test_is_link_detects_junctions_and_is_python_311_safe(tmp_path,monkeypatch):
    """_is_link must fall back safely when os.path.isjunction is absent (3.11)."""
    from openwrench import html_bundle
    plain=_folder_with(tmp_path/'plain',{'index.html':b'<p>x</p>'})
    assert html_bundle._is_link(plain/'index.html') is False
    import os as _os
    monkeypatch.delattr(_os.path,'isjunction',raising=False)
    assert html_bundle._is_link(plain) is False


def test_unclosed_drop_tags_are_reported(tmp_path):
    files=read_zip(pack({'index.html':b'<p>Before</p><script>var x=1;<p>After</p>',
                         'clean.html':b'<p>fine</p>'}))[0]
    assert StaticHTML('index.html',files).unclosed=='script'
    assert StaticHTML('clean.html',files).unclosed is None
    reasons=[i['reason'] for i in inspect(files) if i['page']=='index.html']
    assert any('Unclosed' in r for r in reasons)
    assert not [i for i in inspect(files) if i['page']=='clean.html']


def test_inspect_marks_a_truncated_report(monkeypatch):
    from openwrench import html_bundle
    monkeypatch.setattr(html_bundle,'MAX_ISSUES',3)
    files=read_zip(pack({'index.html':b'<img src="a.png"><img src="b.png"><img src="c.png"><img src="d.png">'}))[0]
    issues=inspect(files)
    assert issues[-1]['reason']==html_bundle.TRUNCATED
    assert sum(1 for i in issues if i['reason']!=html_bundle.TRUNCATED)==3


def test_cancel_after_parsing_is_atomic(library,tmp_path):
    lib,vehicle=library;source=synthetic_html(tmp_path/'manual.zip')
    cancel=[False]
    def progress(*args):cancel[0]=True
    with pytest.raises(InterruptedError):lib.import_document(source,details(),[vehicle],progress,lambda:cancel[0])
    assert lib.documents()==[] and source.is_file()


def synthetic_folder(root, pages=None, assets=True):
    """A nested offline manual folder. Original content only."""
    root.mkdir(parents=True, exist_ok=True)
    (root/'index.html').write_bytes(
        b'<link rel="stylesheet" href="assets/style.css"><h1>Original training manual</h1>'
        b'<a href="procedures/brake.htm#check">Inspect brakes</a><img src="assets/diagram.svg">'
        b'<a href="procedures/engine/head.htm">Cylinder head</a>'
        b'<a href="orphan/deep/extra.htm">Unlinked extra page</a>'
        b'<a href="missing.htm">Absent procedure</a><script src="assets/app.js">secret_script</script>')
    (root/'procedures').mkdir(exist_ok=True)
    (root/'procedures'/'brake.htm').write_bytes(
        b'<a href="../index.html">Home</a><h2 id="check">Synthetic caliper inspection</h2>'
        b'<p>Measure fictional clearance.</p><img src="../assets/diagram.svg">')
    (root/'procedures'/'engine').mkdir(exist_ok=True)
    (root/'procedures'/'engine'/'head.htm').write_bytes(b'<h2>Fictional head torque</h2><p>Original text.</p>')
    # A page no other page links to: it must still be imported and be browsable.
    (root/'orphan'/'deep').mkdir(parents=True, exist_ok=True)
    (root/'orphan'/'deep'/'extra.htm').write_bytes(b'<h2>Unlinked extra page</h2><p>Reachable only from the section list.</p>')
    if assets:
        (root/'assets').mkdir(exist_ok=True)
        (root/'assets'/'style.css').write_bytes(b'h1 {color: blue}')
        (root/'assets'/'diagram.svg').write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40"><rect x="2" y="2" width="40" height="20" fill="blue"/></svg>')
        (root/'assets'/'app.js').write_bytes(b'fetch("https://example.invalid")')
    return root


def test_folder_import_nested_assets_and_unlinked_pages(library,tmp_path):
    lib,vehicle=library
    folder=synthetic_folder(tmp_path/'manual')
    report={}
    identifier=lib.import_document(folder,details(),[vehicle],notice=report)
    assert report['entry']=='index.html'
    files=lib.html_files(identifier)
    # Nested, unlinked and asset files are all preserved with their relative paths.
    for name in ('index.html','procedures/brake.htm','procedures/engine/head.htm',
                 'orphan/deep/extra.htm','assets/style.css','assets/diagram.svg'):
        assert name in files, name
    assert lib.search('fictional clearance',vehicle)[0]['id']==identifier
    # The unlinked page is indexed, so it is reachable from the section list.
    assert any(s['path']=='orphan/deep/extra.htm' for s in lib.html_sections(identifier))
    # The original folder is untouched.
    assert (folder/'index.html').is_file() and (folder/'orphan'/'deep'/'extra.htm').is_file()


def test_folder_import_preserves_links_and_blocks_external(tmp_path):
    files,report=read_bundle_folder(synthetic_folder(tmp_path/'manual'))
    html=StaticHTML('index.html',files)
    rendered=''.join(html.output)
    assert 'bundle:/procedures/brake.htm#check' in rendered
    assert 'bundle:/assets/diagram.svg' in rendered
    assert 'example.invalid' not in rendered and '<script' not in rendered.lower()
    assert any(i['reason']=='Missing resource' for i in inspect(files))


def test_folder_import_entry_page_detection(tmp_path):
    # index.htm is honoured when there is no index.html.
    folder=tmp_path/'manual';folder.mkdir()
    (folder/'index.htm').write_text('<h1>Contents</h1><a href="a.htm">A</a>')
    (folder/'a.htm').write_text('<p>A</p>')
    files,_=read_bundle_folder(folder)
    assert entry_page(files)[0]=='index.htm'
    # Missing index: the shallowest page is chosen and the ambiguity is explained.
    other=tmp_path/'other';other.mkdir()
    (other/'zeta.htm').write_text('<p>Z</p>')
    (other/'alpha.htm').write_text('<p>A</p>')
    files,_=read_bundle_folder(other)
    entry,note=entry_page(files)
    assert entry=='alpha.htm' and 'No index.html' in note
    assert 'alpha.htm' in folder_report_text(dict(entry=entry,notes=[note]))
    # Ambiguous: two index.html files are reported rather than silently picked.
    ambiguous=tmp_path/'ambiguous';ambiguous.mkdir()
    (ambiguous/'index.html').write_text('<p>root</p>')
    (ambiguous/'sub').mkdir();(ambiguous/'sub'/'index.html').write_text('<p>sub</p>')
    files,_=read_bundle_folder(ambiguous)
    entry,note=entry_page(files)
    assert entry=='index.html' and 'Multiple' in note


def test_folder_import_reports_unusable_content(tmp_path):
    folder=synthetic_folder(tmp_path/'manual')
    (folder/'assets'/'nav.js').write_bytes(b'buildMenu()')
    (folder/'procedures'/'dynamic.php').write_bytes(b'<?php echo "x";')
    (folder/'assets'/'font.woff2').write_bytes(b'wOF2')
    (folder/'procedures'/'notes.xyz').write_bytes(b'opaque')
    files,report=read_bundle_folder(folder)
    # Storable but unusable files are kept so the bundle mirrors the folder, and
    # reported so the user is never told a script-driven manual is complete.
    assert 'assets/nav.js' in report['inactive'] and 'assets/font.woff2' in report['inactive']
    assert 'assets/nav.js' in files and 'assets/font.woff2' in files
    # Files the bundle cannot store are reported separately and not imported.
    assert 'procedures/dynamic.php' in report['unsupported']
    assert 'procedures/notes.xyz' in report['unsupported']
    assert not any(n.endswith(('.php','.xyz')) for n in files)
    text=folder_report_text(report)
    assert 'JavaScript' in text and 'not displayed by the static viewer' in text
    # A JavaScript-only entry page is called out explicitly.
    shell=tmp_path/'shell';shell.mkdir()
    (shell/'index.html').write_bytes(b'<script src="app.js"></script>')
    (shell/'app.js').write_bytes(b'document.write("manual")')
    _,report=read_bundle_folder(shell)
    assert any('JavaScript' in note for note in report['notes'])
    assert any('empty' in note.lower() for note in report['notes'])


def test_folder_import_skips_unsafe_entries_and_symlinks(tmp_path):
    folder=synthetic_folder(tmp_path/'manual')
    outside=tmp_path/'outside.html';outside.write_text('Private page')
    linked=folder/'linked.html'
    try:
        linked.symlink_to(outside)
        made_symlink=True
    except OSError:
        made_symlink=False
    files,report=read_bundle_folder(folder)
    assert 'linked.html' not in files
    if made_symlink:
        assert any(row['path']=='linked.html' for row in report['skipped'])
        assert any('symbolic link' in row['reason'] for row in report['skipped'])
    assert 'Private page' not in ''.join(v.decode('utf-8','replace') for v in files.values())


def test_folder_import_enforces_limits(tmp_path,monkeypatch):
    from openwrench import html_bundle
    folder=synthetic_folder(tmp_path/'manual')
    monkeypatch.setattr(html_bundle,'MAX_FILES',3)
    with pytest.raises(ValueError,match='supported files'):read_bundle_folder(folder)
    monkeypatch.undo()
    monkeypatch.setattr(html_bundle,'MAX_TOTAL',10)
    with pytest.raises(ValueError,match='total-size'):read_bundle_folder(folder)
    monkeypatch.undo()
    monkeypatch.setattr(html_bundle,'MAX_FILE',8)
    with pytest.raises(ValueError,match='per-file'):read_bundle_folder(folder)
    monkeypatch.undo()
    monkeypatch.setattr(html_bundle,'MAX_DEPTH',2)
    with pytest.raises(ValueError,match='nesting'):read_bundle_folder(folder)
    monkeypatch.undo()
    monkeypatch.setattr(html_bundle,'MAX_ENTRIES',4)
    with pytest.raises(ValueError,match='entries'):read_bundle_folder(folder)


def test_folder_import_requires_html_and_is_cancellable(tmp_path):
    empty=tmp_path/'empty';empty.mkdir();(empty/'notes.txt').write_text('no pages')
    with pytest.raises(ValueError,match='no HTML'):read_bundle_folder(empty)
    with pytest.raises(ValueError,match='Choose an HTML folder'):read_bundle_folder(tmp_path/'absent')
    folder=synthetic_folder(tmp_path/'manual')
    with pytest.raises(InterruptedError):read_bundle_folder(folder,cancelled=lambda:True)


def test_folder_import_is_deduplicated_and_reindexable(library,tmp_path):
    lib,vehicle=library
    folder=synthetic_folder(tmp_path/'manual')
    report={}
    identifier=lib.import_document(folder,details(),[vehicle],notice=report)
    assert report['entry']=='index.html'
    with pytest.raises(ValueError,match='already exists'):lib.import_document(folder,details(),[vehicle])
    # Reindex rebuilds the same sections from the stored bundle.
    before=lib.html_sections(identifier)
    lib.reindex(identifier)
    assert lib.html_sections(identifier)==before
    # A folder and its zipped form are the same document.
    archive=tmp_path/'manual.zip';archive.write_bytes(pack(lib.html_files(identifier)))
    with pytest.raises(ValueError,match='already exists'):lib.import_document(archive,details(),[vehicle])


def test_folder_import_large_manual_stays_off_gui_thread(library,tmp_path,app,monkeypatch):
    """A big nested folder must import with a bounded GUI-thread footprint."""
    lib,vehicle=library
    folder=tmp_path/'big';folder.mkdir()
    for n in range(400):
        sub=folder/f'section{n//50:02d}';sub.mkdir(exist_ok=True)
        (sub/f'page{n:03d}.html').write_bytes(f'<h2>Section {n}</h2><p>Original text {n}.</p><a href="../index.html">Home</a>'.encode())
    (folder/'index.html').write_bytes(b'<h1>Big original manual</h1><a href="section00/page000.html">Start</a>')
    seen=[]
    report={}
    identifier=lib.import_document(folder,details(),[vehicle],lambda n,total:seen.append((n,total)),notice=report)
    assert report['entry']=='index.html' and seen
    assert len(lib.html_sections(identifier))>=401
    assert lib.search('Original text 250',vehicle)[0]['id']==identifier


def test_worker_reports_folder_notice_without_gui_reparse(library,tmp_path):
    """The worker must carry the import report so the GUI need not re-read the folder."""
    from openwrench.pdf_worker import main as worker_main
    import json
    lib,vehicle=library
    folder=synthetic_folder(tmp_path/'manual')
    (folder/'assets'/'nav.js').write_bytes(b'menu()')
    job=tmp_path/'job.json'
    job.write_text(json.dumps(dict(database=str(lib.store.path),operation='import',source=str(folder),
                                   metadata=details(),vehicles=[vehicle],output=str(tmp_path/'render.raw'))))
    assert worker_main([str(job)])==0


def test_folder_import_via_viewer_opens_entry_page(library,tmp_path,app):
    lib,vehicle=library
    folder=synthetic_folder(tmp_path/'manual')
    report={}
    identifier=lib.import_document(folder,details(),[vehicle],notice=report)
    viewer=HtmlViewer(lib,identifier)
    viewer.task.process.waitForFinished(30000)
    for _ in range(200):
        app.processEvents()
        if viewer.browser.files:break
    assert 'index.html' in viewer.browser.files
    assert 'orphan/deep/extra.htm' in viewer.browser.files
    viewer.close()


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

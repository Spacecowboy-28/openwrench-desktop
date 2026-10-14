from contextlib import closing
from datetime import date
import json
import sqlite3
from pathlib import Path

import pytest
from openwrench.garage import Garage
from openwrench.library import Library, metadata
from openwrench.maintenance import Maintenance, plus_months
from openwrench.providers import applicability, online_references
from openwrench.storage import Store
from openwrench.transfers import garage_document, read_tables


def synthetic_pdf(path, words='Synthetic brake inspection', blank=False):
    """Original one-page fixture. No external manual content or fixture dependency."""
    stream = b'' if blank else ('BT /F1 14 Tf 40 100 Td ('+words+') Tj ET').encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    content=b'%PDF-1.4\n'; offsets=[0]
    for n,obj in enumerate(objects,1):
        offsets.append(len(content)); content+=str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(content)
    content+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])
    content+=b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'
    path.write_bytes(content)
    return path


def details():
    return dict(title='Synthetic manual',description='Original test',category='Brakes',source='Synthetic test',publisher='OpenWrench tests',
                publication_date='2026-01-01',rights='MIT test fixture',verification='User-imported documentation',reviewed_at='2026-01-02',
                document_type='Manual',applicability=dict(year=2020,make='Honda',model='Civic'))


@pytest.fixture
def library(tmp_path):
    with closing(Store(tmp_path/'workspace.sqlite3')) as store:
        vehicle=Garage(store).save_vehicle(dict(year=2020,make='Honda',model='Civic'))
        yield Library(store),vehicle


def test_import_search_view_persistence_backup_restore(library,tmp_path):
    lib,vehicle=library
    original=synthetic_pdf(tmp_path/'input.pdf')
    identifier=lib.import_document(original,details(),[vehicle])
    found=lib.search('brake',vehicle)
    assert found[0]['page']==1 and found[0]['id']==identifier and 'brake' in found[0]['excerpt']
    assert not lib.search('brake','absent')
    assert not lib.search('" OR *')
    path=lib.local_path(identifier)
    assert path.read_bytes()==original.read_bytes()
    path.unlink()
    assert lib.local_path(identifier).exists()
    lib.bookmark('Page',vehicle,identifier,1)
    backup=lib.store.backup(tmp_path/'backup.sqlite3')
    before=read_tables(lib.db)
    lib.delete(identifier)
    assert not lib.search('brake') and original.exists()
    lib.store.restore(backup)
    assert read_tables(lib.db)==before
    assert lib.search('brake')
    with closing(Store(lib.store.path)) as reopened:
        assert Library(reopened).document(identifier)['source']=='Synthetic test'
    exported=garage_document(lib.store)
    assert exported['repair_library']['documents'][0]['id']==identifier
    assert 'document_files' not in exported['repair_library'] and 'document_pages' not in exported['repair_library']


def test_duplicate_metadata_association_and_missing_file(library,tmp_path):
    lib,vehicle=library
    source=synthetic_pdf(tmp_path/'input.pdf')
    identifier=lib.import_document(source,details(),[vehicle])
    with pytest.raises(ValueError,match='already exists'):
        lib.import_document(source,details(),[])
    second=Garage(lib.store).save_vehicle(dict(year=2019,make='Mazda',model='3'))
    changed=dict(details(),title='Revised')
    lib.save_metadata(identifier,changed,[vehicle,second])
    assert len(lib.associations(identifier))==2
    assert lib.documents(second,'Brakes','Revised')[0]['id']==identifier
    assert not lib.documents(second,'Engine','Revised')
    assert lib.search('brake',second)
    with lib.db:
        lib.db.execute('DELETE FROM document_files WHERE document_id=?',(identifier,))
    with pytest.raises(ValueError,match='missing'):
        lib.local_path(identifier)
    wrong=synthetic_pdf(tmp_path/'wrong.pdf','Different')
    with pytest.raises(ValueError,match='hash'):
        lib.locate(identifier,wrong)
    lib.locate(identifier,source)
    assert lib.local_path(identifier).exists()


def test_cancel_and_bad_pdf_preserve_library(library,tmp_path):
    lib,vehicle=library
    source=synthetic_pdf(tmp_path/'input.pdf')
    with pytest.raises(InterruptedError):
        lib.import_document(source,details(),[vehicle],cancelled=lambda:True)
    for data in (b'not PDF',b'%PDF-1.4 malformed'):
        source.write_bytes(data)
        with pytest.raises(ValueError):
            lib.import_document(source,details(),[vehicle])
    assert lib.documents()==[] and Garage(lib.store).vehicle(vehicle)


def test_no_text_and_failed_reindex_preserves_metadata(library,tmp_path,monkeypatch):
    lib,vehicle=library
    identifier=lib.import_document(synthetic_pdf(tmp_path/'scan.pdf',blank=True),details(),[vehicle])
    assert 'No extractable text' in lib.document(identifier)['index_status']
    before=lib.document(identifier)
    def fail(*a): raise ValueError('index failed')
    monkeypatch.setattr('openwrench.pdf_engine.extract',fail)
    with pytest.raises(ValueError):lib.reindex(identifier)
    assert lib.document(identifier)==before


def test_pdf_render(library,tmp_path):
    from openwrench.pdf_engine import render
    lib,vehicle=library
    identifier=lib.import_document(synthetic_pdf(tmp_path/'file.pdf'),details(),[vehicle])
    output=tmp_path/'render.raw'
    result=render(lib.local_path(identifier),1,2,output)
    assert result['width']==600 and len(output.read_bytes())==result['stride']*result['height']


def test_schedule_service_links_due_and_month_end(library):
    lib,vehicle=library
    garage=Garage(lib.store)
    entry=garage.save_entry(vehicle,dict(kind='service',title='Test service',date='2026-01-31',odometer=1000))
    schedules=Maintenance(lib.store)
    data=dict(vehicle_id=vehicle,title='User test',origin='User-defined',distance_interval=500,months_interval=1,last_entry_id=entry)
    schedules.save(data)
    row=schedules.rows(vehicle)[0]
    assert schedules.due(row,date(2026,2,27))['next_date']=='2026-02-28'
    assert schedules.due(row,date(2026,2,28))['status']=='Due'
    garage.save_entry(vehicle,dict(kind='mileage',date='2026-02-01',odometer=1500))
    assert schedules.due(row,date(2026,2,2))['status']=='Due'
    garage.delete_entry(vehicle,entry)
    row=schedules.rows(vehicle)[0]
    assert row['last_entry_id'] is None and row['baseline_odometer']==1000
    with pytest.raises(ValueError):schedules.save(dict(data,origin='Manufacturer source (user verified)'))
    assert plus_months(date(2024,1,31),1)==date(2024,2,29)


@pytest.mark.parametrize('vehicle,expected',[
    (dict(year=2015,make='Lexus',model='GS 350'),'Partial match'),
    (dict(year=2015,make='Lexus',model='GS 350',drivetrain='RWD'),'Not applicable'),
    (dict(year=2015,make='Lexus',model='GS 350',drivetrain='AWD'),'Candidate match'),
    (dict(year=2020,make='Honda',model='Civic'),'Not applicable')])
def test_applicability(vehicle,expected):
    reference=dict(year=2015,make='Lexus',model='GS 350',drivetrain='AWD')
    assert applicability(vehicle,reference)==expected
    if expected=='Candidate match':assert applicability(dict(vehicle,engine='3.5L V6'),reference,True)=='Verified applicability'
    if expected=='Candidate match':assert applicability(vehicle,reference,True)=='Partial match'
    assert applicability(vehicle,{})=='Unknown applicability'


def test_provider_failure_and_unrelated_vehicle():
    class Broken:
        def references(self,vehicle):raise OSError('offline')
    assert online_references({},[Broken()])[1]
    for vehicle in [dict(year=2001,make='Toyota',model='Tundra'),dict(year=2020,make='Honda',model='Civic'),dict(year=2022,make='Mazda',model='3')]:
        refs,errors=online_references(vehicle)
        assert len(refs)==4 and not errors
        assert all(not r.requirements for r in refs)


def make_v2(path):
    from types import SimpleNamespace
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute("INSERT INTO settings VALUES ('theme','light')");db.commit()
        Store._migrate_garage(SimpleNamespace(connection=db))
        db.execute("INSERT INTO vehicles VALUES ('00000000-0000-0000-0000-000000000001','Truck','truck',NULL,2006,'Ford','F-150','4.6L V8',NULL,'', 'mi','2026-01-01T00:00:00+00:00')")
        db.commit()


def test_v2_migration_preserves_records_and_v2_restore(tmp_path):
    original=tmp_path/'legacy.sqlite3';make_v2(original)
    original_bytes=original.read_bytes()
    with closing(Store(original)) as upgraded:
        assert Garage(upgraded).vehicles()[0]['engine']=='4.6L V8'
        backup=next(tmp_path.glob('legacy.pre-v3-*'))
        with closing(sqlite3.connect(backup)) as saved:
            assert saved.execute('PRAGMA user_version').fetchone()[0]==2
            assert saved.execute('SELECT engine FROM vehicles').fetchone()[0]=='4.6L V8'
        original_bytes=backup.read_bytes()
        assert Library(upgraded).documents()==[]
    with closing(Store(tmp_path/'current.sqlite3')) as current:
        current.restore(backup)
        assert Garage(current).vehicles()[0]['id']=='00000000-0000-0000-0000-000000000001'
        assert backup.read_bytes()==original_bytes


def test_failed_v3_migration_rolls_back(tmp_path,monkeypatch):
    source=tmp_path/'legacy.sqlite3';make_v2(source)
    def fail(db):
        db.execute('CREATE TABLE temporary_table (value TEXT)')
        raise sqlite3.OperationalError('injected')
    monkeypatch.setattr('openwrench.library_schema.create_library',fail)
    with pytest.raises(sqlite3.OperationalError):Store(source)
    with closing(sqlite3.connect(source)) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='temporary_table'").fetchone()
        assert db.execute('SELECT count(*) FROM vehicles').fetchone()[0]==1


@pytest.mark.parametrize('damage',['hash','bytes','association','schedule','path'])
def test_reject_malformed_library_restore(library,tmp_path,damage):
    lib,vehicle=library
    identifier=lib.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
    source=lib.store.backup(tmp_path/'bad.sqlite3')
    with closing(sqlite3.connect(source)) as db:
        if damage=='hash':db.execute("UPDATE documents SET sha256='invalid'")
        elif damage=='bytes':db.execute("UPDATE document_files SET content=x'0001'")
        elif damage=='association':db.execute("UPDATE document_vehicles SET vehicle_id='unknown'")
        elif damage=='path':db.execute("UPDATE documents SET sha256='../../outside'")
        elif damage=='schedule':db.execute("UPDATE documents SET applicability='[]'")
        db.commit()
    before=read_tables(lib.db)
    with pytest.raises((ValueError,sqlite3.Error)):lib.store.restore(source)
    assert read_tables(lib.db)==before


def test_document_cascade_does_not_delete_garage(library,tmp_path):
    lib,vehicle=library
    identifier=lib.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
    lib.bookmark('local',vehicle,identifier,1)
    Maintenance(lib.store).save(dict(vehicle_id=vehicle,title='Test',origin='User-defined',months_interval=3,procedure_id=identifier))
    lib.delete(identifier)
    assert Garage(lib.store).vehicle(vehicle)
    assert not list(lib.db.execute('SELECT * FROM bookmarks'))
    assert Maintenance(lib.store).rows(vehicle)[0]['procedure_id'] is None


def test_export_csv_library_metadata_without_content(library,tmp_path):
    import zipfile
    from openwrench.transfers import export_garage
    lib,vehicle=library
    lib.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
    target=export_garage(lib.store,tmp_path/'export.zip','csv')
    with zipfile.ZipFile(target) as archive:
        assert 'documents.csv' in archive.namelist()
        assert 'document_vehicles.csv' in archive.namelist()
        assert not any(name in archive.namelist() for name in ['document_files.csv','document_pages.csv'])
        assert b'Synthetic brake inspection' not in b''.join(archive.read(n) for n in archive.namelist())


def test_import_size_limit_and_failed_transaction(library,tmp_path,monkeypatch):
    lib,vehicle=library
    path=synthetic_pdf(tmp_path/'input.pdf')
    monkeypatch.setattr('openwrench.library.MAX_PDF_BYTES',10)
    with pytest.raises(ValueError,match='50 MiB'):lib.import_document(path,details(),[vehicle])
    monkeypatch.undo()
    def fail(*args):raise sqlite3.OperationalError('disk unavailable')
    monkeypatch.setattr(lib,'_pages',fail)
    with pytest.raises(sqlite3.OperationalError):lib.import_document(path,details(),[vehicle])
    assert not lib.documents() and not list(lib.db.execute('SELECT * FROM document_files'))


def test_readonly_copy_recovery_after_restore_to_other_directory(library,tmp_path):
    lib,vehicle=library
    identifier=lib.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
    source=lib.store.backup(tmp_path/'portable.sqlite3')
    with closing(Store(tmp_path/'other'/'workspace.sqlite3')) as target:
        target.restore(source)
        copy=Library(target).local_path(identifier)
        assert copy.exists() and copy.parent.parent==target.path.parent
        assert Library(target).search('brake')


def test_encrypted_pdf_rejected(library,tmp_path):
    import base64
    # Original synthetic one-page fixture, encrypted solely for rejection testing.
    content=base64.b64decode('JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgPDYwMWM1YWE3ZjA+Cj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9UeXBlIC9QYWdlcwovQ291bnQgMQovS2lkcyBbIDQgMCBSIF0KPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL0NhdGFsb2cKL1BhZ2VzIDIgMCBSCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9UeXBlIC9QYWdlCi9SZXNvdXJjZXMgPDwKPj4KL01lZGlhQm94IFsgMC4wIDAuMCAxMDAgMTAwIF0KL1BhcmVudCAyIDAgUgo+PgplbmRvYmoKNSAwIG9iago8PAovViAyCi9SIDMKL0xlbmd0aCAxMjgKL1AgNDI5NDk2NzI5MgovRmlsdGVyIC9TdGFuZGFyZAovTyA8NTQyMTc4Zjk2YTVhYWFmNmZlMGFmYzMzYzU1ZTFjOGQ0YTc2NDllZDY4NDU2YzRjMjdiMDc5NGRlOGM0ZTc5Yz4KL1UgPGY1NDZiNGUzYjA1ZmI3YTYyYjEwMzJmYmJmOTM5NzhiMjhiZjRlNWU0ZTc1OGE0MTY0MDA0ZTU2ZmZmYTAxMDg+Cj4+CmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA1OSAwMDAwMCBuIAowMDAwMDAwMTE4IDAwMDAwIG4gCjAwMDAwMDAxNjcgMDAwMDAgbiAKMDAwMDAwMDI2MSAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDYKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKL0lEIFsgPDMwMzkzNTMzMzE2NjYzMzg2MTM3MzAzMTYzMzczMDYyMzc2MzM3MzIzMzMwMzAzNjM4MzUzNjMyMzYzODY0NjM+IDwzMDM5MzUzMzMxNjY2MzM4NjEzNzMwMzE2MzM3MzA2MjM3NjMzNzMyMzMzMDMwMzYzODM1MzYzMjM2Mzg2NDYzPiBdCi9FbmNyeXB0IDUgMCBSCj4+CnN0YXJ0eHJlZgo0NzYKJSVFT0YK')
    source=tmp_path/'encrypted.pdf';source.write_bytes(content)
    lib,vehicle=library
    with pytest.raises(ValueError,match='password protected'):
        lib.import_document(source,details(),[vehicle])
    assert not lib.documents()


def test_initial_ford_provider_requires_unknown_configuration():
    vehicle=dict(year=2006,make='Ford',model='F-150',engine='4.6L V8')
    refs,_=online_references(vehicle)
    manuals=[r for r in refs if r.requirements]
    assert len(manuals)==2
    assert all(applicability(vehicle,r.requirements)=='Partial match' for r in manuals)
    assert applicability(dict(vehicle,drivetrain='4WD',engine_code='VIN W'),manuals[0].requirements)=='Not applicable'


def test_library_restore_failure_rolls_back_index_and_documents(library,tmp_path,monkeypatch):
    lib,vehicle=library
    lib.import_document(synthetic_pdf(tmp_path/'input.pdf'),details(),[vehicle])
    source=lib.store.backup(tmp_path/'safe.sqlite3')
    before=read_tables(lib.db)
    def fail(records):
        lib.db.execute('DELETE FROM library_fts')
        lib.db.execute('DELETE FROM documents')
        raise sqlite3.OperationalError('injected restore failure')
    monkeypatch.setattr(lib.store,'_replace_records',fail)
    with pytest.raises(ValueError,match='rolled back'):lib.store.restore(source)
    assert read_tables(lib.db)==before and lib.search('brake')

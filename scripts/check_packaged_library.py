"""Exercise the actual packaged PDF worker offline, with original synthetic data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_library import synthetic_pdf,details
from test_html_library import synthetic_html,synthetic_folder
from openwrench.storage import Store
from openwrench.library import Library


def main():
    executable=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='openwrench-packaged-') as temporary:
        directory=Path(temporary)
        database=directory/'workspace.sqlite3'
        with_store=Store(database);with_store.close()
        source=synthetic_pdf(directory/'original.pdf')
        def worker(job):
            request=directory/'request.json'
            request.write_text(json.dumps(dict(job,database=str(database))),'utf-8')
            result=subprocess.run([str(executable),'--pdf-worker',str(request)],capture_output=True,text=True,timeout=60,check=True)
            messages=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            if not messages or 'result' not in messages[-1]:raise RuntimeError('Packaged worker produced no result')
            return messages[-1]['result']
        identifier=worker(dict(operation='import',source=str(source),metadata=details(),vehicles=[]))
        result=worker(dict(operation='render',id=identifier,page=1,scale=1,output=str(directory/'page.raw')))
        assert result['width']==300 and (directory/'page.raw').stat().st_size>0
        store=Store(database)
        assert Library(store).search('brake')[0]['id']==identifier
        store.close()
        html=worker(dict(operation='import',source=str(synthetic_html(directory/'original.zip')),metadata=details(),vehicles=[]))
        materialized=worker(dict(operation='materialize',id=html))
        bundle=Path(materialized['root'] if isinstance(materialized,dict) else materialized)
        assert (bundle/'procedures'/'brake.htm').is_file()
        store=Store(database)
        assert Library(store).search('caliper')[0]['id']==html
        backup=store.backup(directory/'backup.sqlite3');store.close()
        restored=Store(directory/'restored.sqlite3');restored.restore(backup)
        assert Library(restored).local_path(html).is_dir()
        restored.close()
        folder=synthetic_folder(directory/'manual')
        (folder/'assets'/'nav.js').write_bytes(b'menu()')
        request=directory/'folder.json'
        request.write_text(json.dumps(dict(operation='import',source=str(folder),metadata=details(),vehicles=[],database=str(database))),'utf-8')
        result=subprocess.run([str(executable),'--pdf-worker',str(request)],capture_output=True,text=True,timeout=60,check=True)
        messages=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        notice=[m['notice'] for m in messages if 'notice' in m]
        assert notice and notice[0]['entry']=='index.html',notice
        assert 'assets/nav.js' in notice[0]['inactive']
        store=Store(database)
        library=Library(store)
        folder_ids=[d['id'] for d in library.documents() if d['format']=='html']
        assert len(folder_ids)==2
        newest=next(i for i in folder_ids if 'orphan/deep/extra.htm' in library.html_files(i))
        assert 'procedures/engine/head.htm' in library.html_files(newest)
        assert library.search('fictional clearance')[0]['id']==newest
        store.close()
        print('Packaged PDF render and HTML ZIP and folder import, search, extraction and portable restore passed.')


if __name__=='__main__':main()

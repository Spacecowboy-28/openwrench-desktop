"""Bounded, killable worker entry point. SQLite connections never cross threads."""
import json
from pathlib import Path
import sys
from contextlib import closing


def main(arguments):
    job = json.loads(Path(arguments[0]).read_text('utf-8'))
    def progress(current,total):
        print(json.dumps(dict(progress=current,total=total)),flush=True)
    try:
        from openwrench.library import Library
        from openwrench.storage import Store
        with closing(Store(Path(job['database']))) as store:
            library = Library(store)
            operation = job['operation']
            if operation == 'import':
                notice = {}
                result = library.import_document(job['source'],job['metadata'],job['vehicles'],progress,notice=notice)
                if notice:
                    print(json.dumps(dict(notice=notice)),flush=True)
            elif operation == 'index':
                library.reindex(job['id'],progress)
                result = job['id']
            elif operation == 'locate':
                library.locate(job['id'],job['source'])
                result = job['id']
            elif operation == 'render':
                from openwrench.pdf_engine import render
                result = render(library.local_path(job['id']),job['page'],job['scale'],job['output'])
            elif operation == 'materialize':
                from openwrench.html_bundle import inspect, read_bundle_dir
                root = library.local_path(job['id'])
                # Read and inspect the already-validated bundle here so the GUI
                # thread never re-inflates the ZIP or reparses every page.
                files = read_bundle_dir(root)
                issues = inspect(files)
                print(json.dumps(dict(bundle=dict(root=str(root),files=list(files)))),flush=True)
                result = dict(root=str(root),issues=issues)
            else:
                raise ValueError('Unknown document operation.')
        print(json.dumps(dict(result=result)),flush=True)
        return 0
    except Exception as error:
        print(json.dumps(dict(error=str(error))),flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

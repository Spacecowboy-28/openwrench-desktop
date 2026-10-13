import json
import os
from pathlib import Path
import subprocess
import sys


def test_native_event_loop_and_startup_persistence(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), QT_QPA_PLATFORM='offscreen')
    for _ in range(2):
        result = subprocess.run([sys.executable, '-m', 'openwrench', '--smoke-test', '--data-dir', str(tmp_path)], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['visible'] is True
    assert (tmp_path / 'openwrench.sqlite3').exists()
    assert (tmp_path / 'application.log').exists()


def test_startup_error_exits_without_hanging(tmp_path):
    (tmp_path / 'openwrench.sqlite3').write_bytes(b'broken')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), QT_QPA_PLATFORM='offscreen')
    result = subprocess.run([sys.executable, '-m', 'openwrench', '--smoke-test', '--data-dir', str(tmp_path)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert 'Startup failed' in result.stderr

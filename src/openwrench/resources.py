"""Locate bundled application resources in source checkouts and frozen builds.

PyInstaller extracts data files into ``sys._MEIPASS`` (onefile) or beside the
executable (onedir). A source checkout keeps them in the repository. This module is
the single place that knows both layouts, so callers never guess a path.
"""

import sys
from pathlib import Path

# Resource directory relative to the repository root and to the frozen bundle root.
RESOURCE_DIR = 'assets'


def resource_root():
    """Directory that holds packaged resources (``assets``), or the repo root."""
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle:
        return Path(bundle)
    # src/openwrench/resources.py -> repository root is three parents up.
    return Path(__file__).resolve().parents[2]


def resource_path(name):
    """Absolute path to a bundled resource, whether frozen or run from source."""
    candidate = resource_root() / RESOURCE_DIR / name
    if not candidate.exists():
        candidate = resource_root() / name
    return candidate


def icon_path():
    """Path to the application icon (.ico on Windows, .png elsewhere)."""
    preferred = 'openwrench.ico' if sys.platform.startswith('win') else 'openwrench.png'
    path = resource_path(preferred)
    if path.exists():
        return path
    for fallback in ('openwrench.png', 'openwrench.ico'):
        path = resource_path(fallback)
        if path.exists():
            return path
    return None


def application_icon():
    """Return a QIcon for the app, or an empty QIcon when no asset is available."""
    from PySide6.QtGui import QIcon
    path = icon_path()
    return QIcon(str(path)) if path else QIcon()

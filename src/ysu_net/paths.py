"""Paths for the editable checkout used by the Linux installer, or a frozen GUI bundle."""
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, "frozen", False))
# A PyInstaller bundle has no checkout; its executable directory is the stable root.
PROJECT_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]

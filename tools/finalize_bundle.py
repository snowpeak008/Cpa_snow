"""Compatibility entry point; package only reviewed Git tracked files."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('package_branch.py')), run_name='__main__')

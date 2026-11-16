"""Freeze the actually installed environment, excluding this editable project."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
result = subprocess.run([sys.executable,"-m","pip","freeze","--exclude-editable"],check=True,capture_output=True,text=True)
(root/"requirements.lock").write_text(
    "# Generated from verified Windows Python 3.12 environment; no guessed versions.\n"+result.stdout,
    encoding="utf-8")

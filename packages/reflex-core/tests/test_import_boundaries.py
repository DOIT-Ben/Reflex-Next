import json
import subprocess
import sys


def test_import_reflex_core_does_not_import_forbidden_dependencies():
    code = """
import json
import sys
import reflex_core
forbidden = [
    name for name in sys.modules
    if name == 'sqlite3'
    or name.startswith('PyQt')
    or name.startswith('PySide')
    or name == 'torch'
    or name.startswith('torch.')
    or name == 'sentence_transformers'
    or name.startswith('sentence_transformers.')
]
print(json.dumps(forbidden))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []

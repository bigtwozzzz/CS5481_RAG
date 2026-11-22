"""Native M4 interpreter selection must preserve environment isolation."""
import os
from pathlib import Path
import tempfile
import unittest

from scripts.m5_generation.b_cli import default_m4_python


class NativeInterpreterTests(unittest.TestCase):
    def test_dedicated_environment_preferred_to_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            executable=Path('Scripts/python.exe') if os.name=='nt' else Path('bin/python')
            for name in ('.venv','.venv_m4'):
                path=root/name/executable
                path.parent.mkdir(parents=True)
                path.touch()
            self.assertEqual(default_m4_python(root),root/'.venv_m4'/executable)

    def test_existing_legacy_environment_remains_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            executable=Path('Scripts/python.exe') if os.name=='nt' else Path('bin/python')
            path=root/'.venv'/executable
            path.parent.mkdir(parents=True)
            path.touch()
            self.assertEqual(default_m4_python(root),path)

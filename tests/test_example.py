"""The cross-restyle example's committed reports are what the tool produces from its committed profiles and texts."""
import subprocess
import sys
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/cross-restyle'


class ExampleTests(unittest.TestCase):
    def test_the_committed_reports_are_current(self):
        done = subprocess.run([sys.executable, str(EXAMPLE / 'run.py'), '--check'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == '__main__':
    unittest.main()

"""The website agrees with the code: its version, every command example, links, JSON, JSON-LD and public files."""
import subprocess
import sys
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / 'site'


class SiteTests(unittest.TestCase):
    def test_the_site_validates_against_the_code(self):
        done = subprocess.run([sys.executable, '-B', str(SITE / 'validate.py')], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == '__main__':
    unittest.main()

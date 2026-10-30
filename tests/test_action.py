"""The GitHub Action's script runs the command it names, splits its arguments like a shell and passes the exit status
through."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/cross-restyle'


def script():
    text = (ROOT / 'action.yml').read_text(encoding='utf-8')
    block = re.search(r'^      run: \|\n((?:        .*\n|\n)+)', text, re.M).group(1)
    return '\n'.join(line[8:] for line in block.splitlines())


@unittest.skipUnless(shutil.which('bash'), 'needs bash')
class ActionTests(unittest.TestCase):
    def run_action(self, command, args):
        env = dict(os.environ, MDRESTYLER_TOOL=str(ROOT / 'skills/mdrestyler/scripts/mdrestyler.py'),
                   MDRESTYLER_COMMAND=command, MDRESTYLER_ARGS=args)
        return subprocess.run(['bash', '-c', script()], cwd=EXAMPLE, env=env, capture_output=True, text=True, encoding='utf-8')

    def test_the_action_names_the_skill_script(self):
        self.assertIn('${{ github.action_path }}/skills/mdrestyler/scripts/mdrestyler.py', (ROOT / 'action.yml').read_text(encoding='utf-8'))
        self.assertTrue((ROOT / 'skills/mdrestyler/scripts/mdrestyler.py').is_file())

    def test_a_clear_check_passes_and_a_copy_guard_hit_fails(self):
        clear = self.run_action('check', "--profile profiles/james 'restyle/twain-to-james/take-2.md'")
        self.assertEqual(clear.returncode, 0, clear.stderr)
        self.assertIn('Copy guard: clear', clear.stdout)
        hit = self.run_action('check', '--profile profiles/twain passages/twain.md')
        self.assertEqual(hit.returncode, 1, hit.stderr)

    def test_an_error_exits_2(self):
        self.assertEqual(self.run_action('check', '--profile no-such-folder passages/twain.md').returncode, 2)


if __name__ == '__main__':
    unittest.main()

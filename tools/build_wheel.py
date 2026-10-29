#!/usr/bin/env python3
"""Build the wheel from the skill folder's own files: a staged copy of the repository in which the package also carries
the skill's MANIFEST.json, so `mdrestyler --version` installed from the wheel names the same digest. The skill folder
itself never holds that copy. Needs uv. Prints the wheel's path and SHA-256.

  python3 tools/build_wheel.py [--out dist]"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', default=str(ROOT / 'dist'))
    args = parser.parse_args()
    check = subprocess.run([sys.executable, str(ROOT / 'tools/manifest.py'), '--check'], capture_output=True, text=True)
    if check.returncode:
        sys.exit(check.stderr.strip() or 'the manifest is stale')
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / 'mdrestyler'
        stage.mkdir()
        for name in ('README.md', 'LICENSE', 'pyproject.toml'):
            shutil.copy(ROOT / name, stage / name)
        shutil.copytree(ROOT / 'skills', stage / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy(ROOT / 'skills/mdrestyler/MANIFEST.json', stage / 'skills/mdrestyler/scripts/mdrestyler/MANIFEST.json')
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(['uv', 'build', '--wheel', '--out-dir', str(out), str(stage)], check=True)
    wheel = max(out.glob('mdrestyler-*.whl'), key=lambda p: p.stat().st_mtime)
    print(wheel, hashlib.sha256(wheel.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()

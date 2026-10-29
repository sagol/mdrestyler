#!/usr/bin/env python3
"""Write skills/mdrestyler/MANIFEST.json: the SHA-256 of every file in the skill folder except the manifest itself
(_build.json included), sorted by path; print the manifest's own SHA-256, which consumers pin.

  python3 tools/manifest.py [--commit SHA]   (--commit also writes scripts/mdrestyler/_build.json first)
  python3 tools/manifest.py --check          (exit 1 when the manifest is stale)"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'mdrestyler'


def entries():
    out = {}
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT).as_posix()
        if path.is_dir() or rel == 'MANIFEST.json' or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            sys.exit(f'{rel} is a symbolic link; the skill ships regular files only')
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def receipt_problem():
    """Why scripts/mdrestyler/_build.json is not a source receipt, or None: it must hold this version and a full source
    commit (the commit of everything but the receipt and the manifest), and nothing else."""
    import re
    sys.path.insert(0, str(ROOT / 'scripts'))
    from mdrestyler import __version__
    try:
        build = json.loads((ROOT / 'scripts/mdrestyler/_build.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return f'scripts/mdrestyler/_build.json is missing or unreadable ({error}): run tools/manifest.py --commit <source commit>'
    if set(build) != {'commit', 'version'} or build['version'] != __version__ or not re.fullmatch('[0-9a-f]{40}', str(build['commit'])):
        return f'scripts/mdrestyler/_build.json must hold version {__version__} and a full source commit, nothing else'
    return None


def render(data):
    return (json.dumps(data, indent=1, sort_keys=True) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--commit', help='the frozen source commit to record in _build.json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.commit:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from mdrestyler import __version__
        (ROOT / 'scripts/mdrestyler/_build.json').write_bytes(render({'commit': args.commit, 'version': __version__}))
    receipt = receipt_problem()
    if receipt:
        sys.exit(receipt)
    data = render(entries())
    if args.check:
        current = (ROOT / 'MANIFEST.json').read_bytes() if (ROOT / 'MANIFEST.json').is_file() else b''
        if current != data:
            sys.exit('MANIFEST.json is stale: run tools/manifest.py')
    else:
        (ROOT / 'MANIFEST.json').write_bytes(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()

"""The mdrestyler command: one entry point for the scan, the checks and installing, with nothing installed but this
package. Standard library only."""
import hashlib
import json
import sys
from pathlib import Path

from . import __version__

USAGE = """usage: mdrestyler COMMAND [ARGS]

commands:
  scan      build an author profile from EPUB books or the author's own Markdown book
  check     measure drafts against a profile and run the copy guard; exit 1 on a shared run (--accepted for a revision)
  rank      order two or more takes of one unit by fit
  book      check every unit of a book in reading order, one row each (--list names the units)
  install   install a profile into a profile folder
  profile   validate a profile folder: profile validate FOLDER --lang ru
  verify    check this installation against its manifest (and --expect a manifest digest)

Each command's --help says more. mdrestyler --version prints the version, source commit and manifest digest."""


def skill_root():
    """The skill folder this package runs from, when it runs from one (scripts/mdrestyler/ inside it)."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / 'MANIFEST.json').is_file() else None


def build():
    try:
        return json.loads((Path(__file__).resolve().parent / '_build.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'version': __version__, 'commit': None}


def manifest_digest(root):
    return hashlib.sha256((root / 'MANIFEST.json').read_bytes()).hexdigest()


def installed_manifest():
    """The manifest a wheel carries beside the package (the skill's own, copied at build), or None."""
    path = Path(__file__).resolve().parent / 'MANIFEST.json'
    return path if path.is_file() else None


def verify(root, expect=None):
    """Problems with the installation at root against its manifest, and against expect (a manifest digest) when given."""
    problems = []
    digest = manifest_digest(root)
    if expect and digest != expect:
        problems.append(f'MANIFEST.json is {digest}, not the expected {expect}')
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    for name, want in sorted(manifest.items()):
        path = root / name
        if not path.is_file() or path.is_symlink():
            problems.append(f'{name} is missing')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != want:
            problems.append(f'{name} differs from the manifest')
    listed = set(manifest) | {'MANIFEST.json'}
    extra = sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                   and str(p.relative_to(root)) not in listed)
    problems += [f'{name} is not in the manifest' for name in extra]
    return problems


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    if command == '--version':
        info, root, carried = build(), skill_root(), installed_manifest()
        digest = (manifest_digest(root) if root else hashlib.sha256(carried.read_bytes()).hexdigest() if carried
                  else 'none: not run from a skill folder or a built wheel')
        print(f"mdrestyler {info.get('version', __version__)} (commit {info.get('commit') or 'unknown'}, manifest {digest})")
        return 0
    if command == 'scan':
        from . import scan
        return scan.main(rest, prog='mdrestyler scan')
    if command == 'check':
        from . import check
        return check.main(rest, prog='mdrestyler check')
    if command == 'rank':
        from . import check
        return check.main(['--rank'] + rest, prog='mdrestyler rank')
    if command == 'book':
        from . import check
        if not rest or rest[0].startswith('-'):
            print('usage: mdrestyler book BOOK --profile FOLDER --list UNITS [--within p90] [--json]', file=sys.stderr)
            return 2
        return check.main(['--book', rest[0]] + rest[1:], prog='mdrestyler book')
    if command == 'install':
        from . import install
        return install.main(rest)
    if command == 'profile':
        if not rest or rest[0] != 'validate' or len(rest) < 2:
            print('usage: mdrestyler profile validate FOLDER --lang ru', file=sys.stderr)
            return 2
        from . import profile
        from .metrics import required_lang
        lang = rest[rest.index('--lang') + 1] if '--lang' in rest[:-1] else None
        if not lang:
            print('mdrestyler profile validate: --lang is required', file=sys.stderr)
            return 2
        try:
            bundle = profile.load(rest[1], required_lang(lang))
        except (OSError, ValueError) as error:
            print(f'Profile not valid: {error}', file=sys.stderr)
            return 2
        print(json.dumps({'status': bundle['status'], 'revision': profile.revision(bundle)}, indent=2, ensure_ascii=False))
        return 0
    if command == 'verify':
        root = skill_root()
        if root is None:
            print('mdrestyler verify: not run from a skill folder; verify the skill folder that holds MANIFEST.json', file=sys.stderr)
            return 2
        expect = rest[rest.index('--expect') + 1] if '--expect' in rest[:-1] else None
        problems = verify(root, expect)
        for p in problems:
            print(p, file=sys.stderr)
        print(json.dumps({'root': str(root), 'manifest_sha256': manifest_digest(root), 'ok': not problems}, indent=2))
        return 1 if problems else 0
    print(f'mdrestyler: unknown command {command!r}\n\n{USAGE}', file=sys.stderr)
    return 2


def main_exit():
    """The installed command's entry point."""
    sys.exit(main())

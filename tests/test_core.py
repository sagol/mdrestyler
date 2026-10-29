"""What mdrestyler adds around the measures: the configured approval, layout, schemas and defaults, the shipped
defaults, the book's unit list, the own-book eligibility, and the command's version, verify and validate."""
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/mdrestyler'
SCRIPTS = SKILL / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from mdrestyler import check, names, profile  # noqa: E402
from mdrestyler.metrics import Budget  # noqa: E402

DEFAULTS = SCRIPTS / 'mdrestyler/defaults'


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, '-B', '-S', str(SCRIPTS / 'mdrestyler.py'), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


class Fresh(unittest.TestCase):
    """Each test starts from mdrestyler's own configuration and a scratch folder."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        saved = (names.PRODUCT, dict(names.COMMANDS), names.APPROVER, names.LAYOUT, names.EXTRA_PROFILE_SCHEMAS,
                 names.EXTRA_GUARD_SCHEMAS, names.KNOWN_DEFAULTS, names.REPORT_NOTE, names._CONFIGURED)
        names._CONFIGURED = None   # each test configures this process afresh
        self.addCleanup(self.restore, saved)

    @staticmethod
    def restore(saved):
        (names.PRODUCT, commands, names.APPROVER, names.LAYOUT, names.EXTRA_PROFILE_SCHEMAS, names.EXTRA_GUARD_SCHEMAS,
         names.KNOWN_DEFAULTS, names.REPORT_NOTE, names._CONFIGURED) = saved
        names.COMMANDS.clear()
        names.COMMANDS.update(commands)

    def profile_folder(self, source, lang='en'):
        folder = self.root / f'profile-{lang}'
        folder.mkdir()
        for name in (f'AUTHOR_PROFILE.{lang}.md', f'author-profile.{lang}.json'):
            shutil.copy(source / name, folder / name)
        return folder


class ApprovalTests(Fresh):
    DELEGATED = '# Profile\n\nStatus: draft.\n\n## Approval\n- Approved under delegation: DEC-07\n'

    def test_a_delegated_approval_approves_nothing_without_a_configured_product(self):
        self.assertEqual(profile.status(self.DELEGATED, self.root, 'AUTHOR_PROFILE.en.md'), 'draft')
        self.assertIn('none is configured', profile.delegated_approval('DEC-07', self.root, 'AUTHOR_PROFILE.en.md'))

    def test_the_configured_approver_decides_and_sees_the_folder_and_file(self):
        seen = []

        def approver(decision, folder, item):
            seen.append((decision, folder, item))
            return '' if decision == 'DEC-07' else 'not this one'
        names.configure(approver=approver)
        self.assertEqual(profile.status(self.DELEGATED, self.root, 'AUTHOR_PROFILE.en.md'), 'approved')
        self.assertEqual(seen, [('DEC-07', self.root, 'AUTHOR_PROFILE.en.md')])
        self.assertEqual(profile.status(self.DELEGATED.replace('DEC-07', 'DEC-08'), self.root, 'AUTHOR_PROFILE.en.md'), 'draft')

    def test_the_author_s_own_dated_approval_needs_no_product(self):
        text = '# Profile\n\nStatus: draft.\n\n## Approval\n- Approved by the author on: 2026-10-03\n'
        self.assertEqual(profile.status(text), 'approved')

    def test_a_process_is_configured_once_and_a_conflicting_call_changes_nothing(self):
        names.configure(product='Host A', approver=lambda decision, folder, item: 'never here')
        self.assertEqual(profile.status(self.DELEGATED, self.root, 'AUTHOR_PROFILE.en.md'), 'draft')
        names.configure(product='Host A', approver=names.APPROVER)   # the same settings: nothing changes
        with self.assertRaisesRegex(ValueError, 'already configured'):
            names.configure(product='Host B', approver=lambda decision, folder, item: '')
        with self.assertRaisesRegex(ValueError, 'already configured'):
            names.configure(product='Host A')   # partial: still another set of settings
        self.assertEqual(names.PRODUCT, 'Host A')
        self.assertEqual(profile.status(self.DELEGATED, self.root, 'AUTHOR_PROFILE.en.md'), 'draft')

    def test_invalid_settings_are_refused_before_anything_changes(self):
        for bad in ({'approver': 'not callable'}, {'layout': object()}, {'known_defaults': [('x', 'y')]},
                    {'commands': {'build': 'x'}}, {'profile_schemas': [1]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                names.configure(product='Host', **bad)
            self.assertEqual(names.PRODUCT, 'mdrestyler')
            self.assertIsNone(names._CONFIGURED)

    def test_configure_refuses_unknown_command_names_and_messages_use_the_configured_ones(self):
        with self.assertRaises(ValueError):
            names.configure(commands={'build': 'x'})
        names.configure(product='Host', commands={'scan': 'host-scan'})
        self.assertIn('host-scan', profile.rescan())
        self.assertEqual(names.command('check'), 'mdrestyler check')


class DefaultTests(Fresh):
    def test_shipped_defaults_name_mdrestyler_and_read_as_defaults(self):
        for lang in ('en', 'ru'):
            with self.subTest(lang=lang):
                text = (DEFAULTS / f'AUTHOR_PROFILE.{lang}.md').read_text(encoding='utf-8')
                self.assertIn('mdrestyler', text)
                bundle = profile.load(self.profile_folder(DEFAULTS, lang), lang)
                self.assertEqual(bundle['status'], 'default')
                self.assertEqual(bundle['profile']['schema'], 'mdrestyler-author-profile/1')

    def test_an_edited_default_or_one_with_a_guard_is_a_draft(self):
        folder = self.profile_folder(DEFAULTS, 'en')
        prose = folder / 'AUTHOR_PROFILE.en.md'
        prose.write_text(prose.read_text(encoding='utf-8') + '\nA line the author added.\n', encoding='utf-8')
        self.assertEqual(profile.load(folder, 'en')['status'], 'draft')
        prose_bytes, measures = (DEFAULTS / 'AUTHOR_PROFILE.ru.md').read_bytes(), (DEFAULTS / 'author-profile.ru.json').read_bytes()
        self.assertEqual(profile.classify(prose_bytes.decode('utf-8'), prose_bytes, measures, True, 'ru'), 'draft')
        self.assertEqual(profile.classify(prose_bytes.decode('utf-8'), prose_bytes, measures, False, 'ru'), 'default')

    def test_a_configured_product_s_own_defaults_stay_defaults_untouched(self):
        folder = self.profile_folder(DEFAULTS, 'en')
        prose = folder / 'AUTHOR_PROFILE.en.md'
        prose.write_text(prose.read_text(encoding='utf-8').replace('mdrestyler ships', 'Another tool ships'), encoding='utf-8')
        self.assertEqual(profile.load(folder, 'en')['status'], 'draft')
        pair = (hashlib.sha256(prose.read_bytes()).hexdigest(), hashlib.sha256((folder / 'author-profile.en.json').read_bytes()).hexdigest())
        names.configure(known_defaults=[pair])
        self.assertEqual(profile.load(folder, 'en')['status'], 'default')
        prose.write_text(prose.read_text(encoding='utf-8') + '\nEdited.\n', encoding='utf-8')
        self.assertEqual(profile.load(folder, 'en')['status'], 'draft')


class SchemaTests(Fresh):
    def test_only_mdrestyler_schemas_are_read_unless_a_product_adds_its_own(self):
        payload = json.loads((DEFAULTS / 'author-profile.en.json').read_text(encoding='utf-8'))
        profile.validate_profile(payload, 'en', 'x')
        for schema in ('mdrestyler-author-profile/2', 'other-author-profile/1'):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                profile.validate_profile(dict(payload, schema=schema), 'en', 'x')
        names.configure(profile_schemas=['other-author-profile/1'])
        profile.validate_profile(dict(payload, schema='other-author-profile/1'), 'en', 'x')

    def test_guard_schemas_likewise(self):
        guard = {'language': 'en', 'run_words': 8, 'window': profile.WINDOW, 'catches_runs_of': profile.CAUGHT, 'hashes': ['0123456789ab']}
        profile.validate_guard(dict(guard, schema='mdrestyler-copy-guard/1'), 'en', 'x')
        with self.assertRaises(ValueError):
            profile.validate_guard(dict(guard, schema='other-copy-guard/1'), 'en', 'x')
        names.configure(guard_schemas=['other-copy-guard/1'])
        profile.validate_guard(dict(guard, schema='other-copy-guard/1'), 'en', 'x')
        self.assertEqual(profile.guard_schemas(), ('mdrestyler-copy-guard/1', 'other-copy-guard/1'))


class UnitListTests(Fresh):
    def book(self):
        bk = self.root / 'book'
        bk.mkdir()
        for name in ('01.md', '02.md'):
            (bk / name).write_text(f'# {name}\n\nText.\n', encoding='utf-8')
        (bk / 'notes.txt').write_text('x', encoding='utf-8')
        return bk

    def test_the_list_gives_the_order_and_skips_blank_and_comment_lines(self):
        bk = self.book()
        listing = self.root / 'units.txt'
        listing.write_text('# order\n02.md\n\n01.md\n', encoding='utf-8')
        self.assertEqual([p.name for p in check.list_units(bk, listing)], ['02.md', '01.md'])

    def test_an_entry_outside_missing_repeated_or_not_markdown_stops_the_table(self):
        bk = self.book()
        (self.root / 'outside.md').write_text('# x\n', encoding='utf-8')
        for body, why in (('../outside.md\n', 'outside the book'), ('03.md\n', 'not a Markdown file'), ('01.md\n01.md\n', 'twice'),
                          ('notes.txt\n', 'not a Markdown file'), ('\n# none\n', 'lists no units')):
            with self.subTest(body=body):
                listing = self.root / 'units.txt'
                listing.write_text(body, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, why):
                    check.list_units(bk, listing)

    def test_the_book_command_needs_a_list_and_a_profile(self):
        bk = self.book()
        result = cli('book', bk, '--profile', DEFAULTS)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--list', result.stderr)
        result = cli('book', bk, '--list', self.root / 'units.txt')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--profile is required', result.stderr)


class OwnBookTests(Fresh):
    def setUp(self):
        super().setUp()
        self.bk = self.root / 'book'
        self.bk.mkdir()
        self.text = '# One\n\n' + 'She waited by the gate and watched the road. ' * 30 + '\n'
        (self.bk / '01.md').write_text(self.text, encoding='utf-8')
        self.units = {'01.md': {'eligible': True, 'sha256': hashlib.sha256(self.text.encode()).hexdigest(), 'exclude': []}}

    def read(self, **extra):
        from mdrestyler import scan
        eligibility = self.root / 'eligibility.json'
        eligibility.write_text(json.dumps({'decision': 'Author confirmation 2026-10-01', 'language': 'en', 'units': self.units, **extra}))
        return scan.read_imported(self.bk, eligibility, Budget())

    def test_the_eligibility_record_gives_the_order_and_title(self):
        meta, chapters = self.read(order=['01.md'], title='Mine')
        self.assertEqual(meta['title'], 'Mine')
        self.assertEqual([c['source_unit'] for c in chapters if not c['apparatus']], ['01.md'])
        meta, _ = self.read(order=['01.md'])
        self.assertEqual(meta['title'], 'book')

    def test_without_an_order_or_with_an_import_record_the_book_is_refused(self):
        with self.assertRaisesRegex(ValueError, '"order" must list'):
            self.read()
        with self.assertRaisesRegex(ValueError, 'only the tool that wrote it'):
            self.read(order=['01.md'], record='review/import/x/record.json')
        with self.assertRaisesRegex(ValueError, 'not in the eligibility order'):
            self.read(order=['02.md'])

    def test_a_scan_never_writes_inside_the_book_it_reads_or_beside_its_sources(self):
        (self.bk / 'samples.en.md').write_text(self.text, encoding='utf-8')
        before = {p.name: p.read_bytes() for p in self.bk.iterdir()}
        eligibility = self.root / 'eligibility.json'
        units = {'samples.en.md': {'eligible': True, 'sha256': hashlib.sha256(self.text.encode()).hexdigest(), 'exclude': []}}
        eligibility.write_text(json.dumps({'decision': 'Author confirmation 2026-10-01', 'language': 'en', 'units': units,
                                           'order': ['samples.en.md']}))
        alias = self.root / 'alias'
        alias.symlink_to(self.bk)
        for out, work in ((self.root / 'out', self.bk), (self.bk, self.root / 'work'), (self.root / 'out', self.bk / 'sub'),
                          (self.root / 'out', alias)):
            with self.subTest(out=str(out), work=str(work)):
                result = cli('scan', '--own-book', self.bk, '--eligibility', eligibility, '--out', out, '--work', work, '--min-words', 10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('inside the book being scanned', result.stderr)
                self.assertEqual({p.name: p.read_bytes() for p in self.bk.iterdir()}, before)
        books = self.root / 'books'
        books.mkdir()
        (books / 'mine.epub').write_bytes(b'not read: refused first')
        result = cli('scan', '--own', books / 'mine.epub', '--out', self.root / 'out2', '--work', books)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('holds the source', result.stderr)

    def test_the_default_layout_knows_no_book(self):
        self.assertIsNone(names.LAYOUT.inside_book(self.bk))


class CommandTests(Fresh):
    def copy_skill(self):
        dest = self.root / 'mdrestyler'
        shutil.copytree(SKILL, dest, ignore=shutil.ignore_patterns('__pycache__'))
        return dest

    def test_version_names_the_manifest_digest_of_the_skill_it_runs_from(self):
        dest = self.copy_skill()
        result = subprocess.run([sys.executable, '-B', '-S', str(dest / 'scripts/mdrestyler.py'), '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(hashlib.sha256((dest / 'MANIFEST.json').read_bytes()).hexdigest(), result.stdout)

    def test_verify_passes_a_clean_copy_and_names_a_changed_or_added_file(self):
        dest = self.copy_skill()
        run = lambda *a: subprocess.run([sys.executable, '-B', '-S', str(dest / 'scripts/mdrestyler.py'), 'verify', *a], capture_output=True, text=True)
        self.assertEqual(run().returncode, 0, run().stderr)
        digest = hashlib.sha256((dest / 'MANIFEST.json').read_bytes()).hexdigest()
        self.assertEqual(run('--expect', digest).returncode, 0)
        self.assertEqual(run('--expect', '0' * 64).returncode, 1)
        (dest / 'scripts/mdrestyler/check.py').write_text('# changed\n', encoding='utf-8')
        self.assertIn('check.py differs', run().stderr)
        (dest / 'scripts/mdrestyler/extra.py').write_text('', encoding='utf-8')
        self.assertIn('extra.py is not in the manifest', run().stderr)

    def test_the_manifest_is_current(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/manifest.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_validate_reports_the_status_or_why_not(self):
        result = cli('profile', 'validate', DEFAULTS, '--lang', 'en')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'default')
        result = cli('profile', 'validate', self.root, '--lang', 'en')
        self.assertEqual(result.returncode, 2)

    def test_the_package_runs_from_its_skill_folder_without_site_packages_or_the_cwd(self):
        (self.root / 'mdrestyler').mkdir()
        (self.root / 'mdrestyler/__init__.py').write_text('raise SystemExit("the cwd package was imported")\n')
        result = cli('--help', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: mdrestyler', result.stdout)

    def test_the_package_and_the_wheel_carry_one_version(self):
        import re
        from mdrestyler import __version__
        self.assertEqual(re.search(r'^version = "([^"]+)"', (ROOT / 'pyproject.toml').read_text(), re.M).group(1), __version__)

    def test_compiled_caches_beside_the_skill_are_never_run(self):
        import importlib.util
        import os
        import py_compile
        dest = self.copy_skill()
        init = dest / 'scripts/mdrestyler/__init__.py'
        real, stamp = init.read_bytes(), init.stat().st_mtime_ns
        init.write_bytes(real.replace(b"'0.1.0'", b"'9.9.9'"))   # same size
        os.utime(init, ns=(stamp, stamp))
        py_compile.compile(str(init), cfile=importlib.util.cache_from_source(str(init)), doraise=True)
        init.write_bytes(real)
        os.utime(init, ns=(stamp, stamp))   # the cache now looks current for the real source
        result = subprocess.run([sys.executable, str(dest / 'scripts/mdrestyler.py'), '--version'], capture_output=True, text=True)
        self.assertIn('mdrestyler 0.1.0', result.stdout, result.stderr)

    def test_the_skill_carries_its_source_receipt(self):
        build = json.loads((SCRIPTS / 'mdrestyler/_build.json').read_text())
        self.assertEqual(set(build), {'commit', 'version'})
        self.assertRegex(build['commit'], r'^[0-9a-f]{40}$')
        result = subprocess.run([sys.executable, '-B', '-S', str(self.copy_skill() / 'scripts/mdrestyler.py'), '--version'],
                                capture_output=True, text=True)
        self.assertIn(f"commit {build['commit']}", result.stdout)

    def test_an_unknown_command_exits_2(self):
        self.assertEqual(cli('restyle').returncode, 2)


if __name__ == '__main__':
    unittest.main()

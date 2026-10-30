#!/usr/bin/env python3
"""Check the site against the checked-out code. Standard library only; documentation is parsed, never executed.

It checks that the version on the site is mdrestyler.__version__, that every `mdrestyler COMMAND ...` example names a
real command and real flags (and that complete examples get past the command's own argument checks), that local links,
fragment ids and repository links resolve, that ARIA and copy targets exist, that JSON, JSON-LD, the sitemap and the
SVGs parse, that the page makes no third-party request and keeps a strict CSP, that heading levels do not skip, that
the theme colors keep 4.5:1 contrast, and that stage.PUBLIC_FILES exist. It exits 1 with a list of problems."""
import ast
import contextlib
import io
import json
import re
import shlex
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True   # leave no cache beside the skill's verified sources
SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
SCRIPTS = ROOT / 'skills' / 'mdrestyler' / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SITE)]

import mdrestyler  # noqa: E402
from mdrestyler import check as check_module, cli, install as install_module, profile as profile_module  # noqa: E402
from mdrestyler import scan as scan_module  # noqa: E402
from stage import PUBLIC_FILES  # noqa: E402

VERSION = mdrestyler.__version__
BASE = 'https://sagol.github.io/mdrestyler/'
REPO_PREFIXES = (('https://github.com/sagol/mdrestyler/blob/main/', 'file'),
                 ('https://github.com/sagol/mdrestyler/tree/main/', 'dir'),
                 ('https://raw.githubusercontent.com/sagol/mdrestyler/main/', 'file'))
TEXT_FILES = ('index.html', 'llms.txt', 'llms-full.txt', 'agents.json', '.well-known/agent.json', 'site.webmanifest',
              'og-image.svg', 'favicon.svg', 'robots.txt', 'sitemap.xml', 'styles.css', 'app.js', 'README.md')
# The repository test forbids these in any file; spelled in pieces so this file passes it too.
FORBIDDEN = re.compile('|'.join(['md' + 'bindery', 'md' + 'narra', 'md' + 'editorial', '/run/' + 'media', '/ho' + 'me/']), re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.references, self.targets, self.headings = [], [], [], []
        self.blocks, self.inline_code, self.json_ld, self.problems = [], [], [], []
        self.tabs, self.panels, self.csp, self.lang = {}, {}, None, None
        self.resources = []   # (tag, url) the browser loads
        self._pre = self._code = self._script = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html':
            self.lang = a.get('lang')
        if 'id' in a:
            self.ids.append(a['id'])
        for key in ('href', 'src', 'cite'):
            if a.get(key):
                self.references.append(a[key])
        for key in ('aria-controls', 'aria-labelledby', 'aria-describedby', 'data-copy-target'):
            self.targets.extend(a.get(key, '').split())
        if 'style' in a:
            self.problems.append(f'inline style attribute on <{tag}> (the CSP blocks it)')
        for key in a:
            if key.startswith('on'):
                self.problems.append(f'inline event handler {key} on <{tag}> (the CSP blocks it)')
        if re.fullmatch(r'h[1-6]', tag):
            self.headings.append(int(tag[1]))
        if tag == 'img':
            if 'alt' not in a:
                self.problems.append(f'<img src="{a.get("src")}"> has no alt attribute')
            self.resources.append(('img', a.get('src', '')))
        if tag == 'link' and set((a.get('rel') or '').split()) & {'stylesheet', 'icon', 'manifest', 'preload', 'modulepreload'}:
            self.resources.append(('link', a.get('href', '')))
        if tag == 'meta' and (a.get('http-equiv') or '').lower() == 'content-security-policy':
            self.csp = a.get('content', '')
        if tag == 'style':
            self.problems.append('<style> element (keep styles in styles.css)')
        if tag == 'script':
            if a.get('type') == 'application/ld+json':
                self._script = []
            elif a.get('src'):
                self.resources.append(('script', a['src']))
            else:
                self.problems.append('inline <script> (the CSP allows only local script files)')
        if a.get('role') == 'tab':
            self.tabs[a.get('id')] = a.get('aria-controls')
        if a.get('role') == 'tabpanel':
            self.panels[a.get('id')] = a.get('aria-labelledby')
        if tag == 'pre':
            self._pre = []
        if tag == 'code' and self._pre is None:
            self._code = []

    def handle_endtag(self, tag):
        if tag == 'pre' and self._pre is not None:
            self.blocks.append(''.join(self._pre))
            self._pre = None
        if tag == 'code' and self._code is not None:
            self.inline_code.append(''.join(self._code))
            self._code = None
        if tag == 'script' and self._script is not None:
            self.json_ld.append(''.join(self._script))
            self._script = None

    def handle_data(self, text):
        for buffer in (self._pre, self._code, self._script):
            if buffer is not None:
                buffer.append(text)


class Reached(BaseException):
    """Raised where a command would start its work: the example got past every argument check."""


class Captured(BaseException):
    def __init__(self, parser):
        super().__init__()
        self.parser = parser


def cli_commands():
    """The command names cli.main dispatches on, read from its source."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding='utf-8'))
    names = {'-h', '--help'}
    branches = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
                and node.test.left.id == 'command' and isinstance(node.test.ops[0], ast.Eq):
            name = node.test.comparators[0].value
            names.add(name)
            branches[name] = {n.value for b in node.body for n in ast.walk(b)
                              if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r'--[a-z][a-z-]*', n.value)}
    return names, branches


def argparse_flags(command):
    """The option strings of the parser a command builds, captured before it parses anything."""
    argv = [command] + (['BOOK'] if command == 'book' else [])
    with mock.patch('argparse.ArgumentParser.parse_args', lambda self, *a, **k: (_ for _ in ()).throw(Captured(self))), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            cli.main(argv)
        except Captured as captured:
            return set(captured.parser._option_string_actions)
    return None


def dry_run(args):
    """Run cli.main on args with every command's work replaced by Reached. Returns None when the arguments pass."""
    stop = lambda *a, **k: (_ for _ in ()).throw(Reached())
    patches = [mock.patch.object(scan_module, 'scan', stop), mock.patch.object(check_module, 'check', stop),
               mock.patch.object(check_module, 'rank', stop), mock.patch.object(check_module, 'book_check', stop),
               mock.patch.object(check_module, 'list_units', stop), mock.patch.object(install_module, 'install', stop),
               mock.patch.object(profile_module, 'load', stop), mock.patch.object(cli, 'verify', stop)]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        try:
            code = cli.main(list(args))
        except Reached:
            return None
        except SystemExit as exc:
            code = exc.code
    if code in (0, None):
        return None
    message = (err.getvalue().strip().splitlines() or ['exit status %s' % code])[-1]
    return message


def contrast(a, b):
    def lum(color):
        r, g, b_ = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(rgba, under):
    r, g, b, alpha = rgba
    base = [int(under[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(alpha * c + (1 - alpha) * u):02x}' for c, u in zip((r, g, b), base))


def theme_tokens(css):
    def block(selector):
        match = re.search(re.escape(selector) + r'\s*\{(.*?)\}', css, re.S)
        return dict(re.findall(r'(--[\w-]+):\s*([^;]+);', match.group(1))) if match else {}
    dark = block(':root')
    light = dict(dark, **block('[data-theme="light"]'))
    return {'dark': dark, 'light': light}


def main():
    errors = []
    counts = Counter()

    def require(condition, message):
        if not condition:
            errors.append(message)

    # Public files
    for name in PUBLIC_FILES:
        p = SITE / name
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(SITE), f'public file missing or outside site/: {name}')

    # Words and paths the repository forbids
    for p in sorted(SITE.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            found = FORBIDDEN.search(p.read_bytes().decode('utf-8', errors='replace'))
            require(not found, f'{p.relative_to(SITE)}: holds a forbidden word or path: {found and found.group(0)!r}')

    html = (SITE / 'index.html').read_text(encoding='utf-8')
    page = Page()
    page.feed(html)
    errors.extend(f'index.html: {p}' for p in page.problems)
    require(page.lang == 'en', 'index.html: <html lang="en"> missing')
    require(not [k for k, n in Counter(page.ids).items() if n > 1], f'index.html: duplicate ids: {[k for k, n in Counter(page.ids).items() if n > 1]}')
    ids = set(page.ids)

    # Headings: one h1, no skipped level
    require(page.headings.count(1) == 1, f'index.html: expected one h1, found {page.headings.count(1)}')
    for before, after in zip(page.headings, page.headings[1:]):
        require(after <= before + 1, f'index.html: heading level skips from h{before} to h{after}')

    # CSP and third-party requests
    csp = page.csp or ''
    require(bool(csp), 'index.html: no Content-Security-Policy meta element')
    require("'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp, 'index.html: the CSP allows inline code')
    require(not re.search(r'https?:', csp), 'index.html: the CSP allows a remote origin')
    for directive in ('script-src', 'style-src', 'object-src', 'base-uri'):
        require(directive in csp, f'index.html: the CSP lacks {directive}')
    for tag, url in page.resources:
        require(bool(url) and not urlsplit(url).scheme and not url.startswith('//'), f'index.html: <{tag}> loads a remote resource: {url}')
    require(not re.search(r'url\(\s*[\'"]?(?:https?:)?//', (SITE / 'styles.css').read_text(encoding='utf-8')), 'styles.css: loads a remote resource')
    require(not re.search(r'\b(fetch|XMLHttpRequest|import\s*\(|sendBeacon)\b', (SITE / 'app.js').read_text(encoding='utf-8')), 'app.js: makes a network request')

    # ARIA and copy targets, tabs
    for target in page.targets:
        require(target in ids, f'index.html: ARIA or copy target missing: {target}')
    for tab, panel in page.tabs.items():
        require(page.panels.get(panel) == tab, f'index.html: tab {tab} and panel {panel} do not point at each other')

    # Links
    def resolve(reference, where):
        url = urlsplit(reference)
        if reference.startswith(BASE):
            name = unquote(reference[len(BASE):].split('#')[0]) or 'index.html'
            require(name in PUBLIC_FILES, f'{where}: site link to a file that is not published: {reference}')
            if name == 'index.html' and url.fragment:
                require(unquote(url.fragment) in ids, f'{where}: broken fragment: {reference}')
            return
        for prefix, kind in REPO_PREFIXES:
            if reference.startswith(prefix):
                path = ROOT / unquote(reference[len(prefix):].split('#')[0].split('?')[0])
                ok = path.is_file() if kind == 'file' else path.is_dir()
                require(ok and path.resolve().is_relative_to(ROOT), f'{where}: repository link to a missing {kind}: {reference}')
                return
        if url.scheme or url.netloc or reference.startswith('mailto:'):
            return
        name = unquote(url.path).lstrip('/') or 'index.html'
        if name in ('.', './'):
            name = 'index.html'
        require(name in PUBLIC_FILES, f'{where}: link target is not a published file: {reference}')
        if name == 'index.html' and url.fragment:
            require(unquote(url.fragment) in ids, f'{where}: broken fragment: {reference}')

    for reference in page.references:
        resolve(reference, 'index.html')
        counts['links'] += 1

    # JSON-LD
    require(bool(page.json_ld), 'index.html: no JSON-LD')
    types = set()
    for text in page.json_ld:
        try:
            data = json.loads(text)
        except ValueError as exc:
            errors.append(f'index.html: JSON-LD does not parse: {exc}')
            continue
        for node in data.get('@graph', []):
            types.add(node.get('@type'))
            if node.get('@type') == 'SoftwareApplication':
                require(node.get('softwareVersion') == VERSION, f'JSON-LD softwareVersion {node.get("softwareVersion")} is not {VERSION}')
                require(node.get('downloadUrl') == 'https://pypi.org/project/mdrestyler/', 'JSON-LD downloadUrl is not the PyPI page')
            if node.get('@type') == 'SoftwareSourceCode':
                require(node.get('version') == VERSION, f'JSON-LD SoftwareSourceCode version {node.get("version")} is not {VERSION}')
            if node.get('@type') == 'FAQPage':
                visible = re.findall(r'<summary>(.*?)</summary>', html)
                asked = [q['name'] for q in node.get('mainEntity', [])]
                require(asked == visible, 'JSON-LD FAQ questions differ from the visible FAQ')
            def urls(value, key=None):
                if isinstance(value, dict):
                    for k, v in value.items():
                        yield from urls(v, k)
                elif isinstance(value, list):
                    for v in value:
                        yield from urls(v, key)
                elif isinstance(value, str) and key != '@id' and value.startswith('https://'):
                    yield value
            for value in urls(node):   # an @id names a node; it is not a page anchor
                resolve(value, 'JSON-LD')
    for wanted in ('WebSite', 'SoftwareApplication', 'SoftwareSourceCode', 'HowTo', 'FAQPage'):
        require(wanted in types, f'JSON-LD has no {wanted}')

    # Versions: every x.y.z on the site is the package's version
    for name in TEXT_FILES:
        text = (SITE / name).read_text(encoding='utf-8')
        for found in sorted(set(re.findall(r'(?<![\d.])v?(\d+\.\d+\.\d+)(?![\d.])', text))):
            require(found == VERSION, f'{name}: version {found} is not mdrestyler.__version__ {VERSION}')
    require(f'v{VERSION}' in html, f'index.html does not show v{VERSION}')

    # JSON files
    manifests = {}
    for name in ('agents.json', '.well-known/agent.json', 'site.webmanifest'):
        try:
            manifests[name] = data = json.loads((SITE / name).read_text(encoding='utf-8'))
        except ValueError as exc:
            errors.append(f'{name}: does not parse: {exc}')
            continue
        if 'version' in data:
            require(data['version'] == VERSION, f'{name}: version {data["version"]} is not {VERSION}')
        for icon in data.get('icons', []):
            resolve(icon['src'], name)

        def walk(value):
            if isinstance(value, dict):
                for v in value.values():
                    yield from walk(v)
            elif isinstance(value, list):
                for v in value:
                    yield from walk(v)
            elif isinstance(value, str):
                yield value
        for value in walk(data):
            if value.startswith('https://'):
                resolve(value, name)
    agents = manifests.get('agents.json', {})

    # Sitemap and robots
    try:
        tree = ET.parse(SITE / 'sitemap.xml')
        for loc in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
            require(loc.text.startswith(BASE), f'sitemap.xml: {loc.text} is outside the site')
            resolve(loc.text, 'sitemap.xml')
    except ET.ParseError as exc:
        errors.append(f'sitemap.xml: does not parse: {exc}')
    require(f'Sitemap: {BASE}sitemap.xml' in (SITE / 'robots.txt').read_text(encoding='utf-8'), 'robots.txt: no Sitemap line')

    # Images
    for name in ('favicon.svg', 'og-image.svg'):
        try:
            ET.parse(SITE / name)
        except ET.ParseError as exc:
            errors.append(f'{name}: does not parse: {exc}')
    png = (SITE / 'og-image.png').read_bytes()
    require(png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (1200, 630), 'og-image.png is not a 1200x630 PNG')

    # Contrast
    tokens = theme_tokens((SITE / 'styles.css').read_text(encoding='utf-8'))
    for theme, t in tokens.items():
        pairs = [(fg, bg) for fg in ('--text-primary', '--text-secondary', '--text-muted', '--accent')
                 for bg in ('--bg-primary', '--bg-secondary', '--bg-tertiary')]
        pairs += [('--accent-fg', '--accent-solid'), ('--accent-fg', '--accent-solid-hover'), ('--accent-hover', '--bg-primary')]
        for fg, bg in pairs:
            ratio = contrast(t[fg], t[bg])
            require(ratio >= 4.5, f'styles.css: {theme} theme {fg} on {bg} has contrast {ratio:.2f}, under 4.5')
        for status in ('pass', 'warn', 'err', 'info'):
            rgba = re.match(r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)', t[f'--status-{status}-bg'])
            for surface in ('--bg-secondary', '--bg-tertiary'):
                under = blend((int(rgba[1]), int(rgba[2]), int(rgba[3]), float(rgba[4])), t[surface])
                ratio = contrast(t[f'--status-{status}'], under)
                require(ratio >= 4.5, f'styles.css: {theme} theme badge {status} on {surface} has contrast {ratio:.2f}, under 4.5')
        counts['contrast pairs'] += len(pairs) + 8

    # LLM files: structure, links, code
    blocks = [('index.html', b) for b in page.blocks]
    inline = [('index.html', c) for c in page.inline_code]
    for name in ('llms.txt', 'llms-full.txt'):
        text = (SITE / name).read_text(encoding='utf-8')
        require(text.startswith('# mdrestyler'), f'{name}: must start with "# mdrestyler"')
        fence = re.compile(r'^[ \t]*```[^\n]*\n(.*?)^[ \t]*```[ \t]*$', re.S | re.M)
        blocks.extend((name, b) for b in fence.findall(text))
        prose = fence.sub('', text)
        inline.extend((name, c) for c in re.findall(r'`([^`\n]+)`', prose))
        for reference in re.findall(r'\]\(([^)\s]+)\)', prose) + re.findall(r'(?<![(<])\bhttps://[^\s)`>]+', prose):
            resolve(reference.rstrip('.,;:'), name)
            counts['links'] += 1
    require(re.search(r'^> \S', (SITE / 'llms.txt').read_text(encoding='utf-8'), re.M), 'llms.txt: no "> " summary line')
    for value in agents.get('cli_commands', {}).values():
        inline.append(('agents.json', value.get('syntax', '')))
    for value in agents.get('install', {}).values():
        if 'uses: sagol/mdrestyler' in value:
            blocks.append(('agents.json', value))

    # Commands and flags
    commands, branches = cli_commands()
    flags = {}
    for name in commands - {'-h', '--help', '--version'}:
        found = argparse_flags(name)
        flags[name] = found if found is not None else branches.get(name, set())
    require(flags.get('check') and '--profile' in flags['check'], 'could not read the check command\'s flags')

    def tokens_of(line):
        line = re.sub(r'^\s*(?:\$\s*|- run:\s*)', '', line).strip()
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|<>')
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return None
        segments, segment = [], []
        for token in tokens + [';']:
            if token and all(c in ';&|<>' for c in token):
                segments.append(segment)
                segment = []
            else:
                segment.append(token)
        out = []
        for args in segments:
            if args[:1] == ['mdrestyler']:
                out.append(args[1:])
            elif len(args) > 1 and args[0] in ('python3', 'python') and args[1].endswith('mdrestyler.py'):
                out.append(args[2:])
        return out

    def check_flags(where, line, args):
        if not args:
            return
        command = args[0]
        if re.fullmatch(r'[A-Z][A-Z_]*', command):   # a placeholder such as COMMAND
            return
        if command not in commands:
            errors.append(f'{where}: unknown command {command!r}: {line}')
            return
        if command == 'profile':
            require(args[1:2] == ['validate'], f'{where}: profile takes validate: {line}')
        known = flags.get(command, set()) | ({'-h', '--help'} if command not in ('profile', 'verify') else set())
        for token in args[1:]:
            token = token.strip('[](){}|,.;')
            if token.startswith('-') and token not in ('-', '--') and not re.fullmatch(r'-?\d+(\.\d+)?', token):
                flag = token.split('=')[0]
                require(flag in known, f'{where}: {command} has no flag {flag}: {line}')
        counts['commands'] += 1

    placeholder = re.compile(r'[\[\]…()]|\.\.\.|<[^>\s]+>')
    command_line = re.compile(r'(^|[;&|]\s*)(\$\s*)?(mdrestyler|python3? \S*mdrestyler\.py)(\s|$)')
    for where, block in blocks:
        if 'uses: sagol/mdrestyler@' in block:
            command = re.search(r'^\s*command:\s*["\']?([\w-]+)', block, re.M)
            argline = re.search(r'^\s*args:\s*(.*)$', block, re.M)
            args = [command.group(1) if command else 'check'] + (shlex.split(argline.group(1).strip()) if argline else [])
            if len(args) == 1 or args[1:2] == ['']:
                args = args[:1]
            check_flags(where, 'action: ' + ' '.join(args), args)
            problem = dry_run(args)
            require(problem is None, f'{where}: action example fails the argument checks ({problem}): {" ".join(args)}')
            counts['complete examples'] += 1
            continue
        for line in re.sub(r'\\\n\s*', ' ', block).splitlines():   # join backslash continuations
            if not command_line.search(line.strip()):
                continue
            found = tokens_of(line)
            if found is None:
                require('mdrestyler' not in line.split('#')[0], f'{where}: malformed shell quoting: {line}')
                continue
            for args in found:
                check_flags(where, line, args)
                if args and not placeholder.search(line):
                    problem = dry_run(args)
                    require(problem is None, f'{where}: example fails the argument checks ({problem}): {line.strip()}')
                    counts['complete examples'] += 1
    for where, code in inline:
        if re.match(r'(mdrestyler|python3? \S*mdrestyler\.py) ', code):
            for args in tokens_of(placeholder.sub(lambda m: m.group(0) if m.group(0).startswith('<') else ' ', code)) or []:
                check_flags(where, code, args)

    # Coverage: every command and flag is documented
    full = (SITE / 'llms-full.txt').read_text(encoding='utf-8')
    table_rows = re.search(r'<tbody id="command-rows">(.*?)</tbody>', html, re.S)
    first_cells = re.findall(r'<tr>\s*<td[^>]*><code[^>]*>([^<]+)</code></td>', table_rows.group(1)) if table_rows else []
    documented = {'profile' if c == 'profile validate' else c for c in first_cells}
    agent_commands = {'profile' if c == 'profile validate' else c for c in agents.get('cli_commands', {})}
    for command in sorted(commands - {'-h', '--help'}):
        require(command in documented, f'index.html: the commands table has no row for {command}')
        require(command in agent_commands, f'agents.json: cli_commands has no {command}')
        require(f'`mdrestyler {command}' in full, f'llms-full.txt: no section for mdrestyler {command}')
    for command, names in flags.items():
        for flag in sorted(names - {'-h', '--help'}):
            require(f'`{flag}' in full, f'llms-full.txt: {command} flag {flag} is not documented')
    require(agents.get('github_action') == f'sagol/mdrestyler@v{VERSION}', 'agents.json: github_action is not the current release')

    if errors:
        for error in errors:
            print(f'error: {error}', file=sys.stderr)
        print(f'{len(errors)} problem(s).', file=sys.stderr)
        return 1
    print(f'Site valid for mdrestyler {VERSION}: {counts["commands"]} command examples '
          f'({counts["complete examples"]} run through the argument checks), {counts["links"]} links, '
          f'{counts["contrast pairs"]} contrast pairs, JSON, JSON-LD, sitemap and {len(PUBLIC_FILES)} public files.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, ET.ParseError) as exc:
        sys.exit(f'site validation failed: {exc}')

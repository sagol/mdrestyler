"""What messages call this product and its commands, and who decides a delegated approval. A product built on
mdrestyler calls configure() once, before anything else runs, so every message and every profile it classifies use
its own names and its own approval rule. Standard library only."""
from pathlib import Path

PRODUCT = 'mdrestyler'
COMMANDS = {'scan': 'mdrestyler scan', 'check': 'mdrestyler check', 'install': 'mdrestyler install'}
APPROVER = None   # approver(decision, folder, item) -> '' when the decision approves the profile there, else why not
EXTRA_PROFILE_SCHEMAS = ()   # profile schemas a product wrote under its own name: read as they are, never rewritten
EXTRA_GUARD_SCHEMAS = ()   # copy-guard schemas likewise, for guards built by the same algorithm
REPORT_NOTE = 'Measures locate drift; a reader confirms it.'   # the check report's last line
KNOWN_DEFAULTS = frozenset()   # (prose, measures) SHA-256 pairs of defaults a product shipped: untouched, they stay defaults


class Layout:
    """How books are laid out, for a scan of an author's own Markdown book (--own-book) and for keeping a scan's output
    out of books. This default knows no books: the eligibility record lists the units in reading order ("order") and
    may name a title; it names no record of how the book was imported. A product with its own book layout passes a subclass
    to configure()."""
    order_name = 'the eligibility order'   # what messages call the reading order
    precedence = {
        'ru': 'Сначала решают бриф, запись о рассказчике и принятый авторский текст; профиль решает только то, что они оставляют открытым. '
              'Перед черновиком сверьте точку зрения и время с брифом; конфликт утверждённого профиля решает автор. '
              'Описание голоса правится вручную; измеряемые цели меняются новым сканированием.',
        'en': 'The brief, the narrator\'s record and accepted text decide first; this profile decides only what they leave open. '
              'Before drafting, compare POV and tense with the brief; the author resolves any conflict with an approved profile. '
              'Edit the described voice below; measured targets change with a new scan.',
    }

    def inside_book(self, path):
        """The book that holds path, if any; a scan never writes into one."""
        return None

    def record(self, held, book, eligibility, eligibility_path):
        """The book's own record of how it was imported, as a dict ({} when there is none)."""
        if eligibility.get('record'):
            raise ValueError(f'{eligibility_path}: "record" names a record only the tool that wrote it can check; '
                             'leave it out')
        return {}

    def order(self, held, book, eligibility, eligibility_path):
        """(title, the unit paths in reading order, each once)."""
        order = eligibility.get('order')
        if not isinstance(order, list) or not order or not all(isinstance(u, str) and u for u in order):
            raise ValueError(f'{eligibility_path}: "order" must list the book\'s unit files in reading order, as text')
        title = eligibility.get('title')
        return (title if isinstance(title, str) and title.strip() else Path(book).name), order


LAYOUT = Layout()


_CONFIGURED = None   # the settings of the one configure() call this process made


def configure(product=None, commands=None, approver=None, layout=None, profile_schemas=None, guard_schemas=None, known_defaults=None,
              report_note=None):
    """Set this process's host settings, once, before anything runs. profile_schemas, guard_schemas and known_defaults let
    a product's earlier profiles keep working: the schemas it wrote them under, and the defaults it shipped, by their
    (prose, measures) SHA-256 pairs. Everything is checked before anything changes. A second call with the same settings
    changes nothing; any other second call is refused, and the first settings stay, so an approval rule can never be
    swapped once profiles have been read under it."""
    global PRODUCT, APPROVER, LAYOUT, EXTRA_PROFILE_SCHEMAS, EXTRA_GUARD_SCHEMAS, KNOWN_DEFAULTS, REPORT_NOTE, _CONFIGURED
    import re
    texts = lambda items: isinstance(items, (list, tuple)) and all(isinstance(x, str) and x for x in items)
    hex64 = lambda x: isinstance(x, str) and re.fullmatch('[0-9a-f]{64}', x) is not None
    problems = []
    if product is not None and not (isinstance(product, str) and product):
        problems.append('product must be a name')
    if commands is not None and not (isinstance(commands, dict) and set(commands) <= set(COMMANDS) and texts(list(commands.values()))):
        problems.append(f'commands must map {", ".join(COMMANDS)} to names')
    if approver is not None and not callable(approver):
        problems.append('approver must be callable')
    if layout is not None and not isinstance(layout, Layout):
        problems.append('layout must be a Layout')
    for name, value in (('profile_schemas', profile_schemas), ('guard_schemas', guard_schemas)):
        if value is not None and not texts(value):
            problems.append(f'{name} must be a list of schema names')
    if known_defaults is not None and not (isinstance(known_defaults, (list, tuple, set, frozenset))
                                           and all(isinstance(p, (list, tuple)) and len(p) == 2 and all(map(hex64, p)) for p in known_defaults)):
        problems.append('known_defaults must be (prose, measures) SHA-256 pairs')
    if report_note is not None and not (isinstance(report_note, str) and report_note):
        problems.append('report_note must be text')
    if problems:
        raise ValueError('configure: ' + '; '.join(problems))
    settings = {'product': product, 'commands': tuple(sorted((commands or {}).items())), 'approver': approver, 'layout': layout,
                'profile_schemas': tuple(profile_schemas or ()), 'guard_schemas': tuple(guard_schemas or ()),
                'known_defaults': frozenset(tuple(p) for p in known_defaults or ()), 'report_note': report_note}
    if _CONFIGURED is not None:
        if settings == _CONFIGURED:
            return
        raise ValueError('configure: this process is already configured with other settings; they stay as they are')
    _CONFIGURED = settings
    if product is not None:
        PRODUCT = product
    if commands:
        COMMANDS.update(commands)
    if approver is not None:
        APPROVER = approver
    if layout is not None:
        LAYOUT = layout
    EXTRA_PROFILE_SCHEMAS = settings['profile_schemas']
    EXTRA_GUARD_SCHEMAS = settings['guard_schemas']
    KNOWN_DEFAULTS = settings['known_defaults']
    if report_note is not None:
        REPORT_NOTE = report_note


def command(name):
    return COMMANDS[name]

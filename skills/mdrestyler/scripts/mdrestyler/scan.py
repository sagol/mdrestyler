#!/usr/bin/env python3
"""Build an author voice profile from one or more DRM-free EPUB books, one profile per language.

For each language with enough text it writes, into --out:
  author-profile.<lang>.json   measures, target ranges and the function-word fingerprint, with every source's hash
  copy-guard.<lang>.json       winnowed hashes of the books' 8-word runs, short sections included, so a draft that
                               repeats a book can be found
  AUTHOR_PROFILE.<lang>.md     a draft profile: the measured targets filled in, the described voice left to write
and, into --work (a folder outside the book), samples.<lang>.md: passages to read while writing the described voice.
Delete the samples once the profile is written; a reference book's text never enters the book or the profile.

Mark the author's own books with --own and books by other writers with --reference. An imported book is read from its
Markdown units with --own-book BOOK --eligibility FILE: the file records the author's confirmation of which units and
passages are their own original prose. Only those are measured and sampled; every unit, notes included, feeds the
copy guard, and the source record keeps the source file's hash and each unit's. Only the author's own books
may be quoted in the profile. --out and --work must lie outside any book (installing puts the result in one), and a
profile already in --out is replaced only with --replace, which first moves its files to --out/history/<time>/.
Exit status: 0 built; 1 refused (DRM, a size limit, an existing profile, a folder inside a book, a destination that is
a symbolic link, the same book given twice) or no language had enough text; 2 on errors, such as a damaged archive, an
input that is not a regular file or a language tag that names no language. Standard library only."""
import argparse
import datetime
import hashlib
import json
import re
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

sys.dont_write_bytecode = True   # an installed skill folder stays as installed: no __pycache__ beside the scripts

from .held import Held, Stopped as HeldStopped
from .install import history_folder
from . import __version__
from . import names as host
from .profile import GUARD_SCHEMA, PROFILE_SCHEMA, every_name, unsafe_destination
from .metrics import (CAUGHT, CYRILLIC, LATIN, MEASURE_METHOD, TEXT_MB, Budget, DRMError, LimitError, SCENE_BREAK, SHINGLE, WINDOW, build_targets, calibration,
                           chapter_values, guard_hashes, register_targets,
                           half_split_cosines, source_to_pool_cosine, measure, read_epub, read_markdown, sentences, split_by_language, words_of,
                           SHORT_SECTION, count_words, lang_code, mostly_cyrillic, tag_script, unsegmented, visible_text)

SCHEMA = PROFILE_SCHEMA
TOOL = f'mdrestyler scan {__version__}'


class Refused(ValueError):
    pass


def inside_book(path):
    """The book that holds path, if any, as the configured layout knows books."""
    return host.LAYOUT.inside_book(path)


def chapters_of(parts):
    return [ch for _, part in parts for ch in part]


def scripts_of(chapters):
    """Every script a profile's paragraphs are written in, so the check can match a draft in any of them."""
    return sorted({'cyrillic' if mostly_cyrillic(p[0]) else 'latin'
                   for ch in chapters for p in ch['paragraphs'] if p != SCENE_BREAK and (CYRILLIC.search(p[0]) or LATIN.search(p[0]))})


def plain(value, limit=200):
    """Book metadata as one plain line: no line breaks or control characters, so it cannot start a line of its own."""
    return re.sub(r'\s+', ' ', re.sub(r'[\x00-\x1f\x7f]', ' ', value or '')).strip()[:limit]


def cell(value):
    """Plain metadata escaped for a Markdown table cell or heading: it shows as text and never as markup."""
    return re.sub(r'([\\`*_\[\]<>|#])', r'\\\1', plain(value))


def sample_locator(where, positions):
    if len(positions) == 1:
        return f'{where}, paragraph {positions[0]}'
    span = (f'{positions[0]} to {positions[-1]}' if positions == list(range(positions[0], positions[-1] + 1))
            else ', '.join(map(str, positions)))
    return f'{where}, paragraphs {span}'


def pick_samples(by_source, lang):
    """Heuristic leads to varied passages, not semantic judgments of scene type. Keep paragraph boundaries."""
    kinds = {'narration at rest': [], 'dialogue': [], 'under pressure': [], 'interior': [], 'chapter opening': [], 'chapter ending': []}
    for source, chapters in by_source:
        for ci, ch in enumerate(chapters):
            if ch.get('short') or ch.get('apparatus'):
                continue
            positions = ch.get('source_paragraphs')
            paras, paragraph = [], 0
            for index, p in enumerate(ch['paragraphs']):
                if p != SCENE_BREAK:
                    paragraph += 1
                    paras.append((p, positions[index] if positions is not None else paragraph, index))
            if not paras:
                continue
            where = f'{cell(source["title"] or source["file"])} ({source["role"]}), section {ch.get("source_section", ci + 1)}: {cell(ch.get("title", ""))}'
            if ch.get('source_unit'):
                where += f', unit {cell(ch["source_unit"])}'
            kinds['chapter opening'].append((sample_locator(where, [p[1] for p in paras[:3]]), '\n\n'.join(p[0][0] for p in paras[:3])))
            kinds['chapter ending'].append((sample_locator(where, [p[1] for p in paras[-3:]]), '\n\n'.join(p[0][0] for p in paras[-3:])))
            run = []
            previous = None
            for p, position, index in paras:
                text = p[0]
                if previous != (position - 1, index - 1):
                    run = []   # removed languages and scene breaks cannot join one exchange
                previous = position, index
                n = len(words_of(text))
                quoted = text.lstrip()[:1] in '"“—–' or '“' in text or '"' in text
                if quoted:
                    run.append((position, text))
                    if len(run) == 4:
                        kinds['dialogue'].append((f'{where}, paragraphs {run[0][0]} to {position}', '\n\n'.join(t for _, t in run)))
                        run = []
                    continue
                run = []
                ss = sentences(text, lang)
                lengths = [len(words_of(s)) for s in ss]
                if 60 <= n <= 220 and '!' not in text and '?' not in text:
                    kinds['narration at rest'].append((f'{where}, paragraph {position}', text))
                if len(lengths) >= 5 and sorted(lengths)[len(lengths) // 2] <= 6:
                    kinds['under pressure'].append((f'{where}, paragraph {position}', text))
                if n >= 80 and lengths and sum(lengths) / len(lengths) >= 24:
                    kinds['interior'].append((f'{where}, paragraph {position}', text))
    picks = {}
    for kind, items in kinds.items():
        want = 3 if kind in ('narration at rest', 'dialogue') else 2
        if items:
            step = max(1, len(items) // want)
            picks[kind] = items[::step][:want]
    return picks


def clip(text, limit=230):
    # Preserve speech turns and paragraph shape; truncation is visible, not evidence of the passage's ending.
    count, kept = 0, []
    for paragraph in text.split('\n\n'):
        words = paragraph.split()
        if count + len(words) > limit:
            kept.append(' '.join(words[:limit - count]) + ' … [excerpt truncated]')
            break
        kept.append(paragraph)
        count += len(words)
    return '\n\n'.join(kept)


def fmt(v):
    return f'{v:.2f}' if isinstance(v, float) else str(v)


def profile_markdown(lang, sources, targets, date, partial=False, unsettled=False, emphasis_partial=False):
    rows = '\n'.join(f'| {t["label"]} | {fmt(t["value"])} | {fmt(t["low"])} to {fmt(t["high"])} | {t["basis"]} ({t["sample_count"]}) |' for t in targets.values())
    srcs = '\n'.join(f'| {cell(s["title"] or s["file"])} | {cell(s["author"]) or "-"} | {s["role"]} | {s["words"]} | `{s["sha256"][:12]}` |' for s in sources)
    own = any(s['role'] == 'own' for s in sources)
    coverage = ('Coverage: partial. Sources include Han, kana, Thai, Lao, Khmer or Myanmar text without supported word segmentation. '
                'Word and sentence measures are approximate there; the guard cannot guarantee complete coverage.' if partial else '')
    if partial and lang == 'ru':
        coverage = ('Покрытие частичное: среди источников есть текст без поддерживаемого разбиения на слова. '
                    'Меры слов и предложений там приблизительны; полнота защиты от копирования не подтверждена.')
    if unsettled:   # rules the scan could not settle (listed with each source in the JSON profile)
        coverage = (coverage + ' ' if coverage else '') + (
            'Стили прочитаны частично: правила таблиц стилей, которые сканирование не может проверить (с проверкой атрибута, '
            'псевдоклассом, соседним элементом или условием), могут скрывать или показывать прочитанный текст; они перечислены '
            'у источников в профиле.' if lang == 'ru' else
            'Styles: partial. Stylesheet rules the scan cannot settle (an attribute test, a pseudo-class, a sibling step or a '
            'condition) may hide or show text it read; the JSON profile lists them with each source.')
    if emphasis_partial:   # rules beyond the import's subset that set italic or bold (listed with each source in the JSON profile)
        coverage = (coverage + ' ' if coverage else '') + (
            'Выделение прочитано частично: правила таблиц стилей за пределами подмножества импорта задают курсив или '
            'полужирный, а сканирование, как и импорт, их не применяет; мера выделения приблизительна, правила перечислены '
            'у источников в профиле.' if lang == 'ru' else
            'Emphasis: partial. Stylesheet rules beyond the import\'s subset set italic or bold, which the scan, like the import, '
            'does not apply; the emphasis measure is approximate, and the JSON profile lists them with each source.')
    if lang == 'ru':
        quote = 'Цитировать можно только книги с ролью own.' + ('' if own else ' Среди источников нет книг автора, поэтому профиль ничего не цитирует.')
        return f"""# Профиль автора (ru)

Статус: черновик, построен {date}; автор его ещё не утвердил.
{coverage}
Язык: ru. Меры и целевые диапазоны: `author-profile.ru.json`. Защита от копирования: `copy-guard.ru.json`.
{host.LAYOUT.precedence['ru']}

## Источники

| Книга | Автор | Роль | Слов | SHA-256 |
|---|---|---|---|---|
{srcs}

{quote}

## Измеряемые цели

Основание указано для каждой меры: chapter spread — разброс не менее четырёх глав; pooled fallback — общий результат ±20% с допуском, когда глав с этой мерой меньше четырёх. В скобках — число измеренных глав; source/half comparisons считает сравнения источников и их половин. Короткий черновик даёт слабое свидетельство.

Меры смешивают повествование, реплики и другие регистры. Они находят различия, но не доказывают сходство голоса. Не выводите из средней длины фразы, что размышление должно звучать как короткая реплика.

| Мера | Источники | Целевой диапазон | Основание (число) |
|---|---|---|---|
{rows}

## Повествование

- Точка зрения и время:
- Дистанция и внутренний мир:
- Чувства (названы, показаны через тело, обойдены):
- Как развивается мысль внутри абзаца; сомнение, поправка, смешанное чувство:

## Ритм

- Движение фразы и как оно меняется в напряжении и в размышлении:
- Абзацы по типам сцен:
- Разница между спокойной сценой, спором, близким разговором и кризисом:

## Лексика

- Регистр и словарь:
- Любимые слова и обороты (описать; цитировать только книги автора):

## Образность

- Откуда берутся образы; как часто встречаются сравнения и метафоры:

## Диалог

- Оформление и ремарки:
- Как различаются персонажи:
- Как реплика отвечает, уклоняется, перебивает или меняет отношения:

## Строение

- Начала и концовки глав; разрывы сцен; пересказ и сцена:

## Тон и юмор

-

## Никогда

- Только ограничения автора и обоснованные границы голоса. Редкость в образцах не означает запрета; допустимую вариацию опишите выше.

## Основание описания и пределы

- Для наблюдений укажите источник, раздел и абзацы, без цитат из reference; отделите наблюдение от вывода и пожелания автора.
- Какие типы сцен прочитаны в контексте; что осталось неизвестным; какое противоположное наблюдение ограничивает обобщение:

## Речь персонажей

Пределы, в которых речь персонажа может отходить от голоса повествования:

-

## Утверждение

Запишите дату, когда автор утвердил профиль, например 03.10.2026 или 3 октября 2026 г., и больше ничего в этой строке; примечания — в строке «Изменения с датами».

- Утверждён автором: (ещё нет)
- Изменения с датами:
"""
    quote = 'Quote only books marked own.' + ('' if own else " No source is the author's own, so this profile quotes nothing.")
    return f"""# Author profile ({lang})

Status: draft, built {date}; the author has not approved it yet.
{coverage}
Language: {lang}. Measures and targets: `author-profile.{lang}.json`. Copy guard: `copy-guard.{lang}.json`.
{host.LAYOUT.precedence['en']}

## Sources

| Book | Author | Role | Words | SHA-256 |
|---|---|---|---|---|
{srcs}

{quote}

## Measured targets

Each range names its basis and sample count. Chapter spread needs at least four chapters with that measure. Pooled fallback uses the pooled value ±20% plus the measure's allowance when fewer chapters qualify. Source/half comparisons count comparisons between sources and their halves. A short draft gives weak evidence.

The pooled measures mix narration, speech and other registers; the narration and dialogue ranges in the measures file keep the first two apart where the sources hold enough of each. They locate differences, not fidelity. A short overall sentence length does not prescribe clipped reflective narration.

| Measure | Sources | Target range | Basis (count) |
|---|---|---|---|
{rows}

## Narration

- Point of view and tense:
- Distance and interiority:
- How emotion is handled (named, embodied, deflected):
- How thought moves within a paragraph; hesitation, self-correction and mixed feeling:

## Rhythm

- Sentence movement, and how it shifts under pressure or in reflection:
- Paragraphing by scene type:
- Variation between quiet scenes, argument, intimacy and crisis:

## Diction

- Register and vocabulary band:
- Words and constructions the voice favors (described; quote only own books):

## Imagery

- Where the images come from; how often figurative language appears:

## Dialogue

- How speech is set out and tagged:
- How characters are told apart:
- How a reply answers, evades, interrupts or changes a relationship:

## Structure

- Chapter openings and endings; scene breaks; summary against scene:

## Tone and humor

-

## Never

- Author-stated exclusions and evidenced limits only. Rarity in samples is not a prohibition; describe allowed variation above.

## Evidence and limits

- Locate observations by source, section and paragraphs, without quoting reference books; distinguish observation, inference and author direction.
- Scene types read in context, coverage still unknown, and counterexamples that limit each generalization:

## Character speech

The limits within which a character's speech may depart from the narration's voice:

-

## Approval

Write the date the author approved this profile, such as 2026-10-03 or 3 October 2026, and nothing else on that line; notes go on the Changes line.

- Approved by the author on: (not yet)
- Changes, with dates:
"""


NOTE_DEFINITION = re.compile(r'(?m)^[ \t]{0,3}\[\^[^\]\n]+\]:[ \t]*(.*(?:\n(?:[ \t]*\n)*(?:[ \t]{4}|\t).*)*)')   # as read_markdown removes it


def read_unit(held, book, name, budget):
    """The bytes of a unit the reading order names: a regular file inside the book, reached through the book's handle (Held)
    without following a link at any step, so no text from outside the book enters a profile; counted against the budget
    before it is read, and never read past what was counted. Anything else is refused."""
    parts = name.split('/')
    if name.startswith('/') or '\\' in name or ':' in name or '..' in parts or '' in parts or '.' in parts:
        raise ValueError(f'{book}: {host.LAYOUT.order_name} names {name!r}, which is not a unit inside the book')
    for end in range(1, len(parts) + 1):   # named apart for the author; the read below decides
        try:
            if held.kind('/'.join(parts[:end])) == 'link':
                raise ValueError(f'{book}: {host.LAYOUT.order_name} reaches {name!r} through a symbolic link')
        except OSError:
            break
    try:
        return held.read(name, take=lambda size: budget.take_bytes(size, str(Path(book) / name)))
    except OSError:
        raise ValueError(f'{book}: {host.LAYOUT.order_name} names {name!r}, which is not a regular file inside the book') from None


def guard_reading(text):
    """A unit's text for the copy guard, in manuscript order: everything a reader can meet, prose, notes, image alt text
    and titles where the image stands, and reference definitions with their titles, as the guard's every-word reading
    keeps it."""
    return [b.strip() for b in re.split(r'\n\s*\n', visible_text(text, every_word=True)) if b.strip()]


def script_of(tags, lang, declared=()):
    """The script of the first of tags (the author's, then the import's) of the language lang that names one (sr-Latn:
    latin), read before a tag is reduced to its language; else the one script the source's declared tags give lang, a
    tag without a script subtag giving its language's usual one, or that usual script when it declares none. None
    when the source declares lang in several scripts, which only the author settles."""
    for tag in tags:
        if isinstance(tag, str) and lang_code(tag, '') == lang and re.search(r'(?i)(?:^|[-_])(?:latn|cyrl)(?:[-_]|$)', tag):
            return tag_script(tag)
    scripts = {tag_script(t) for t in declared if isinstance(t, str) and lang_code(t, '') == lang}
    return None if len(scripts) > 1 else scripts.pop() if scripts else tag_script(lang)


def read_imported(book, eligibility_path, budget):
    """An author's own Markdown book read from its units in reading order, as read_epub reads an EPUB: (meta, chapters).
    Units and passages the author did not confirm as original prose are apparatus: guarded, never measured. The book is
    held from the first read on (Held), and its record, order and units are read through it."""
    try:
        held = Held(Path(book).resolve(), strict=False)
    except HeldStopped as error:
        raise ValueError(str(error)) from None
    try:
        return read_imported_held(held, Path(book), eligibility_path, budget)
    finally:
        held.close()


def read_imported_held(held, book, eligibility_path, budget):
    eligibility_bytes = Path(eligibility_path).read_bytes()   # parsed and hashed from the same bytes
    eligibility = json.loads(eligibility_bytes.decode('utf-8'))
    if not isinstance(eligibility, dict):
        raise ValueError(f'{eligibility_path}: not an eligibility record; it is a JSON object with "decision", "language" and "units"')
    units = eligibility.get('units') or {}
    if not isinstance(units, dict):
        raise ValueError(f'{eligibility_path}: "units" must name each unit file with its decision, as a JSON object')
    for key in ('record', 'language'):
        if eligibility.get(key) is not None and not isinstance(eligibility[key], str):
            raise ValueError(f'{eligibility_path}: "{key}" must be text')
    if not isinstance(eligibility.get('decision'), str) or not eligibility['decision'].strip():
        raise ValueError(f'{eligibility_path}: no decision; record the author\'s dated confirmation of their original prose first')
    for name, choice in units.items():   # only a literal true marks a unit as the author's original prose
        exclude = choice.get('exclude', []) if isinstance(choice, dict) else None
        if not isinstance(choice, dict) or not isinstance(choice.get('eligible', False), bool) \
                or not isinstance(exclude, list) or not all(isinstance(e, str) for e in exclude):
            raise ValueError(f'{eligibility_path}: unit {name!r} needs "eligible": true or false and "exclude" as a list of passages')
    record = host.LAYOUT.record(held, book, eligibility, eligibility_path)
    title, order = host.LAYOUT.order(held, book, eligibility, eligibility_path)
    where = host.LAYOUT.order_name
    repeated = sorted({path for path in order if order.count(path) > 1})
    if repeated:   # each unit is read once, where it stands; a second entry would count its prose twice
        raise ValueError(f'{book}: {where} names {", ".join(repeated)} more than once; list each unit once')
    unknown = sorted(set(units) - set(order))
    if unknown:
        raise ValueError(f'{eligibility_path}: names units that are not in {where}: {", ".join(unknown)}')
    chapters, unit_hashes, reading_order, measured, excluded_count, source_section = [], {}, [], [], {}, 0
    for path in order:
        data = read_unit(held, book, path, budget)   # counted before it is read
        unit_hashes[path] = hashlib.sha256(data).hexdigest()
        text = data.decode('utf-8')
        choice = units.get(path) or {'eligible': False}
        if choice.get('eligible') is True and choice.get('sha256') != unit_hashes[path]:   # the confirmation covers these bytes only
            raise ValueError(f'{eligibility_path}: unit {path!r} ' + ('has changed since the author confirmed it' if choice.get('sha256')
                             else 'needs the SHA-256 it had when the author confirmed it') + '; ask the author to confirm it again')
        excluded = [re.sub(r'\s+', ' ', e).strip() for e in choice.get('exclude') or [] if e.strip()]
        if choice.get('eligible') is True:
            measured.append(path)
            if excluded:
                excluded_count[path] = len(excluded)
        matched = set()
        reading_order += guard_reading(text)   # every word a reader can meet, in manuscript order, excluded passages in place
        for ch in read_markdown(text, excluded):   # an excluded passage is cut out of its paragraph, the rest measured
            source_section += 1   # source sections only; synthetic guard entries below do not advance the locator
            kept, apart = ch['paragraphs'], ch.get('apart', [])
            matched |= {passage for passage, _ in apart}
            words = sum(count_words(q[0]) for q in kept if q != SCENE_BREAK)
            chapters.append({'title': ch['title'], 'paragraphs': kept, 'short': words < SHORT_SECTION,
                             'apparatus': choice.get('eligible') is not True, 'source_section': source_section,
                             'source_unit': path, 'source_paragraphs': ch['source_paragraphs']})
            if apart:
                chapters.append({'title': '', 'paragraphs': apart, 'short': True, 'apparatus': True})
        missing = [e for e in excluded if e not in matched]
        if missing:   # an exclusion that matches nothing would leave its passage measured without the author's word
            raise ValueError(f'{eligibility_path}: unit {path!r}: the excluded passage {missing[0][:60]!r} matches no paragraph; '
                             'copy it exactly from the unit')
        notes = [(re.sub(r'\s+', ' ', m.group(1)).strip(), 0) for m in NOTE_DEFINITION.finditer(text)]
        if notes:   # notes are left out of the measures, as a book's notes are, but the guard reads them
            chapters.append({'title': '', 'paragraphs': notes, 'short': True, 'apparatus': True})
    lang = lang_code(eligibility.get('language') or record.get('language') or '', '')
    if not lang:
        raise ValueError(f'{eligibility_path}: no language; record the book\'s language code, such as en or ru')
    declared = (record.get('meta') or {}).get('language')
    declared = [t for t in declared if isinstance(t, str)] if isinstance(declared, list) else []
    script = script_of([eligibility.get('language'), record.get('language_tag')], lang, declared)
    if script is None:   # sr-Latn beside sr-Cyrl in the source, and neither the author's tag nor the import's names one
        raise ValueError(f'{eligibility_path}: the source names {lang} in several scripts '
                         f'({", ".join(t for t in declared if lang_code(t, "") == lang)}); set the eligibility file\'s language '
                         f'to the book\'s tag with its script, such as {lang}-Latn or {lang}-Cyrl')
    meta = {'title': title, 'author': ', '.join((record.get('meta') or {}).get('creator') or []),
            'language': lang, 'script': script,   # the import's source, or else the units in reading order, never the title alone
            'sha256': record.get('source_sha256') or hashlib.sha256(''.join(unit_hashes[p] for p in order).encode()).hexdigest(),
            'units': unit_hashes, 'decision': eligibility.get('decision', ''),
            # what the author authorized for measuring, kept with the profile: the eligibility file's hash, the measured
            # units and how many passages each left out (counts only: the profile never holds the book's text)
            'eligibility': {'file_sha256': hashlib.sha256(eligibility_bytes).hexdigest(), 'measured': measured,
                            'excluded_passages': excluded_count},
            'reading_order': reading_order}   # the guard reads every unit in order, excluded passages in place
    return meta, chapters


def scan(own, reference, out, work, min_words=3000, replace=False, text_mb=TEXT_MB, books=()):
    out, work = Path(out), Path(work)
    if work.resolve() == out.resolve() or out.resolve() in work.resolve().parents or work.resolve() in out.resolve().parents:
        raise ValueError('--work and --out must not hold each other: samples hold book text, are deleted after use, and stay apart from the profile')
    for flag, path in (('--out', out), ('--work', work)):
        book = inside_book(path)
        if book:
            raise Refused(f'{flag} {path} lies inside the book at {book}: scan and keep the samples outside the book, '
                          f'then install the profile with {host.command("install")}')
        written = path.resolve()   # the scan writes here: never into a source it reads, nor where a source lies
        for root, _ in books:
            source = Path(root).resolve()
            if written == source or source in written.parents:
                raise Refused(f'{flag} {path} lies inside the book being scanned, {root}: keep the profile and the samples outside it')
        for source in list(own) + list(reference):
            if written in Path(source).resolve().parents:
                raise Refused(f'{flag} {path} holds the source {source}: keep the books outside the folders the scan writes')
    sources, buckets, streams = [], {}, []
    partial = False   # each language's guard covers all sources, so a coverage limit travels with every profile
    unsettled = False   # likewise for stylesheet rules a scan could not settle
    budget = Budget(text_mb)   # one budget for every book in the scan
    for role, paths in (('own', list(own) + [('book', b, e) for b, e in books]), ('reference', reference)):
        for path in paths:
            if isinstance(path, tuple):
                meta, chapters = read_imported(path[1], path[2], budget)
                path = path[1]
            else:
                meta, chapters = read_epub(path, budget)
            source = {'file': plain(Path(path).name), 'title': plain(meta['title']), 'author': plain(meta['author']), 'role': role,
                      'sha256': meta['sha256'], 'language': meta['language']}
            if meta.get('unresolved_styles'):   # rules it could not settle that might show or hide text it read
                source['unresolved_styles'] = meta['unresolved_styles']
                unsettled = True
            if meta.get('unresolved_emphasis'):   # rules setting emphasis beyond the subset, which neither reading counts
                source['unresolved_emphasis'] = meta['unresolved_emphasis']
            if meta.get('units'):
                source['units'] = meta['units']
                source['eligibility_decision'] = plain(meta.get('decision', ''))
                source['eligibility'] = meta['eligibility']
            twin = next((s for s in sources if s['sha256'] == source['sha256']), None)
            if twin:   # the same book twice would weigh double, and under both roles be quotable and not
                raise Refused(f'{path} is the same book as {twin["file"]} (given as {twin["role"]}); give each book once, as own or as reference')
            sources.append(source)
            stream = []   # counted as it grows, so a book past the ceiling stops before its runs are hashed
            texts = meta.get('reading_order')
            if texts is None:
                texts = [t for ch in chapters for t in [ch['title']] + [p[0] for p in ch['paragraphs'] if p != SCENE_BREAK]]
            for text in texts:
                partial = unsegmented(text) or partial
                words = words_of(text)
                budget.take_words(len(words), path)
                stream += words
            streams.append(stream)
            for lang, part in split_by_language(chapters, meta['language'], meta.get('script')).items():
                buckets.setdefault(lang, []).append((source, part))
    report = {'profiles': {}, 'skipped': {}}
    plans = {}
    for lang, parts in sorted(buckets.items()):
        measured = [(source, [ch for ch in part if not ch.get('short') and not ch.get('apparatus')]) for source, part in parts]
        pooled = measure([ch for _, part in measured for ch in part], lang)
        if pooled['words'] < max(min_words, 1):
            total = sum(count_words(p[0]) for _, part in parts for ch in part for p in ch['paragraphs'] if p != SCENE_BREAK)
            report['skipped'][lang] = (f'{pooled["words"]} words in measured chapters ({total} in all; sections under {SHORT_SECTION} words '
                                       f'and apparatus are not measured); at least {min_words} make a profile')
            continue
        plans[lang] = (parts, measured, pooled)
    names = [name for lang in plans for name in every_name(lang)]   # a profile saved under an older spelling counts too
    problem = (unsafe_destination(out, names + ['history'])
               or unsafe_destination(work, [f'samples.{lang}.md' for lang in plans]))   # before anything is moved or written
    if problem:
        raise Refused(problem)
    existing = [out / name for name in names if (out / name).exists()]
    if existing and not replace:
        raise Refused(f'{out} already holds a profile ({", ".join(p.name for p in existing)}); pass --replace to replace it, and its files move to history/')
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    if existing:
        report['kept'] = str(history_folder(out / 'history'))
        for path in existing:
            path.rename(Path(report['kept']) / path.name)
    date = datetime.date.today().isoformat()
    # one guard for every profile: each book's whole text in reading order, headings and every language included, so a
    # copied passage is found whichever language's profile the draft is checked against
    guard = set().union(*(guard_hashes(stream) for stream in streams)) if streams else set()
    for lang, (parts, measured, pooled) in plans.items():
        rows = [r for _, part in measured for r in chapter_values(part, lang)]
        halves = [c for _, part in measured for c in half_split_cosines(part, lang) + source_to_pool_cosine(part, pooled, lang)]
        targets = build_targets(pooled, rows, halves)
        lang_sources = []
        for (source, part), (_, kept) in zip(parts, measured):
            words = [w for ch in kept for p in ch['paragraphs'] if p != SCENE_BREAK for w in words_of(p[0])]
            lang_sources.append({k: source[k] for k in ('file', 'title', 'author', 'role', 'sha256')} | {'words': len(words), 'chapters': len(kept)}
                                | ({k: source[k] for k in ('units', 'eligibility_decision', 'eligibility')} if source.get('units') else {})
                                | ({'unresolved_styles': source['unresolved_styles']} if source.get('unresolved_styles') else {})
                                | ({'unresolved_emphasis': source['unresolved_emphasis']} if source.get('unresolved_emphasis') else {}))
        emphasis_partial = any(s.get('unresolved_emphasis') for s in lang_sources)
        profile = {'schema': SCHEMA, 'tool': TOOL, 'language': lang, 'built': date, 'sources': lang_sources,
                   'measures': {k: v for k, v in pooled.items() if k != 'function_words'}, 'function_words': pooled['function_words'],
                   'targets': targets, 'chapters_measured': len(rows), 'scripts': scripts_of(chapters_of(parts))}
        if lang in MEASURE_METHOD:   # how this release reads the language's measures; a later method compares only what it kept
            profile['measure_method'] = MEASURE_METHOD[lang]
        profile['calibration'] = calibration(rows, targets)   # each source chapter against the others: the scale a draft's distance is read on
        registers = register_targets([ch for _, part in measured for ch in part], lang)
        if registers:   # narration and dialogue apart, so a pooled measure does not mix speech and narration
            profile['registers'] = registers
        if partial:
            profile['segmentation'] = 'partial'
        if unsettled:
            profile['styles'] = 'partial'
        if emphasis_partial:
            profile['emphasis'] = 'partial'
        # this language's guard bytes, hashed as written: the measures name the one guard they were built with
        guard_bytes = (json.dumps({'schema': GUARD_SCHEMA, 'language': lang, 'run_words': SHINGLE, 'window': WINDOW,
                                   'catches_runs_of': CAUGHT, 'hashes': sorted(guard)}, separators=(',', ':')) + '\n').encode('utf-8')
        profile['copy_guard_sha256'] = hashlib.sha256(guard_bytes).hexdigest()
        (out / f'author-profile.{lang}.json').write_text(json.dumps(profile, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        (out / f'copy-guard.{lang}.json').write_bytes(guard_bytes)
        (out / f'AUTHOR_PROFILE.{lang}.md').write_text(profile_markdown(lang, lang_sources, targets, date, partial, unsettled, emphasis_partial),
                                                       encoding='utf-8')
        picks = pick_samples(measured, lang)
        lines = [f'# Samples for the {lang} profile', '',
                 'Read these to write the described voice. They are book text: keep this file out of the book, quote only books marked own, and delete it once the profile is written.', '',
                 'Categories are heuristic leads, not findings. Read the surrounding scene before using a passage as evidence. '
                 'Short sentences do not prove pressure; long ones do not prove interiority. Verify dialogue continuations and source type. '
                 'A missing category means not sampled, not absent. A truncated excerpt is not a chapter ending. '
                 'Section numbers count reader-extracted sections before filtering; paragraph numbers count their non-break paragraphs.', '']
        for kind, items in picks.items():
            lines.append(f'## {kind}')
            for where, text in items:
                lines += ['', f'### {where}', '', clip(text)]
            lines.append('')
        (work / f'samples.{lang}.md').write_text('\n'.join(lines), encoding='utf-8')
        report['profiles'][lang] = {'segmentation': 'partial' if partial else 'supported', 'styles': 'partial' if unsettled else 'supported',
                                    'emphasis': 'partial' if emphasis_partial else 'supported', 'words': pooled['words'], 'chapters_measured': len(rows), 'targets': len(targets), 'copy_guard_hashes': len(guard),
                                    'files': [str(out / f'AUTHOR_PROFILE.{lang}.md'), str(out / f'author-profile.{lang}.json'), str(out / f'copy-guard.{lang}.json')],
                                    'samples': str(work / f'samples.{lang}.md')}
    return report


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def main(argv=None, prog=None, description=None):
    for stream in (sys.stdout, sys.stderr):   # a terminal that cannot show a character gets an escape, not a crash
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(prog=prog, description=description or __doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--own', action='append', default=[], metavar='EPUB', help="a book by the author (may be quoted in the profile)")
    parser.add_argument('--reference', action='append', default=[], metavar='EPUB', help='a book by another writer (measured and described, never quoted)')
    parser.add_argument('--own-book', metavar='BOOK', help="the author's own Markdown book folder, read from its units (needs --eligibility)")
    parser.add_argument('--eligibility', metavar='FILE', help="the author's confirmation of the book's original units and passages")
    parser.add_argument('--out', required=True, help='folder for the profile files')
    parser.add_argument('--work', required=True, help='folder outside the book for the sample passages')
    parser.add_argument('--min-words', type=positive, default=3000, help='fewest words in a language to build its profile (default 3000)')
    parser.add_argument('--replace', action='store_true', help='replace a profile already in --out, moving its files to history/ first')
    parser.add_argument('--max-expanded-mb', type=positive, default=TEXT_MB,
                        help=f'expanded EPUB text the scan may read across all its books (default {TEXT_MB}); fixed ceilings also limit each file, '
                             'its entries and the words held')
    args = parser.parse_args(argv)
    if bool(args.own_book) != bool(args.eligibility):
        parser.error('--own-book and --eligibility go together')
    if not args.own and not args.reference and not args.own_book:
        parser.error('give at least one book with --own, --own-book or --reference')
    try:
        report = scan(args.own, args.reference, args.out, args.work, args.min_words, args.replace, args.max_expanded_mb,
                      [(args.own_book, args.eligibility)] if args.own_book else ())
    except (DRMError, Refused, LimitError) as error:
        parser.exit(1, f'Refused: {error}\n')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError, zlib.error, NotImplementedError, RuntimeError,
            EOFError) as error:   # a damaged or unsupported archive
        parser.exit(2, f'Scan failed: {error}\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report['profiles']:
        sys.exit(1)


if __name__ == '__main__':
    main()

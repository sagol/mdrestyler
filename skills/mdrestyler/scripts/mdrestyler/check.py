#!/usr/bin/env python3
"""Measure a draft against an author profile and run the copy guard. Standard library only.

  mdrestyler check --profile FOLDER candidate.md [more.md ...] [--lang ru] [--json] [--strict]
  mdrestyler check --profile FOLDER revised.md --accepted base.md   (a revision of one accepted unit)
  mdrestyler rank --profile FOLDER take1.md take2.md take3.md   (takes of one unit, ranked by fit)
  mdrestyler book --profile FOLDER --list UNITS.txt BOOK [--within p90]   (every unit in reading order, one row each)

The report names the candidate files and the SHA-256 of their bytes, the profile's revision (the prose profile, the
measures and the copy guard, each with its SHA-256, the guard stated as absent when there is none), then:
  - the profile's status: approved, draft or the shipped default, quoting an approval line that holds a number but
    does not read as one date;
  - copy guard: runs of 8 words the draft shares with a scanned book. Every shared run of 15 space-delimited words or more within supported extraction is found;
    a shorter one is found only when the guard kept one of its hashes;
  - each measured target: the draft's value, the profile's range, and within, near, outside or not measured, marked
    weak when the draft is too short for that measure;
  - the voice distance: the draft's mean robust distance from the profile's sources over the calibrated measures, and
    the share of the sources' own chapters that lie farther from the rest (each measured without itself), when the
    profile holds a calibration;
  - narration (the author's words) and dialogue (the spoken words) apart, each against its own ranges, when the profile
    holds them; --strict counts these comparisons too. Each register also gets its own voice distance, read against
    that register's source chapters, when the profile calibrates it and the draft holds enough of the register. These
    leave out the share of dialogue, which follows a unit's composition and length more than its voice, so it is a poor
    aim for rewording.
With --rank, each file is one take of the same unit, checked alone and ordered: takes with a copy-guard run last, then
by narration distance, then by voice distance, then by the number of measures outside. The order informs a reading;
it chooses nothing.
With --book, each unit of the book's reading order (the files --list names, one per line, relative to the book) is
checked alone against the profile, for a before and after table of a restyle or a whole-book look at drift. Its last
column reads each unit's narration distance against a threshold, the narration calibration's 90th percentile unless
--within names p50, max or a number: beyond means its narration lies farther from the profile than the sources' own
chapters mostly do, so read it first; within means it lies nearer; by reading means the unit holds too little
narration to measure or the profile has no narration calibration. The column sets an order of reading, not an
outcome: a reading decides whether a unit needs a restyle. The JSON keeps the threshold's selector and exact value. A unit with no prose gets a row saying so; any other failure, such as an invalid
profile, stops the table with exit 2.
Without --lang, the language is the one profile in the folder whose recorded scripts (Latin, Cyrillic) include the
draft's; when several profiles do, pass --lang.
With --accepted, a revision of one accepted unit is checked against that unit's exact accepted base: a run the revision keeps unchanged, in place and unambiguous is the base's own text;
base text it repeats more often than the base is a hit at every occurrence; moved or ambiguous base text is uncertain,
never clear; inserted text and changed seams stay checked. The alignment is bounded (20,000 words, 10 seconds); past
either bound nothing is exempt, duplicates and runs the base lacks stay hits and the rest is uncertain.
Measures locate drift; a reading of the draft judges it.
Exit status: 0 measured; 1 when the copy guard finds a run (or, with --strict, a measure is outside and not marked
weak, or the profile was scanned by another measure method, so a target could not be compared); 2 on errors, including a profile or guard that is not valid."""
import argparse
import bisect
import difflib
import hashlib
import json
import multiprocessing
import sys
from collections import Counter
from pathlib import Path
from queue import Empty

sys.dont_write_bytecode = True   # an installed skill folder stays as installed: no __pycache__ beside the scripts

from . import names as host
from . import profile as profiles
from .metrics import (CAUGHT, MEASURE_METHOD, ONLY_EVERY, REGISTER_MIN_WORDS, REGISTERS, SCENE_BREAK, SHINGLE, calibrated, words_of, compare, interruptions, measure, mostly_cyrillic,
                           read_markdown, register_chapters, required_lang, shingle_hashes, tag_script, tidy, visible_text, word_spans, unsegmented)


def detect_language(text, profile_path):
    """The draft's language: the one profile whose scripts include the draft's; several such profiles need --lang."""
    cyrillic = mostly_cyrillic(text)
    path = Path(profile_path)
    scripts = {}   # language: the script its profile was built from, or the language's usual script
    for file in (sorted(path.glob('author-profile.*.json')) if path.is_dir() else [path]):
        try:
            profile = json.loads(file.read_text(encoding='utf-8'))
            lang = required_lang(profile.get('language'))
            scripts[lang] = profile.get('scripts') or [tag_script(lang)]
        except (OSError, ValueError, AttributeError, TypeError) as error:
            raise ValueError(f'{file}: invalid profile language or metadata: {error}') from error
    wanted = 'cyrillic' if cyrillic else 'latin'
    fitting = [lang for lang, found in sorted(scripts.items()) if isinstance(found, list) and wanted in found]
    if len(fitting) > 1:
        raise ValueError(f'profiles for {", ".join(fitting)} all match the draft\'s {wanted} script; pass --lang')
    if len(fitting) == 1:
        return fitting[0]
    return 'ru' if cyrillic else 'en'


def guard_readings(text):
    """The copy guard's three readings of text, so a copied run hides in none: as a reader sees it, with hidden words
    kept and interruptions (comments, tags, link addresses) removed, and the raw text, which holds those interruptions'
    own words. Each is a list of (word, line, own), own marking a word only that reading holds: in the second, one
    between the marks visible_text puts around what the first leaves out; in the raw one, one inside an interruption."""
    out = []
    for n, view in enumerate((visible_text(text), visible_text(text, every_word=True, mark=True), tidy(text))):
        tidied, spans = word_spans(view)
        starts = [0] + [i + 1 for i, c in enumerate(tidied) if c == '\n']
        if n == 1:
            opens = [i for i, c in enumerate(tidied) if c == ONLY_EVERY[0]]
            closes = [i for i, c in enumerate(tidied) if c == ONLY_EVERY[1]]
            own = lambda a, b: bisect.bisect_left(opens, a) > bisect.bisect_left(closes, a)
        elif n == 2:
            regions = []
            for a, b in interruptions(tidied):
                if regions and a <= regions[-1][1]:
                    regions[-1][1] = max(regions[-1][1], b)
                else:
                    regions.append([a, b])
            firsts = [a for a, _ in regions]
            own = lambda a, b: (lambda k: k >= 0 and regions[k][1] > a)(bisect.bisect_left(firsts, b) - 1)
        else:
            own = lambda a, b: False
        out.append([(word, bisect.bisect_right(starts, a), own(a, b)) for word, a, b in spans])
    return out


def reading_map(src, dst):
    """src word index -> dst word index for the words src does not hold alone, line by line where the two readings
    agree word for word: a line read alike maps whole; the lines that differ are aligned together by align, within
    its bounds, and a pair it finds counts only when both words stand on the same line. Past the bounds nothing of
    those lines maps, and their runs count as copies of their own, never merged."""
    lines_src, lines_dst, out = {}, {}, {}
    differing_a, differing_b = [], []
    for i, (word, line, own) in enumerate(src):
        if not own:
            lines_src.setdefault(line, []).append((i, word))
    for j, (word, line, _) in enumerate(dst):
        lines_dst.setdefault(line, []).append((j, word))
    for line, a in lines_src.items():
        b = lines_dst.get(line, [])
        words_a, words_b = [w for _, w in a], [w for _, w in b]
        if words_a == words_b:
            out.update((i, j) for (i, _), (j, _) in zip(a, b))
        else:
            differing_a += [(i, word, line) for i, word in a]
            differing_b += [(j, word, line) for j, word in b]
    if differing_a:
        for tag, a1, a2, b1, _ in align([w for _, w, _ in differing_a], [w for _, w, _ in differing_b]) or ():
            if tag == 'equal':
                out.update((differing_a[a1 + k][0], differing_b[b1 + k][0]) for k in range(a2 - a1)
                           if differing_a[a1 + k][2] == differing_b[b1 + k][2])   # the same line, never a copy on another
    return out


def guard_occurrences(readings, kept):
    """[(reading, index, hash, key)] for each run of the readings whose hash the guard kept. key names the source copy
    it reads: a run of the first reading is its own; a run of a later one is the run it reads in the reading before,
    word for word on its lines, unless it holds a word that reading lacks (own) or does not line up with one, when it
    is a copy of its own. Copies are never merged by place or count alone, and a run read in all three is one."""
    found, keys = [], [{}, {}, {}]
    for r, words in enumerate(readings):
        mapping = reading_map(words, readings[r - 1]) if r else {}
        for h, i in shingle_hashes([w for w, _, _ in words]):
            if h not in kept:
                continue
            key = (r, i)
            if r and not any(own for _, _, own in words[i:i + SHINGLE]):
                target = mapping.get(i)
                if target is not None and all(mapping.get(i + k) == target + k for k in range(SHINGLE)):
                    key = keys[r - 1].get(target, key)
            keys[r][i] = key
            found.append((r, i, h, key))
    return found


def copies(found):
    """{hash: how many source copies of its run} from guard_occurrences."""
    return Counter(h for h, _ in {(h, key) for _, _, h, key in found})


ALIGN_WORDS = 20_000
ALIGN_SECONDS = 10
SHINGLE_WORDS = SHINGLE


START = 'spawn' if sys.platform != 'linux' else 'fork'   # how the alignment's worker starts; spawn re-imports the entry script


def _opcodes(base, cand, out):
    out.put(difflib.SequenceMatcher(None, base, cand, autojunk=False).get_opcodes())


def align(base, cand):
    """Opcodes aligning base words with candidate words, or None past the bounds."""
    if max(len(base), len(cand)) > ALIGN_WORDS:
        return None
    queue = multiprocessing.get_context(START).Queue()
    worker = multiprocessing.get_context(START).Process(target=_opcodes, args=(base, cand, queue))
    worker.start()
    try:   # read while the worker runs: a large result fills the pipe, and joining first would wait on it
        result = queue.get(timeout=ALIGN_SECONDS)
    except Empty:
        result = None
    if worker.is_alive():
        worker.terminate()
    worker.join()
    return result


def same_passage(taken, put):
    """Whether words taken out in one place and words put in at another are one passage moved: they share at least
    three fifths of the longer's words, in any order, so a few words edited on the way still count; a fragment
    rewritten past that is new text."""
    shared = sum((Counter(taken) & Counter(put)).values())
    return shared >= max(1, -(-3 * max(len(taken), len(put)) // 5))


def classify(base_words, cand_words, kept):
    """{index: 'hit' | 'uncertain' | 'exempt'} for each candidate run whose hash the guard kept, and the alignment
    state: 'complete', or why it was bounded. A run inside unchanged text is exempt only when every stretch of CAUGHT words
    through it stays inside that text: the guard keeps one hash for a shared stretch that long, so one beside a changed
    seam may belong to a stretch the change completes, which only the source could tell (uncertain, never clear)."""
    cand_runs = shingle_hashes(cand_words)
    base_runs = shingle_hashes(base_words)
    base_count, cand_count, base_at = {}, {}, {}
    for h, i in base_runs:
        base_count[h] = base_count.get(h, 0) + 1
        base_at.setdefault(h, []).append(i)
    for h, _ in cand_runs:
        cand_count[h] = cand_count.get(h, 0) + 1
    result = {}
    opcodes = align(base_words, cand_words)
    state = 'complete' if opcodes is not None else f'bounded: over {ALIGN_WORDS:,} words or {ALIGN_SECONDS} seconds'
    equal, moved, ambiguous_equal = [], [], set()
    if opcodes is not None:
        equal = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in opcodes if tag == 'equal']
        for tag, i1, i2, j1, j2 in opcodes:
            if tag not in ('insert', 'replace'):
                continue
            moved_from = [base_at[h][0] for h, j in cand_runs if j1 <= j and j + SHINGLE_WORDS <= j2 and h in base_at
                          and cand_count[h] <= base_count[h]]   # a duplicate is already a hit; only moved text is ambiguous
            if not moved_from:   # words too few for a run, taken out in one place and put in here, reordered or edited:
                moved_from = [d1 for kind, d1, d2, _k1, _k2 in opcodes if kind in ('delete', 'replace') and (d1, d2) != (i1, i2)
                              and same_passage(base_words[d1:d2], cand_words[j1:j2])]   # move what lies between too
            if not moved_from:
                continue
            moved.append((j1, j2))   # base text placed somewhere new: this span and the equal spans it crosses are ambiguous
            lo, hi = min(moved_from + [i1]), max(moved_from + [i1])
            for k, (e1, e2, _f1, _f2) in enumerate(equal):
                if e2 > lo and e1 < hi:
                    ambiguous_equal.add(k)
    for h, j in cand_runs:
        if h not in kept:
            continue
        if h not in base_count or cand_count[h] > base_count[h]:
            result[j] = 'hit'   # not the base's text, or repeated more often than the base (which copy is new cannot be told)
            continue
        if opcodes is None:
            result[j] = 'uncertain'
            continue
        inside = next((k for k, (_e1, _e2, f1, f2) in enumerate(equal) if f1 <= j and j + SHINGLE_WORDS <= f2), None)
        if inside is None:
            in_moved = any(a <= j and j + SHINGLE_WORDS <= b for a, b in moved)
            result[j] = 'uncertain' if in_moved else 'hit'   # moved base text, or a run across a changed seam
        else:
            f1, f2 = equal[inside][2], equal[inside][3]
            reach = CAUGHT - SHINGLE_WORDS   # how far a stretch the guard catches can run past this run on either side
            kept_whole = f1 <= max(0, j - reach) and min(len(cand_words), j + SHINGLE_WORDS + reach) <= f2
            result[j] = 'exempt' if kept_whole and inside not in ambiguous_equal else 'uncertain'
    return result, state


def check(candidates, profile_path, lang=None, accepted=None):
    texts = []
    for c in candidates:   # hash the bytes on disk; measure the same bytes, decoded, with line endings unified
        data = Path(c).read_bytes()
        texts.append((Path(c), hashlib.sha256(data).hexdigest(), data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')))
    partial = any(unsegmented(text) or unsegmented(visible_text(text, every_word=True)) for _, _, text in texts)
    lang = required_lang(lang) if lang else detect_language(' '.join(visible_text(t) for _, _, t in texts), profile_path)
    bundle = profiles.load(profile_path, lang)
    profile, guard = bundle['profile'], bundle['guard_data']
    partial = partial or profile.get('segmentation') == 'partial' or (lang in ('ja', 'zh', 'th', 'lo', 'km', 'my') and not profile.get('scripts'))
    styles_partial = profile.get('styles') == 'partial'   # the scan could not settle every stylesheet rule of a source
    emphasis_partial = profile.get('emphasis') == 'partial'   # rules beyond the subset set emphasis in a source: that target is approximate
    kept = set(guard['hashes']) if guard is not None else None
    chapters = [ch for _, _, t in texts for ch in read_markdown(t)]
    measures = measure(chapters, lang)
    if not measures['words']:
        raise NoProse('the candidate has no prose to measure')
    hits, uncertain, exempt, alignment = [], [], 0, None
    base_record = None
    if accepted is not None:
        if len(texts) != 1:
            raise ValueError('--accepted takes one revised candidate and its own accepted base')
        base_data = Path(accepted).read_bytes()
        base_text = base_data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        base_record = {'file': str(Path(accepted)), 'sha256': hashlib.sha256(base_data).hexdigest()}
    if guard is not None:
        rank = {'exempt': 0, 'uncertain': 1, 'hit': 2}
        base_readings = guard_readings(base_text) if base_record is not None else None
        base_copies = copies(guard_occurrences(base_readings, kept)) if base_readings is not None else None
        for path, _, text in texts:
            readings = guard_readings(text)
            found = guard_occurrences(readings, kept)
            counted = copies(found)
            classes = [None] * len(readings)
            if base_readings is not None:
                for r, words in enumerate(readings):
                    classes[r], state = classify([w for w, _, _ in base_readings[r]], [w for w, _, _ in words], kept)
                    alignment = state if alignment in (None, 'complete') else alignment
            strictest, where = {}, {}   # each source copy keeps its strictest class across the readings
            for r, i, h, key in found:
                kind = classes[r].get(i, 'hit') if classes[r] is not None else 'hit'
                if base_copies is not None and counted[h] > base_copies.get(h, 0):
                    kind = 'hit'   # more copies than the base holds, counted across the readings: which is new cannot be told
                if rank[kind] > rank.get(strictest.get(key), -1):
                    strictest[key] = kind
                if key == (r, i):
                    where[key] = (readings[r][i][1], ' '.join(w for w, _, _ in readings[r][i:i + SHINGLE]))
            for key in sorted(strictest, key=lambda k: (where[k][0], k)):
                kind, (line, run) = strictest[key], where[key]
                entry = {'file': str(path), 'line': line, 'words': run}
                if kind == 'hit':
                    hits.append(entry)
                elif kind == 'uncertain':
                    uncertain.append(entry)
                else:
                    exempt += 1
    rows = compare(measures, profile)
    cal = profile.get('calibration')
    voice_distance = calibrated(measures, cal)
    registers = {}
    for name, reg in (profile.get('registers') or {}).items():
        part = measure(register_chapters(chapters, lang, name), lang)
        if part['words']:
            reg_rows = compare(part, {**profile, 'targets': reg['targets']})
            reg_distance, reg_status = register_distance(part, reg, name)
            registers[name] = {'words': part['words'], 'voice_distance': reg_distance, 'calibration': reg_status,
                               'calibration_quantiles': reg['calibration']['quantiles'] if (reg.get('calibration') or {}).get('status') == 'available' else None,
                               'measures': [{'measure': k, 'label': lab, 'value': v, 'low': lo, 'high': hi, 'status': st} for k, lab, v, lo, hi, st in reg_rows]}
    return {
        'language': lang,
        'segmentation': 'partial' if partial else 'supported',
        'styles': 'partial' if styles_partial else 'supported',
        'emphasis': 'partial' if emphasis_partial else 'supported',
        'candidates': [{'file': str(p), 'sha256': sha} for p, sha, _ in texts],
        'words': measures['words'],
        'measure_method': {'tool': MEASURE_METHOD.get(lang, 1), 'profile': profile.get('measure_method', 1)},
        'profile': {**profiles.revision(bundle), 'built': profile.get('built'), 'sources': len(profile.get('sources', [])),
                    'status': bundle['status'], 'unread_approval': bundle['unread_approval'], 'approval_issue': bundle['approval_issue'],
                    'delegated': bundle['delegated'], 'delegation_issue': bundle['delegation_issue']},
        'copy_guard': 'not available' if guard is None else (f'{len(hits)} shared run(s)' if hits else
                                                             f'uncertain: {len(uncertain)} run(s) in moved or ambiguous base text or beside a changed seam' if uncertain else
                                                             'partial: no shared runs found' if partial or styles_partial else 'clear'),
        'copy_guard_uncertain': uncertain,
        'accepted_base': base_record,
        'base_runs_exempt': exempt if base_record is not None else None,
        'alignment': alignment,
        'copy_guard_catches_runs_of': guard.get('catches_runs_of') if guard is not None and not partial and not styles_partial else None,
        'copy_guard_hits': hits,
        'measures': [{'measure': k, 'label': lab, 'value': v, 'low': lo, 'high': hi, 'status': st} for k, lab, v, lo, hi, st in rows],
        'voice_distance': voice_distance,
        'calibration': ('available' if voice_distance else 'the draft lacks a measure the calibration uses (too short or no dialogue)') if cal and cal.get('status') == 'available'
                       else cal.get('reason', 'unavailable') if cal else 'not in this profile: rescan its sources with this ' + host.PRODUCT + ' to add it',
        'calibration_quantiles': cal.get('quantiles') if cal and cal.get('status') == 'available' else None,
        'registers': registers,
        'registers_status': 'available' if profile.get('registers') else 'not in this profile: rescan its sources with this ' + host.PRODUCT + ' to add them',
        'register_calibrations': {name: ((profile.get('registers') or {}).get(name) or {}).get('calibration') and
                                  {k: v for k, v in profile['registers'][name]['calibration'].items() if k in ('status', 'reason', 'quantiles', 'chapters', 'min_words')}
                                  for name in REGISTERS},   # the profile's own, whatever this unit holds
    }


def register_distance(part, reg, name):
    """One register's calibrated distance and its status: available, or why it is not measured."""
    cal = reg.get('calibration')
    if not cal:
        return None, 'not in this profile: rescan its sources with this ' + host.PRODUCT + ' to add it'
    if cal.get('status') != 'available':
        return None, cal.get('reason', 'unavailable')
    if part['words'] < REGISTER_MIN_WORDS[name]:
        return None, f'{part["words"]} words of {name}; its calibration measured chapters with {REGISTER_MIN_WORDS[name]} or more'
    d = calibrated(part, cal)
    return (d, 'available') if d else (None, 'the draft lacks a measure the calibration uses')


def reg_distance(report, name):
    d = ((report.get('registers') or {}).get(name) or {}).get('voice_distance')
    return d['distance'] if d else None


def all_measures(report):
    """The pooled comparisons and each register's, which gate alike."""
    return report['measures'] + [m for reg in (report.get('registers') or {}).values() for m in reg['measures']]


def outside_count(report):
    return sum(1 for m in all_measures(report) if m['status'] == 'outside')


def rank_key(r):
    """Copy-guard runs last, then narration distance, then voice distance (none last for either), then measures outside.
    The narration comes first: a take rewrites it freely, and the pooled distance also weighs the share of dialogue,
    which follows the unit's composition and length more than its wording."""
    narration = reg_distance(r, 'narration')
    return (bool(r['copy_guard_hits']), narration is None, narration or 0,
            r['voice_distance'] is None, r['voice_distance']['distance'] if r['voice_distance'] else 0, outside_count(r))


def rank(candidates, profile_path, lang=None):
    """Each take checked alone and ordered by rank_key."""
    return sorted((check([c], profile_path, lang) for c in candidates), key=rank_key)


def list_units(book, listing):
    """The units a list file names, one path per line relative to the book, in order; blank lines and lines starting
    with # are skipped. A unit outside the book, missing, named twice or not Markdown stops the table: there is no other
    order to fall back on."""
    book, units = Path(book).resolve(), []
    for number, line in enumerate(Path(listing).read_bytes().decode('utf-8').splitlines(), 1):
        rel = line.strip()
        if not rel or rel.startswith('#'):
            continue
        full = (book / rel).resolve()
        if not full.is_relative_to(book):
            raise ValueError(f'{listing}:{number}: {rel} is outside the book')
        if not rel.endswith('.md') or not full.is_file():
            raise ValueError(f'{listing}:{number}: {rel} is not a Markdown file in the book')
        if full in units:
            raise ValueError(f'{listing}:{number}: {rel} is listed twice')
        units.append(full)
    if not units:
        raise ValueError(f'{listing} lists no units')
    return units


class NoProse(ValueError):
    """A candidate with nothing to measure: a part title, an epigraph page."""


def book_check(units, profile_path, lang):
    """One report per unit, in the order given; a unit with nothing to measure, such as a part title, gets a row saying why."""
    reports = []
    for unit in units:
        text = Path(unit).read_bytes().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        if not any(p != SCENE_BREAK and words_of(p[0]) for ch in read_markdown(text) for p in ch['paragraphs']):
            # before its language is chosen: a heading alone, such as a part title, holds too little to choose by
            reports.append({'candidates': [{'file': str(unit)}], 'not_measured': 'the candidate has no prose to measure'})
            continue
        try:
            reports.append(check([unit], profile_path, lang))
        except NoProse as error:   # any other failure, such as an invalid profile or undecodable file, stops the table
            reports.append({'candidates': [{'file': str(unit)}], 'not_measured': str(error)})
    return reports


WITHIN = ('p50', 'p90', 'max')


def narration_quantiles(r):
    cal = (r.get('register_calibrations') or {}).get('narration')
    return cal['quantiles'] if cal and cal.get('status') == 'available' else None


def threshold(r, within):
    """The threshold's selector and exact value, or None when the profile has no narration calibration to read p50, p90 or max from."""
    if isinstance(within, float):
        return {'selector': 'value', 'value': within}
    q = narration_quantiles(r)
    return {'selector': within, 'value': q[within]} if q else None


def _apart(a, b):
    """Two numbers shown with the fewest decimals (two to six) that tell them apart, so a close call reads as one."""
    for places in range(2, 7):
        if f'{a:.{places}f}' != f'{b:.{places}f}' or a == b:
            return f'{a:.{places}f}', f'{b:.{places}f}'
    return repr(a), repr(b)


def restyle_reading(r, within):
    """Where the unit's narration distance falls against the threshold, kept exactly: an order of reading, never an outcome."""
    t = threshold(r, within)
    d = ((r.get('registers') or {}).get('narration') or {}).get('voice_distance')
    out = {'selector': t['selector'] if t else within if isinstance(within, str) else 'value',
           'threshold': t['value'] if t else None, 'narration_distance': d['distance'] if d else None}
    if t is None:
        return out | {'result': 'by reading', 'reason': 'the profile has no narration calibration: rescan its sources with this ' + host.PRODUCT + ' to add it'}
    if d is None:
        reg = (r.get('registers') or {}).get('narration')
        return out | {'result': 'by reading', 'reason': reg['calibration'] if reg else 'the unit has no narration'}
    return out | {'result': 'within' if d['distance'] <= t['value'] else 'beyond'}


def restyle_cell(reading):
    if reading['result'] == 'by reading':
        return 'by reading'
    d, t = _apart(reading['narration_distance'], reading['threshold'])
    label = t if reading['selector'] == 'value' else f'{reading["selector"]} {t}'
    return f'{reading["result"]} {label} (narration {d})'


def summary_row(r, key, within=None):
    tail = ' n/a |' if within else ''
    if r.get('not_measured'):
        return f'| {r["candidates"][0]["file"]} | n/a | 0 | n/a | not measured: {r["not_measured"]} | n/a | n/a | n/a | n/a | n/a |{tail}'
    d = r['voice_distance']
    regs = r.get('registers') or {}
    reg_cells = []
    for name in REGISTERS:
        rd = (regs.get(name) or {}).get('voice_distance')
        cell = f'{rd["distance"]:.2f}' if rd else 'n/a'
        if name == 'narration':
            cell += f' | {round(100 * rd["closer_than_share"])}%' + (' (beyond every source chapter)' if rd['beyond_sources'] else '') if rd else ' | n/a'
        reg_cells.append(cell)
    return (f'| {r["candidates"][0]["file"]} | {key[r["profile"]["measures"]["sha256"]]} | {r["words"]} | ' + (f'{d["distance"]:.2f} | {round(100 * d["closer_than_share"])}%' + (' (beyond every source chapter)' if d['beyond_sources'] else '')
            if d else f'n/a | {r["calibration"]}') + f' | {" | ".join(reg_cells)} | {outside_count(r)} | {len(r["copy_guard_hits"])} |'
            + (f' {restyle_cell(restyle_reading(r, within))} |' if within else ''))


def summary_report(reports, title, within=None):
    measured = [r for r in reports if not r.get('not_measured')]
    out = [title]
    profiles = {}   # a book in several languages is read against one profile per language: each row names its own
    for r in measured:
        profiles.setdefault(r['profile']['measures']['sha256'], r)
    for n, r in enumerate(profiles.values(), 1):
        q = r['calibration_quantiles']
        nq = narration_quantiles(r)
        out += ['', f'Profile P{n} ({r["language"]}): {r["profile"]["measures"]["file"]} (sha256 {r["profile"]["measures"]["sha256"]}), '
                    f'status {r["profile"]["status"]}'
                + (f'; its source chapters\' distances from the rest: median {q["p50"]:.2f}, 90th percentile {q["p90"]:.2f}, farthest {q["max"]:.2f}' if q else '')
                + (f'; their narration\'s: median {nq["p50"]:.2f}, 90th percentile {nq["p90"]:.2f}, farthest {nq["max"]:.2f}' if nq else
                   '; no narration calibration: rescan its sources with this ' + host.PRODUCT + ' to add it')]
    if not measured:
        out += ['', 'No unit could be measured.']
    key = {sha: f'P{n}' for n, sha in enumerate(profiles, 1)}
    out += ['', '| File | Profile | Words | Voice distance | Closer than (its source chapters) | Narration distance | Narration closer than | '
                'Dialogue distance | Measures outside | Copy-guard runs |' + (' Restyle |' if within else ''),
            '|---|---|---|---|---|---|---|---|---|---|' + ('---|' if within else '')]
    out += [summary_row(r, key, within) for r in reports]
    out += ['', 'The voice distance pools narration and dialogue, so it also weighs how much of a unit is dialogue, which depends on the '
                'unit\'s composition and length; the narration and dialogue distances leave that out and show best what rewording can move.']
    if within:
        chosen = (f'{within!r} as given' if isinstance(within, float) else f'the narration calibration\'s {within}, per profile above')
        out += [f'Restyle reads each unit\'s narration distance against {chosen}: beyond means its narration lies farther from the profile '
                'than the sources\' own chapters mostly do, so read it first; within means it lies nearer; by reading means the unit holds too '
                'little narration to measure, or the profile has no narration calibration. It orders the reading; a reading decides whether '
                'a unit needs a restyle, wherever it falls.']
    out += ['The order and the distances locate; reading decides. A short take reads less reliably than a chapter of 1,200 words or more.']
    return '\n'.join(out)


PROVISIONAL = {'default': " (the shipped default: it guides only what the brief and the author's accepted prose leave open)",
               'draft': " (not yet approved: it guides only what the brief and the author's accepted prose leave open)"}


def fmt(v):
    return 'n/a' if v is None else (f'{v:.3f}' if isinstance(v, float) and abs(v) < 10 else (f'{v:.1f}' if isinstance(v, float) else str(v)))


def text_report(r):
    out = ['Voice check', '',
           'Candidate: ' + ', '.join(f'{c["file"]} (sha256 {c["sha256"]})' for c in r['candidates']),
           f'Language: {r["language"]}; words: {r["words"]}',
           f'Profile: {r["profile"]["prose"]["file"]} (sha256 {r["profile"]["prose"]["sha256"]}), measures '
           f'{r["profile"]["measures"]["file"]} (sha256 {r["profile"]["measures"]["sha256"]}); built {r["profile"]["built"]}, '
           f'{r["profile"]["sources"]} source(s)',
           f'Profile status: {r["profile"]["status"]}' + PROVISIONAL.get(r['profile']['status'], '')
           + (f'; its approval line "{r["profile"]["unread_approval"]}" does not read as one date: if the author approved '
              'it, write that date alone, such as 2026-10-03' if r['profile']['unread_approval'] else '')
           + (f"; {r['profile']['approval_issue']}" if r['profile']['approval_issue'] else '')
           + (f" under {r['profile']['delegated']} (delegated, not the author's own approval)" if r['profile'].get('delegated') else '')
           + (f"; {r['profile']['delegation_issue']}" if r['profile'].get('delegation_issue') else ''),
           f'Copy guard: {r["copy_guard"]}' + (f', {r["profile"]["guard"]["file"]} (sha256 {r["profile"]["guard"]["sha256"]})'
                                               if r['profile']['guard'] != 'absent' else '')
           + (f' (every shared run of {r["copy_guard_catches_runs_of"]} space-delimited words or more is found within supported extraction)'
                                                if r['copy_guard_catches_runs_of'] else '')]
    method = r.get('measure_method') or {'tool': 1, 'profile': 1}
    out.append(f'Measure method: {method["tool"]}' + ('' if method['tool'] == method['profile'] else
               f'; the profile was scanned by method {method["profile"]}, so the targets this tool reads differently are not compared '
               'until the profile is rescanned from its sources and approved again'))
    if r['segmentation'] == 'partial':
        out += ['Coverage: partial. Source or candidate includes unsupported word segmentation. Word and sentence measures are approximate; '
                'copy-guard matches remain useful, but no complete clear is established.']
    if r.get('styles') == 'partial':
        out += ['Styles: partial. The profile\'s scan could not settle every stylesheet rule of a source, so text it read or left out may differ '
                'from what a reader sees; copy-guard matches remain useful, but no complete clear is established.']
    if r.get('emphasis') == 'partial':
        out += ['Emphasis: partial. A source\'s stylesheet sets italic or bold by rules beyond the import\'s subset, which the profile does not '
                'count, so its emphasized-words target is approximate; the copy guard is not affected.']
    for h in r['copy_guard_hits']:
        out.append(f'  {h["file"]}:{h["line"]}: "{h["words"]}"')
    if r.get('accepted_base'):
        out.append(f'Accepted base: {r["accepted_base"]["file"]} (sha256 {r["accepted_base"]["sha256"]}); alignment {r["alignment"]}; '
                   f'{r["base_runs_exempt"]} run(s) kept unchanged in place')
    for h in r.get('copy_guard_uncertain') or []:
        out.append(f'  uncertain {h["file"]}:{h["line"]}: "{h["words"]}"')
    d = r.get('voice_distance')
    if d:
        out.append(f'Voice distance: {d["distance"]:.2f} over {d["measures_used"]} measure(s); closer to the profile than '
                   f'{round(100 * d["closer_than_share"])}% of its {d["source_chapters"]} source chapters'
                   + ('; farther than every source chapter' if d['beyond_sources'] else '')
                   + ('; the draft is shorter than the 1,200-word chapters the calibration measured, so this reads less reliably' if r['words'] < 1200 else ''))
    else:
        out.append(f'Voice distance: not measured ({r.get("calibration", "unavailable")})')
    out += ['', '| Measure | Draft | Target range | Status |', '|---|---|---|---|']
    for m in r['measures']:
        out.append(f'| {m["label"]} | {fmt(m["value"])} | {fmt(m["low"])} to {fmt(m["high"])} | {m["status"]} |')
    for name in REGISTERS:
        reg = (r.get('registers') or {}).get(name)
        if reg:
            rd = reg.get('voice_distance')
            dist = (f'voice distance {rd["distance"]:.2f}, closer to the profile than {round(100 * rd["closer_than_share"])}% of its '
                    f'{rd["source_chapters"]} source chapters\' {name}' + ('; farther than every one' if rd['beyond_sources'] else '')
                    if rd else f'voice distance not measured ({reg.get("calibration", "unavailable")})')
            out += ['', f'{name.capitalize()} only ({reg["words"]} words; {dist}):', '', '| Measure | Draft | Target range | Status |', '|---|---|---|---|']
            out += [f'| {m["label"]} | {fmt(m["value"])} | {fmt(m["low"])} to {fmt(m["high"])} | {m["status"]} |' for m in reg['measures']]
    counts = {}
    for m in r['measures']:
        key = m['status'].split(' (')[0]
        counts[key] = counts.get(key, 0) + 1
    out += ['', 'Summary: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())),
            host.REPORT_NOTE]
    return '\n'.join(out)


def main(argv=None, order_reader=None, profile_default=None, description=None, prog=None):
    """The command line. A product built on mdrestyler may pass order_reader(book, order) -> unit paths, which adds
    --order and replaces --list, and profile_default(book) -> the profile folder --book uses without --profile."""
    for stream in (sys.stdout, sys.stderr):   # a terminal that cannot show a character gets an escape, not a crash
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(prog=prog, description=description or __doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('candidates', nargs='*', help='Markdown draft files')
    parser.add_argument('--profile', help='the profile folder, or an author-profile.<lang>.json file')
    parser.add_argument('--rank', action='store_true', help='check each file alone as a take of the same unit and order the takes by fit')
    parser.add_argument('--book', help='check every unit in the book\'s reading order alone, one row each')
    if order_reader:
        parser.add_argument('--order', default='README.md#Contents', help='with --book: the file and section that own the reading order')
    else:
        parser.add_argument('--list', help='with --book: a file naming the units in reading order, one path per line, relative to the book')
    parser.add_argument('--within', default=None, help='with --book: the narration distance a unit may lie within and need no restyle: '
                        'p50, p90 (default) or max of the narration calibration, or a number')
    parser.add_argument('--lang', help='profile language (default: from the draft\'s script)')
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    parser.add_argument('--strict', action='store_true', help='exit 1 when a measure is outside its range and not marked weak, '
                        'or could not be compared with a profile scanned by another measure method')
    parser.add_argument('--accepted', help="a revision's own accepted base: the unit's exact accepted text before the revision")
    args = parser.parse_args(argv)
    if args.book and (args.candidates or args.rank or args.accepted):
        parser.error('--book checks the book\'s own units: give no files, --rank or --accepted with it')
    if args.within is not None and not args.book:
        parser.error('--within reads the book table: give it with --book')
    within = args.within or 'p90'
    if within not in WITHIN:
        try:
            within = float(within)
        except ValueError:
            within = -1.0
        if not within > 0 or within != within or within == float('inf'):
            parser.error('--within takes p50, p90, max or a positive number')
    if not args.book and not args.candidates:
        parser.error('give the draft files, or --book BOOK')
    if not args.book and not args.profile:
        parser.error('--profile is required')
    if args.book and not args.profile and not profile_default:
        parser.error('--profile is required')
    if args.book and not order_reader and not args.list:
        parser.error('--book needs --list, the file that names the units in reading order')
    if not args.book and not order_reader and args.list:
        parser.error('--list names the units of --book: give it with --book')
    if args.rank and (len(args.candidates) < 2 or args.accepted):
        parser.error('--rank takes two or more takes of one unit and no --accepted')
    if args.book or args.rank:
        try:
            if args.book:
                units = order_reader(Path(args.book), args.order) if order_reader else list_units(args.book, args.list)
                reports = book_check(units, args.profile or str(profile_default(Path(args.book))), args.lang)
                for r in reports:
                    if not r.get('not_measured'):
                        r['restyle_reading'] = restyle_reading(r, within)   # the selector and exact values; restyle is its table cell
                    r['restyle'] = 'n/a' if r.get('not_measured') else restyle_cell(r['restyle_reading'])
                title = f'Voice check of the book {args.book}, unit by unit in reading order'
            else:
                reports, title = rank(args.candidates, args.profile, args.lang), 'Takes ranked by fit (best first)'
            print(json.dumps(reports, indent=1, ensure_ascii=False) if args.json else summary_report(reports, title, within if args.book else None))
        except Exception as error:
            parser.exit(2, f'Voice check failed: {error}\n')
        sys.exit(0)   # a ranking or a book table informs; the per-candidate checks gate
    try:
        report = check(args.candidates, args.profile, args.lang, args.accepted)
        print(json.dumps(report, indent=1, ensure_ascii=False) if args.json else text_report(report))
    except Exception as error:   # any failure exits 2, never 1, which means the copy guard found a run
        parser.exit(2, f'Voice check failed: {error}\n')
    outside = any(m['status'] == 'outside' or m['status'].startswith('incomparable') for m in all_measures(report))   # a weak measure informs; it does not fail
    sys.exit(1 if report['copy_guard_hits'] or (args.strict and outside) else 0)


if __name__ == '__main__':
    main()

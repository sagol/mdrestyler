"""An author profile's files, read once: the prose profile (AUTHOR_PROFILE.<lang>.md, the described voice and its
approval), the measures (author-profile.<lang>.json) and the optional copy guard (copy-guard.<lang>.json), each with
its bytes and SHA-256. Installing and checking both load profiles here, so they accept and refuse the same things. The three hashes together are the profile's revision. Standard library only."""
import datetime
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

from . import names as host
from .metrics import CALIBRATION_METHOD, CALIBRATION_MIN_CHAPTERS, CAUGHT, FUNCTION_WORDS, REGISTERS, ISO_639_2, LANGUAGE_NAMES, MEASURE_METHOD, SHINGLE, TARGETS, WINDOW, _remove_hidden, available_targets, lang_code

GUARD_SCHEMA = 'mdrestyler-copy-guard/1'   # what a scan writes
PROFILE_SCHEMA = 'mdrestyler-author-profile/1'


def guard_schemas():
    """The guard schemas a check reads: this one, and any a configured product wrote by the same algorithm."""
    return (GUARD_SCHEMA,) + tuple(host.EXTRA_GUARD_SCHEMAS)


def profile_schemas():
    return (PROFILE_SCHEMA,) + tuple(host.EXTRA_PROFILE_SCHEMAS)


UNIT_MEASURES = {k for k in TARGETS if k.endswith('_share') or k == 'mattr'} | {'function_word_similarity'}   # 0 to 1
HASH = re.compile(r'[0-9a-f]{12}')   # the SHA-1 prefix a scan writes
SHA256 = re.compile(r'[0-9a-f]{64}')

DEFAULTS = Path(__file__).resolve().parent / 'defaults'
APPROVAL = re.compile(r'[ \t]*(?:[-*+][ \t]+)?(?:Approved by the author on|Утвержд[её]н автором)[ \t]*:?[ \t]*(.*)', re.I)   # on plain()
DELEGATED = re.compile(r'[ \t]*(?:[-*+][ \t]+)?(?:Approved under delegation|Утвержд[её]н по делегированию)[ \t]*:[ \t]*([A-Z][A-Z0-9]*-[0-9]+)[ \t]*\.?', re.I)   # on plain()
DEFAULT = re.compile(r'^[ \t]*[*_]{0,2}(?:Status|Статус)[*_]{0,2}[ \t]*:[ \t]*(?:default|по умолчанию)', re.M | re.I)
# Month names by language, January first, so a date written in words resolves to a real one; full names and common
# abbreviations, the genitive where a language dates with it. A month word not here approves nothing: write the date in numbers.
MONTH_NAMES = """
en january february march april may june july august september october november december
en jan feb mar apr - jun jul aug sep|sept oct nov dec
ru января февраля марта апреля мая июня июля августа сентября октября ноября декабря
ru янв фев мар апр - июн июл авг сен|сент окт ноя|нояб дек
uk січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня
uk січ лют бер квіт трав черв лип серп вер жовт лист груд
fr janvier février mars avril mai juin juillet août septembre octobre novembre décembre
fr janv févr - avr - - juil - sept oct nov déc
de januar|jänner februar märz april mai juni juli august september oktober november dezember
de jan feb mär apr - jun jul aug sep|sept okt nov dez
es enero febrero marzo abril mayo junio julio agosto septiembre|setiembre octubre noviembre diciembre
es ene feb mar abr may jun jul ago sep|sept oct nov dic
it gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre
it gen feb mar apr mag giu lug ago set ott nov dic
pt janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro
pt jan fev mar abr mai jun jul ago set out nov dez
nl januari februari maart april mei juni juli augustus september oktober november december
nl jan feb mrt apr - jun jul aug sep|sept okt nov dec
pl stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia
pl styczeń luty marzec kwiecień maj czerwiec lipiec sierpień wrzesień październik listopad grudzień
pl sty lut mar kwi - cze lip sie wrz paź lis gru
cs ledna února března dubna května června července srpna září října listopadu prosince
cs leden únor březen duben květen červen červenec srpen - říjen listopad prosinec
sv januari februari mars april maj juni juli augusti september oktober november december
sv jan feb mar apr - jun jul aug sep|sept okt nov dec
da januar februar marts april maj juni juli august september oktober november december
da jan feb mar apr - jun jul aug sep|sept okt nov dec
no januar februar mars april mai juni juli august september oktober november desember
no jan feb mar apr - jun jul aug sep|sept okt nov des
fi tammikuuta helmikuuta maaliskuuta huhtikuuta toukokuuta kesäkuuta heinäkuuta elokuuta syyskuuta lokakuuta marraskuuta joulukuuta
fi tammik helmik maalisk huhtik toukok kesäk heinäk elok syysk lokak marrask jouluk
hu január február március április május június július augusztus szeptember október november december
hu jan febr márc ápr máj jún júl aug szept okt nov dec
tr ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık
tr oca şub mar nis may haz tem ağu eyl eki kas ara
el ιανουαρίου φεβρουαρίου μαρτίου απριλίου μαΐου ιουνίου ιουλίου αυγούστου σεπτεμβρίου οκτωβρίου νοεμβρίου δεκεμβρίου
el ιαν φεβ μαρ απρ μαΐ ιουν ιουλ αυγ σεπ οκτ νοε δεκ
"""


def fold(text):
    """Text compared without case: casefolded, then composed again (casefold decomposes ΐ), with Turkish İ, in any
    form, as i. Approval values and the word tables both go through it, so final ς matches as σ on both sides."""
    return unicodedata.normalize('NFC', text.casefold().replace('i\u0307', 'i'))


MONTHS, MONTH_LANGS = {}, {}   # a month name to its month, and to the languages that write it
for _row in fold(MONTH_NAMES).split('\n'):
    for _n, _cell in enumerate(_row.split()[1:], 1):
        for _name in {v for cell in _cell.split('|') if _cell != '-' for v in (cell, cell.replace('ı', 'i'))}:   # MAYIS folds to mayis
            if MONTHS.setdefault(_name, _n) != _n:
                raise ValueError(f'month name {_name} means two months')
            MONTH_LANGS.setdefault(_name, set()).add(_row.split()[0])
# Weekdays by language, Monday first, so a weekday beside a date must be that date's (Sunday, 3 October 2026 is not).
WEEKDAY_NAMES = """
en monday|mon tuesday|tue|tues wednesday|wed thursday|thu|thur|thurs friday|fri saturday|sat sunday|sun
ru понедельник|пн вторник|вт среда|ср четверг|чт пятница|пт суббота|сб воскресенье|вс
uk понеділок|пн вівторок|вт середа|ср четвер|чт пʼятниця|п'ятниця|пт субота|сб неділя|нд
fr lundi|lun mardi|mar mercredi|mer jeudi|jeu vendredi|ven samedi|sam dimanche|dim
de montag|mo dienstag|di mittwoch|mi donnerstag|do freitag|fr samstag|sonnabend|sa sonntag|so
es lunes|lun martes|mar miércoles|mié jueves|jue viernes|vie sábado|sáb domingo|dom
it lunedì|lun martedì|mar mercoledì|mer giovedì|gio venerdì|ven sabato|sab domenica|dom
pt segunda|seg terça|ter quarta|qua quinta|qui sexta|sex sábado|sáb domingo|dom
nl maandag|ma dinsdag|di woensdag|wo donderdag|do vrijdag|vr zaterdag|za zondag|zo
pl poniedziałek|pon wtorek|wt środa|śr czwartek|czw piątek|pt sobota|sob niedziela|niedz|nd
cs pondělí|po úterý|út středa|st čtvrtek|čt pátek|pá sobota|so neděle|ne
sv måndag|mån tisdag|tis onsdag|ons torsdag|tor fredag|fre lördag|lör söndag|sön
da mandag|man tirsdag|tir onsdag|ons torsdag|tor fredag|fre lørdag|lør søndag|søn
no mandag|man tirsdag|tir onsdag|ons torsdag|tor fredag|fre lørdag|lør søndag|søn
fi maanantai|maanantaina|ma tiistai|tiistaina|ti keskiviikko|keskiviikkona|ke torstai|torstaina|to perjantai|perjantaina|pe lauantai|lauantaina|la sunnuntai|sunnuntaina|su
hu hétfő|h kedd|k szerda|sze csütörtök|cs péntek|p szombat|szo vasárnap
tr pazartesi|pzt salı|sal çarşamba|çar perşembe|per cuma|cum cumartesi|cmt pazar|paz
el δευτέρα|δευ τρίτη|τρι|τρί τετάρτη|τετ πέμπτη|πεμ|πέμ παρασκευή|παρ σάββατο|σαβ|σάβ κυριακή|κυρ
ja 月曜日|月曜|月 火曜日|火曜|火 水曜日|水曜|水 木曜日|木曜|木 金曜日|金曜|金 土曜日|土曜|土 日曜日|日曜|日
ko 월요일|월 화요일|화 수요일|수 목요일|목 금요일|금 토요일|토 일요일|일
zh 星期一|周一|週一 星期二|周二|週二 星期三|周三|週三 星期四|周四|週四 星期五|周五|週五 星期六|周六|週六 星期日|星期天|周日|週日
"""
WEEKDAYS = {}   # a word to its weekday in each language: so is Saturday in Czech, Sunday in German
for _row in fold(WEEKDAY_NAMES).split('\n'):
    for _n, _cell in enumerate(_row.split()[1:]):
        for _name in {v for cell in _cell.split('|') for v in (cell, cell.replace('ı', 'i'))}:   # SALI folds to sali
            WEEKDAYS.setdefault(_name, {})[_row.split()[0]] = _n
# Words a period may follow mid-line: a weekday's short forms (sat, Sa, Σάβ), year words (г., r.) and kl., godz.
ABBREVIATIONS = {v for _cell in fold(WEEKDAY_NAMES).split() for v in _cell.split('|')[1:] if len(v) < len(_cell.split('|')[0])}
ABBREVIATIONS |= set(fold('г р r kl godz').split())
# Words a date may come with besides a weekday: the articles some languages date with, year words, feira of segunda-feira.
FILLER = set(fold('the of on approved am г года р року roku r le el il den der dne feira').split()) | set(WEEKDAYS)
# Words that only qualify a time, so they stand beside a date only when a real time does: one phrase of these before
# it (a las 14:30, 下午 2:30), Uhr or one zone after it (14.30 Uhr, 14:30 UTC). TIME itself takes a.m. or p.m. after a
# time, so am alone is only German for on the, before the date (am 3. Oktober).
TIME_PHRASES = set(fold('at|à|a|a las|alle|às|as|um|om|o|o godz|godz|v|ve|kl|klockan|klo|saat|στις|в|о').split('|'))
CONNECTORS = {word for phrase in TIME_PHRASES for word in phrase.split()}
ZONES = set('utc gmt cet cest eet eest msk est edt cst cdt pst pdt bst jst kst'.split())
MERIDIEMS = set('上午 下午 午前 午後 오전 오후'.split())   # before a time
TRAILS = ZONES | {'uhr'}
TIME_WORDS = CONNECTORS | MERIDIEMS | TRAILS
WORD = r"[^\W\d_]+(?:['ʼ][^\W\d_]+)?"
SPACED = r'[^\W\d_\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]'   # a letter of a script written with spaces: not kana, Han or Hangul
ORDINAL = r'(?P<o>st|nd|rd|th|er|re|ème|e|ste|de|º|°|:e|:a|-?го|-?е)'   # 3rd, 1er, 1º, 3:e, 3-го
DAY = r'(?P<d>\d{1,2})(?:\.?' + ORDINAL + r'\.?|\.)?(?!\.)'   # 3, 3., 3rd, 1.º; never 3.., nor 2026 October 3..
MONTH, YEAR, YEAR4 = r'(?P<m>[^\W\d_]{3,})\.?', r'(?P<y>\d{4}|\d{2})(?!\d)', r'(?P<y>\d{4})(?!\d)'   # 3 Oct 26; a leading year has four digits
MERIDIEM = r'\s*(?:a\.?m\.?|p\.?m\.?)(?!\w)'
TIME = re.compile(r'(?<!\d)(?:\d{1,2}\s*(?:h|uhr|ч|時|시|点)\.?\s*\d{1,2}\s*(?:min|мин|分|분)?\.?(?![\w:])'   # 14 h 30 min, 14時30分; 14h30:00 falls through
                  r'|t?\d{1,2}[:h.]\d{2}(?::\d{2}(?:[.,]\d+)?)?'   # 14:30, 14h30, 14.30, T14:30:00.5
                  r'|t\d{4}(?:\d{2}(?:[.,]\d+)?)?'   # T1430, T143000, ISO 8601 basic
                  r'|\d{1,2}(?=' + MERIDIEM + r')'   # the 2 of 2pm
                  r'|\d{1,2}\s*(?:h|uhr|ч|時|시|点)(?!\w))'   # 14 Uhr, 14h
                  r'(?:' + MERIDIEM + r')?'   # one meridiem for every form: 2pm, 2:30 p.m., 2h30 p.m.
                  r'(?:\s*(?:z|(?:utc|gmt)?\s*[+−-]\d{1,2}(?::?\d{2})?)(?![\w]))?(?!\d)')   # and one zone: Z, +03:00, UTC+3
DATES = [re.compile(r'(?<!\d)(?P<y>\d{4})\s*(?P<s>[-/.])\s*(?P<m>\d{1,2})\s*(?P=s)\s*(?P<d>\d{1,2})(?!\d)'),   # 2026-10-03, 2026/10/03, 2026. 10. 3.
         re.compile(r'(?<!\d)(?P<d>\d{1,2})\s*(?P<s>[-/.])\s*(?P<m>\d{1,2})\s*(?P=s)\s*(?P<y>\d{4}|\d{2})(?!\d)'),   # 03.10.2026, 3. 10. 2026, 03.10.26, 10/03/2026 either way
         re.compile(r'(?<!\d)' + DAY + r'\s+(?:(?:of|de)\s+)?' + MONTH + r',?\s+(?:de\s+)?' + YEAR),   # 3 October 2026, 3. Oktober 2026, 3 de octubre de 2026
         re.compile(MONTH + r'\s+' + DAY + r',?\s+' + YEAR),   # October 3rd, 2026
         re.compile(r'(?<!\d)' + YEAR4 + r'\.?\s+' + MONTH + r'\s+' + DAY),   # 2026. október 3.
         re.compile(r'(?<!\d)(?P<d>\d{1,2})' + ORDINAL + r'?(?P<s>[-/.])(?P<m>[^\W\d_]{3,})\.?(?P=s)' + YEAR),   # 03-Oct-2026, 3rd-Oct-26
         re.compile(r'(?<!\d)(?P<y>\d{4})(?P<s>[-/.])(?P<m>[^\W\d_]{3,})(?P=s)(?P<d>\d{1,2})' + ORDINAL + r'?(?!\d)'),   # 2026-Oct-03, 2026-Oct-3rd
         re.compile(r'(?<!\d)(?P<y>\d{4})\s*[年년]\s*(?P<m>\d{1,2})\s*[月월]\s*(?P<d>\d{1,2})\s*[日일号號]?'),   # 2026年10月3日, 3号
         re.compile(r'(?<!\d)(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})(?!\d)')]   # 20261003, ISO 8601 basic



def real_time(text, twelve=False):
    """Whether a matched time is one: an hour to 24 (1 to 12 with a meridiem in it, or beside it when twelve; 24 only
    as 24:00 with every later part zero), minutes and seconds in range, a zone offset within 14:59."""
    zone = re.search(r'[+−-](\d{1,2})(?::?(\d{2}))?\s*$', text)
    if zone and (int(zone[1]) > 14 or int(zone[2] or 0) > 59):
        return False
    core = text[:zone.start()] if zone else text
    runs = re.findall(r'\d+', core)
    parts = [int(r[i:i + 2]) for r in runs[:1] for i in range(0, len(r), 2)] if len(runs[0]) in (4, 6) else [int(r) for r in runs[:1]]
    parts += [int(r) for r in runs[1:]]   # hour, minute, second (T143000 split in pairs), then any fraction
    hour, minute, second = (parts + [0, 0])[:3]
    if hour == 24 and (len(parts) < 2 or any(parts[1:])):   # only 24:00 ends a day
        return False
    return (1 <= hour <= 12 if twelve or re.search(r'[ap]\.?m', core) else hour <= 24) and minute <= 59 and second <= 60



def ordinal_fits(day, suffix):
    """Whether an ordinal suffix belongs to its day: 1st, 2nd, 3rd, 11th; French 1er, 3ème; Dutch 1ste, 3de, 8ste,
    20ste; 1º only on the first; Swedish 1:a, 3:e. A bare e (French 3e, Dutch 1e) and Russian -го or -е fit any day."""
    if suffix in ('st', 'nd', 'rd', 'th'):
        return suffix == ('th' if 10 <= day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th'))
    if suffix in ('ste', 'de'):
        return suffix == ('ste' if day in (1, 8) or day >= 20 else 'de')
    if suffix in (':a', ':e'):
        return suffix == (':a' if day % 10 in (1, 2) and day % 100 not in (11, 12) else ':e')
    if suffix in ('er', 're', 'º', '°'):
        return day == 1
    return suffix != 'ème' or day > 1


def plain(line):
    """A line without its balanced emphasis and code spans, which are presentation; a stray * or _ stays."""
    n = 1
    while n:
        line, n = re.subn(r'(?<!\w)(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)', r'\2', line)
    return re.sub(r'(`+)(.+?)\1', r'\2', line)


def approves(value):
    """Whether an approval line's plain() value is one real calendar date in a common spelling (DATES), its month a
    number or a name in MONTH_NAMES, with nothing around it but filler such as the date's own weekday or "г." and commas or periods. A placeholder
    (3 TBD 2026), an impossible date (31 février 2026), a refusal, a month without a day, a bracketed, struck-out or
    questioned date, or a note beside it ("2026-10-03, pending notes") approves nothing."""
    text = fold(value)
    if re.search(r'\.\s*\.', text):   # a doubled period anywhere, a time's own included: 2:30 p.m..
        return False
    text = re.sub(r'[(（]\s*([^\W\d_]+)\s*[)）]', lambda m: f' {m[1]} ' if m[1] in FILLER else m[0], text)   # 2026年10月3日(土); a date in brackets stays bracketed
    for form in DATES:
        for found in form.finditer(text):
            if len(found['y']) == 2 and any(t.start() <= found.start('y') < t.end() for t in TIME.finditer(text)):
                continue   # a time's hour cannot also supply the year: October 3 14h has none
            rest = text[:found.start()] + ' ' + text[found.end():]
            times = [t for t in TIME.finditer(rest) if real_time(t[0])]   # an impossible time stays in the rest, and keeps it draft
            before, after = (rest[:times[0].start()], rest[times[0].end():]) if len(times) == 1 else (rest, '')
            skeleton = text[:found.start()] + '0' + text[found.end():]   # the date, then the time, as 0
            skeleton = skeleton[:times[0].start()] + '0' + skeleton[times[0].end():] if len(times) == 1 else skeleton
            if (re.search(r'(?:^|\s)[,.]|,\s*[,.]|0\.(?!\s*$)|' + SPACED + '0|0' + SPACED, skeleton)   # a mark follows a word, the date or time, once; no word glued to them
                    or not set(re.findall(WORD + r'(?=\.(?!\s*$))', skeleton)) <= ABBREVIATIONS):   # mid-line, a period ends Sa., г., kl.
                continue
            lead, trail = (re.findall(WORD, part) for part in (before, after))
            tokens = lead + trail
            zones = sum(t in ZONES for t in tokens) + sum(bool(re.search(r'z$|[+−-]\d|utc|gmt', t[0])) for t in times)   # TIME made a final z a zone
            meridiems = sum(t in MERIDIEMS for t in tokens) + sum(bool(re.search(r'[ap]\.?m', t[0])) for t in times)
            loose = re.sub(r"(?<=[^\W\d_])['ʼ-](?=[^\W\d_])", '', before + ' ' + after)   # a hyphen or apostrophe joins two letters
            if (re.search(r"[^\w\s,.]|[\d_]", loose) or len(times) > 1 or zones > 1 or meridiems > 1   # no ? ~ ( [ _ -, note, second time, am pm, UTC PST
                    or len(tokens) > len(set(tokens)) or not set(tokens) <= FILLER | (TIME_WORDS if times else set())   # nor at at, nor a stray "at pm"
                    or set(lead) & TRAILS or set(trail) & (CONNECTORS | MERIDIEMS)   # nor UTC 14:30, 14:30 at
                    or ' '.join(t for t in lead if t in CONNECTORS) not in TIME_PHRASES | {''}   # nor at um 14:30
                    or set(lead) & MERIDIEMS and not real_time(times[0][0], twelve=True)):   # nor 下午 18:30
                continue
            if not ordinal_fits(int(found['d']), found.groupdict().get('o')):   # October 2st
                continue
            month = int(found['m']) if found['m'].isdigit() else MONTHS.get(found['m'])
            if not month:   # a word the tables do not know, such as TBD: no date
                continue
            langs = MONTH_LANGS.get(found['m'])   # a month name sets the weekday's language: So. beside Oktober is Sunday
            weekdays = [{d for lang, d in WEEKDAYS[t].items() if langs is None or lang in langs} for t in tokens if t in WEEKDAYS]
            if langs is None and any(len(days) > 1 for days in weekdays):
                continue   # beside 03.10.2026, So. could be German Sunday or Czech Saturday
            if 'am' in tokens and ('am' not in re.findall(WORD, text[:found.start()]) or langs and 'de' not in langs):
                continue   # am, German on the, comes before a German or numeric date: never October 3, 2026 am 18:30
            readings = [(month, int(found['d']))] + ([(int(found['d']), month)] if form is DATES[1] else [])
            year = int(found['y']) + (2000 if len(found['y']) == 2 else 0)
            for month, day in readings:
                try:
                    date = datetime.date(year, month, day)
                except ValueError:   # an impossible date, such as 2026-02-30
                    continue
                if all(date.weekday() in days for days in weekdays):   # Sunday, 3 October 2026 is a Saturday
                    return True
    return False


def unsafe_destination(folder, names, within=None):
    """Why folder or one of its named files cannot be written in place, or '': a write follows a symbolic link, a
    dangling one included, so a link at any of these paths could put profile text or a book's samples somewhere else,
    such as over an accepted chapter. Every destination is a real path, or absent, and with within (a book) the folder
    resolves inside it, so a linked parent folder cannot lead out either."""
    folder = Path(folder)
    if within is not None and not folder.resolve().is_relative_to(Path(within).resolve()):
        return f'{folder} leads outside {within} through a symbolic link; profile files are written only inside the book'
    for path in [folder] + [folder / name for name in names]:
        if path.is_symlink():
            return f'{path} is a symbolic link; profile files and samples are written only to real paths, so remove the link first'
        if path != folder and path.exists() and not path.is_file() and path.name != 'history':
            return f'{path} is not a regular file'
    return ''


def family(code):
    return [f'AUTHOR_PROFILE.{code}.md', f'author-profile.{code}.json', f'copy-guard.{code}.json']


def spellings(lang):
    """lang, then every other code or name an earlier release named the same language's profiles by: three-letter and
    withdrawn codes (jpn, iw), and the language names it read from a book's metadata (english)."""
    return [lang] + sorted(c for c, two in ISO_639_2.items() if two == lang) + sorted(n for n, code in LANGUAGE_NAMES.items() if code == lang)


def every_name(lang):
    """The file names of lang's profile in every spelling: what a replacement archives and a write must not follow."""
    return [name for code in spellings(lang) for name in family(code)]


def held(lang, folder):
    """The spellings of lang that folder holds a profile file under, two-letter first: an earlier release named a
    profile by the three-letter code its book was tagged with (author-profile.jpn.json), the same language as ja."""
    return [code for code in spellings(lang) if any((Path(folder) / n).exists() or (Path(folder) / n).is_symlink() for n in family(code))]


def files_for(lang, folder=None):
    """A profile's file names for lang; with folder, as that folder holds them, one spelling for all three files."""
    codes = held(lang, folder) if folder is not None else []
    return family(codes[0] if codes else lang)


def approval_fields(markdown):
    """Fields directly under level-2 Approval/Утверждение. Older profiles may use one field below their title.
    Code, hidden text and other sections carry no approval. Ambiguous active fields stay draft."""
    # Approval metadata is never authority, including YAML keys outside the prose extractor's heuristic.
    text = markdown.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\A\ufeff?---[ \t]*\n.*?(?:\n(?:---|\.\.\.)[ \t]*(?:\n|$)|\Z)', '', text, count=1, flags=re.S)
    text = re.sub(r'<!--.*?(?:-->|$)', '', text, flags=re.S)
    text = re.sub(r'<(script|style|template|pre|code)\b[^>]*>.*?(?:</\1\s*>|$)', '', text, flags=re.S | re.I)
    text = _remove_hidden(text)
    lines, fence, html_block = [], None, False
    block_start = re.compile(r' {0,3}(?:[#><|]|[-*+][ \t]|[0-9]{1,9}[.)][ \t])')
    raw_html = re.compile(r' {0,3}<[!?/A-Za-z]')
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            lines.append('')
            continue
        if not line.strip():
            html_block = False
        if html_block or raw_html.match(line):
            html_block = True   # keep the tag as a diagnostic boundary, suppress the block's contents
            lines.append(line if raw_html.match(line) else '')
            continue
        if marker:
            fence = marker[1]
            lines.append('')
            continue
        underline = re.fullmatch(r' {0,3}(=+|-+)[ \t]*', line)
        if underline and lines and lines[-1].strip() and not block_start.match(lines[-1]):
            start = len(lines) - 1
            while start and lines[start - 1].strip() and not block_start.match(lines[start - 1]):
                start -= 1
            if lines[start].startswith(('    ', '\t')):   # an indented code block cannot supply a heading
                lines.append(line)
                continue
            title = ' '.join(part.strip() for part in lines[start:])   # a Setext title may span several lines
            indent = lines[start][:len(lines[start]) - len(lines[start].lstrip(' '))]
            lines[start:] = [indent + ('# ' if underline[1][0] == '=' else '## ') + title]
        else:
            lines.append(line)
    heading = re.compile(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$')
    titles = {'approval', 'утверждение'}
    headings = {i: (len(m[1]), plain(m[2] or '').casefold(), line.startswith(' '))
                for i, line in enumerate(lines) if (m := heading.match(line))}
    history_title = re.compile(r'(history|changes|example|история|изменения|пример)\b')
    roots = [i for i, (level, _, _) in headings.items() if level == 1]
    start, end = (roots[0] if roots else -1), (roots[1] if len(roots) > 1 else len(lines))
    has_approval = any(title in titles for _, title, _ in headings.values())
    canonical = {i for i, (level, title, indented) in headings.items()
                 if level == 2 and title in titles and not indented and start < i < end}
    active, values, issues, seen_heading, indented_section = False, [], [], False, False
    html_in_scope = False
    for i, line in enumerate(lines):
        if raw_html.match(line):
            html_in_scope = html_in_scope or active or not values
            continue
        if i in headings:
            level, title, indented = headings[i]
            legacy_title = bool(title) and not has_approval and not seen_heading and level == 1 and not history_title.match(title)
            candidate = i in canonical or legacy_title
            indented_section = candidate and indented
            active, seen_heading = candidate and not indented_section, True
            continue
        if line.startswith(('    ', '\t')):   # indented code carries no approval
            continue
        value = plain(line)
        label = re.search(r'Approved by the author on|Утвержд[её]н автором|delegat|делегир', value, re.I)
        if not active:
            if indented_section and label and not canonical:
                issues.append(f'{line.strip()} (indented heading; write Approval and its field unindented)')
            continue
        if line.startswith(' '):   # do not silently discard a visible but unsupported indented field
            if label:
                issues.append(f'{line.strip()} (indented field; write it unindented under Approval)')
            continue
        if re.match(r'^[ \t]*(?:[-*+][ \t]+)?(?:Changes(?:, with dates)?|Изменения с датами)[ \t]*:', value, re.I):
            active = False
            continue
        m, d = APPROVAL.fullmatch(value), DELEGATED.fullmatch(value)
        # A code span around the label is an example, even though dates may use code spans.
        if m and '`' not in line.split(':', 1)[0] and not re.search(r'delegat|делегир', value, re.I):
            values.append(m[1])
        elif d and '`' not in line:   # a delegated approval names its decision; the product that keeps decisions decides it
            values.append(f'delegated:{d[1]}')
        elif label:
            issues.append(line.strip())
    issue = ('raw HTML before or in Approval; approval is read only from plain Markdown' if html_in_scope else
             'unsupported Approval heading; use unindented ## Approval or ## Утверждение in the first H1 profile section (or omit H1 headings)' if has_approval and not canonical else
             'multiple active approval fields; keep one current field' if len(values) > 1 else
             f'unsupported approval field: {issues[0]}' if issues else None)
    return ([] if html_in_scope else values), issue


def approval_values(markdown):
    return approval_fields(markdown)[0]


def unread_approval(markdown):
    """The first approval line that holds a number yet does not approve(): a spelling the tables lack, a bracket or a
    note. The author may have approved the profile, so the check quotes the line instead of passing it as a plain draft."""
    return next((value for value in approval_values(markdown)
                 if re.search(r'\d', value) and not approves(value) and not value.startswith('delegated:')), None)


def delegated_decision(markdown):
    """The decision a profile's one approval field names under delegation (Approved under delegation: DEC-NN), or None."""
    values, issue = approval_fields(markdown)
    return values[0].split(':', 1)[1] if not issue and len(values) == 1 and values[0].startswith('delegated:') else None


def delegated_approval(decision, folder, item=None):
    """'' when the product that keeps decisions says `decision` approves the profile in folder (item: the profile's
    file); else why not. Without such a product, configured through names.configure(approver=...), a delegated approval
    approves nothing."""
    if host.APPROVER is None:
        return 'a delegated approval needs the product that keeps its decision, and none is configured'
    return host.APPROVER(decision, folder, item)


def status(markdown, folder=None, item=None):
    """approved when an approval line gives one date (approves), or names a delegated decision the product that keeps decisions
    accepts for profile; default when the status line says so; draft otherwise."""
    values, issue = approval_fields(markdown)
    if issue:
        return 'draft'
    if len(values) == 1 and approves(values[0]):
        return 'approved'
    decision = delegated_decision(markdown)
    if decision and not delegated_approval(decision, folder, item):
        return 'approved'
    return 'default' if DEFAULT.search(markdown) else 'draft'


def classify(markdown, prose, measures, has_guard, lang, folder=None, item=None):
    """status(), except that a default whose prose or measures differ from the shipped ones (or a configured product's), or that carries a guard,
    has been edited: the author's work, kept like a draft."""
    state = status(markdown, folder, item)
    if state == 'default':
        shipped = [DEFAULTS / name for name in files_for(lang)[:2]]
        current = all(p.is_file() for p in shipped) and [prose, measures] == [p.read_bytes() for p in shipped]
        known = measures is not None and (hashlib.sha256(prose).hexdigest(), hashlib.sha256(measures).hexdigest()) in host.KNOWN_DEFAULTS
        if has_guard or not (current or known):
            return 'draft'
    return state


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_targets(targets, lang):
    """Target ranges with labels and minimum lengths, each a measure this checker can read in lang."""
    return (isinstance(targets, dict) and targets
            and set(targets) <= available_targets(lang)   # a target the checker cannot measure in this language enforces nothing
            and all(isinstance(t, dict) and isinstance(t.get('label'), str) and all(_number(t.get(k)) for k in ('low', 'high', 'min_words'))
                    and 0 <= t['low'] <= t['high'] and t['min_words'] > 0 and (t['high'] <= 1 or key not in UNIT_MEASURES)
                    for key, t in targets.items()))


def _valid_calibration(cal, lang):
    """A calibration the check can read: unavailable with a reason, or centers, positive scales and sorted held-out distances."""
    if not (isinstance(cal, dict) and type(cal.get('method')) is int and 1 <= cal['method'] <= CALIBRATION_METHOD):
        return False
    if cal.get('status') == 'unavailable':
        return isinstance(cal.get('reason'), str)
    centers, scales, held_out = cal.get('centers'), cal.get('scales'), cal.get('distances')
    return (cal.get('status') == 'available' and isinstance(centers, dict) and isinstance(scales, dict) and centers
            and set(centers) == set(scales) and set(centers) <= available_targets(lang)
            and all(_number(v) for v in centers.values()) and all(_number(v) and v > 0 for v in scales.values())
            and isinstance(held_out, list) and len(held_out) >= CALIBRATION_MIN_CHAPTERS
            and all(_number(v) and v >= 0 for v in held_out) and held_out == sorted(held_out)
            and isinstance(cal.get('quantiles'), dict) and set(cal['quantiles']) == {'p10', 'p50', 'p90', 'max'}
            and all(_number(v) and v >= 0 for v in cal['quantiles'].values()))


def _valid_registers(registers, lang):
    return (isinstance(registers, dict) and set(registers) <= set(REGISTERS)
            and all(isinstance(r, dict) and _valid_targets(r.get('targets'), lang) and 'function_word_similarity' not in r['targets']
                    and ('calibration' not in r or _valid_calibration(r['calibration'], lang))
                    for r in registers.values()))


def validate_profile(profile, lang, where):
    """Raise ValueError unless profile carries every field the check reads, with the right types."""
    targets = profile.get('targets') if isinstance(profile, dict) else None
    rates = profile.get('function_words') if isinstance(profile, dict) else None
    if not (isinstance(profile, dict) and isinstance(targets, dict) and isinstance(rates, dict)
            and profile.get('schema') in profile_schemas()
            and lang_code(profile.get('language'), '') == lang and isinstance(profile.get('sources', []), list)
            and profile.get('segmentation') in (None, 'partial')
            and isinstance(profile.get('scripts', []), list) and all(isinstance(s, str) and s in ('latin', 'cyrillic') for s in profile.get('scripts', []))
            and _valid_targets(targets, lang)
            and ('function_word_similarity' not in targets or rates)   # a fingerprint target needs a fingerprint
            and set(rates) <= set(FUNCTION_WORDS.get(lang, ()))   # in the language's function words, or the cosine means nothing
            and all(_number(v) and v >= 0 for v in rates.values())
            and (profile.get('copy_guard_sha256') is None or SHA256.fullmatch(str(profile['copy_guard_sha256'])))):
        raise ValueError(f'{where} is not a {lang} author profile: it needs the {PROFILE_SCHEMA} schema, language {lang}, target names measurable in {lang}, '
                         'target ranges with labels and minimum lengths, numeric function-word rates and a list of sources')
    if 'calibration' in profile and not _valid_calibration(profile['calibration'], lang):
        raise ValueError(f'{where} holds a calibration this {host.PRODUCT} cannot read (another release made it, or it was edited): rescan the sources')
    if 'registers' in profile and not _valid_registers(profile['registers'], lang):
        raise ValueError(f'{where} holds narration and dialogue ranges this {host.PRODUCT} cannot read: rescan the sources')
    method = profile.get('measure_method', 1)
    if type(method) is not int or not 1 <= method <= MEASURE_METHOD.get(lang, 1):   # a newer release's method: no meaning to compare
        raise ValueError(f'{where} records measure method {repr(method)[:20]}, which this {host.PRODUCT} does not know (it reads {lang} by '
                         f'method {MEASURE_METHOD.get(lang, 1)}): update {host.PRODUCT}, or rescan the sources with this one')


def validate_guard(guard, lang, where, built_from_books=False):
    """Raise ValueError unless guard was built by the algorithm the check uses: winnowed 8-word runs."""
    if not (isinstance(guard, dict) and guard.get('schema') in guard_schemas() and lang_code(guard.get('language'), '') == lang
            and guard.get('run_words') == SHINGLE and guard.get('window') == WINDOW and guard.get('catches_runs_of') == CAUGHT
            and isinstance(guard.get('hashes'), list) and all(isinstance(h, str) and HASH.fullmatch(h) for h in guard['hashes'])):
        raise ValueError(f'{where} is not a {lang} copy guard of the kind this tool checks ({" or ".join(guard_schemas())}, {SHINGLE}-word runs, '
                         f'window {WINDOW}); rebuild it with {host.command("scan")}')
    if built_from_books and not guard['hashes']:   # an empty guard for a profile built from books would clear every draft
        raise ValueError(f'{where} holds no hashes, though its profile was built from books; rebuild it with {host.command("scan")}')


def rescan():
    return (f'rescan the books with {host.command("scan")} into a new folder, then install that folder; keep the approved '
            'AUTHOR_PROFILE file and carry its described voice and approval over by hand')


def _read(path):
    data = path.read_bytes()
    return {'file': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': data}


def load(path, lang):
    """The profile for lang in a folder (or beside an author-profile.<lang>.json path), checked and with each file's
    revision. Raises ValueError for a missing prose profile, invalid files, or a guard not bound to these measures."""
    path = Path(path)
    folder = path.parent if path.is_file() else path
    named = re.fullmatch(r'author-profile\.([^.]+)\.json', path.name) if path.is_file() else None
    if not named and len(held(lang, folder)) > 1:   # which one governs would be a guess: an untouched en default could hide an approved eng
        raise ValueError(f"{folder} holds the {lang} profile under several names ({', '.join(held(lang, folder))}); keep the one "
                         'in use and move the others to history/, or name its author-profile file')
    names = family(named.group(1)) if named else files_for(lang, folder)   # a named measures file brings its own prose and guard
    prose_path, measures_path, guard_path = (folder / name for name in names)
    measures_path = path if path.is_file() else measures_path
    if not measures_path.is_file():
        raise ValueError(f'no {lang} profile in {folder}: need {prose_path.name} and {measures_path.name}')
    measures = _read(measures_path)
    try:
        profile = json.loads(measures['bytes'].decode('utf-8'))
    except ValueError as error:   # undecodable text or JSON that does not parse is no profile
        raise ValueError(f'{measures_path} cannot be read: {error}') from error
    validate_profile(profile, lang, measures_path)   # language included, as validate_guard checks the guard's
    if not prose_path.is_file():
        raise ValueError(f'{prose_path} is missing: the prose profile holds the described voice and its approval, so a '
                         'profile without it cannot be checked; install the profile again')
    prose = _read(prose_path)
    guard = _read(guard_path) if guard_path.is_file() else None
    try:
        markdown = prose['bytes'].decode('utf-8')
        guard_data = json.loads(guard['bytes'].decode('utf-8')) if guard else None
    except ValueError as error:
        raise ValueError(f'{folder}: a profile file cannot be read: {error}') from error
    bound = profile.get('copy_guard_sha256')
    if guard:
        validate_guard(guard_data, lang, guard_path, bool(profile.get('sources')))
        if bound is None:
            raise ValueError(f'{guard_path} is not bound to its profile ({measures_path.name} records no copy_guard_sha256), '
                             f'so it cannot be shown to belong to these books; {rescan()}')
        if bound != guard['sha256']:
            raise ValueError(f'{guard_path} is not the copy guard {measures_path.name} was built with; {rescan()}')
    elif bound is not None or profile.get('sources'):   # built from books: the guard must be there
        raise ValueError(f'{guard_path} is missing, though {measures_path.name} was built from books; install the profile '
                         f'again or rebuild it with {host.command("scan")}')
    state = classify(markdown, prose['bytes'], measures['bytes'], guard is not None, lang, folder, prose_path.name)
    decision = delegated_decision(markdown)   # a delegated approval is reported as delegated, never as the author's
    return {'language': lang, 'prose': prose, 'measures': measures, 'guard': guard, 'profile': profile, 'guard_data': guard_data,
            'status': state, 'unread_approval': unread_approval(markdown) if state == 'draft' else None,
            'approval_issue': approval_fields(markdown)[1] if state == 'draft' else None,
            'delegated': decision if decision and state == 'approved' else None,
            'delegation_issue': f'its approval names {decision}, which approves nothing here: {delegated_approval(decision, folder, prose_path.name)}'
            if decision and state == 'draft' else None}


def revision(bundle):
    """The profile's revision for a report: each file's path and SHA-256, the guard stated as absent when there is none."""
    entry = lambda f: {'file': f['file'], 'sha256': f['sha256']}
    return {'prose': entry(bundle['prose']), 'measures': entry(bundle['measures']),
            'guard': entry(bundle['guard']) if bundle['guard'] else 'absent'}

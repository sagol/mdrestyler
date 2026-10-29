"""Measures of a narrative voice, shared by the scan and the check. Standard library only.

Text comes in as chapters, each a list of paragraphs. A paragraph is (text, emphasized words); a scene break is the
paragraph SCENE_BREAK. The measures are rough on purpose: they locate drift for a reader to confirm, and they are
never a verdict on prose by themselves."""
import hashlib
import html
import io
import html.parser
import math
import posixpath
import re
import statistics
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import unquote

from .container import DRMError, LimitError, FONT_OBFUSCATION, check_epub_drm, decode_markup as _decode, external, local_name as _local, media_type, package_path, parse_xml as _xml, resolve
from . import styles as S

SCENE_BREAK = ('<scene-break>', 0)
HEADING = '<heading>'   # (HEADING, title): where a chapter starts inside one EPUB file
ANCHOR = '<anchor>'   # (ANCHOR, kind): a landmark's #fragment, marking the section that follows as skip or apparatus
FRONT_MATTER_MAX = 600
FRONT_TITLES = {'copyright', 'copyright page', 'isbn', 'contents', 'table of contents', 'colophon', 'imprint', 'title page',
                'содержание', 'оглавление', 'выходные данные'}   # a short section under one of these headings is front matter   # words: only a section this short can be front matter dropped for a copyright or ISBN notice
BLURB_TITLES = {'annotation', 'аннотация'}   # untyped publisher copy: guarded, never a chapter-voice sample
WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
CYRILLIC = re.compile(r'[Ѐ-ӿ]')
LATIN = re.compile(r'[A-Za-zÀ-ɏ]')
BREAK_LINE = re.compile(r'^\s*(?:[*#~◊•·⁂—–-]\s*){1,5}$')   # "* * *", "***", "◊", "#", "—"

# Sentence ends: terminal punctuation, then closing quotes or brackets, then space before something that can open one.
SENTENCE_END = re.compile(r'([.!?…]+["\'»”’)\]]*)\s+(?=["\'«“‘(\[—–-]?\s*[^\W_])')
DOUBLE_QUOTED = re.compile(r'“([^”]*)”|"([^"]*)"')
SINGLE_QUOTED = re.compile(r"‘((?:[^’]|’(?=\w))*)’(?!\w)|(?<!\w)'((?:[^']|'(?=\w))*)'(?!\w)")   # an apostrophe inside does not close
TIDY = {**{ord(c): None for c in '\u00ad\u200b\u200c\u200d\u2060\ufeff\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'},
        ord('\u2010'): '-', ord('\u2011'): '-', ord('\u02bc'): '’', ord('ѐ'): 'е', ord('ѝ'): 'и', ord('Ѐ'): 'Е', ord('Ѝ'): 'И'}
STRESSED_LATIN = {'á': 'а', 'à': 'а', 'é': 'е', 'è': 'е', 'ó': 'о', 'ò': 'о', 'ý': 'у', 'í': 'и', 'ì': 'и', 'ú': 'у', 'ù': 'у'}
APOSTROPHE_LIKE = re.compile(r"(?<=[^\W\d_])[‘´′`](?=[^\W\d_])")   # it‘s, don´t, don′t read as it’s, don’t
COMBINING = re.compile('[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]')   # stress and other marks left after NFKC
CYRILLIC_LANGS = {'ru', 'uk', 'be', 'bg', 'sr', 'mk', 'kk', 'ky', 'tg', 'mn'}
ISO_639_2 = dict(pair.split(':') for pair in '''
aar:aa abk:ab afr:af aka:ak alb:sq amh:am ara:ar arg:an arm:hy asm:as ava:av ave:ae aym:ay aze:az bak:ba bam:bm baq:eu
bel:be ben:bn bis:bi bod:bo bos:bs bre:br bul:bg bur:my cat:ca ces:cs cha:ch che:ce chi:zh chu:cu chv:cv cor:kw cos:co
cre:cr cym:cy cze:cs dan:da deu:de div:dv dut:nl dzo:dz ell:el eng:en epo:eo est:et eus:eu ewe:ee fao:fo fas:fa fij:fj
fin:fi fra:fr fre:fr fry:fy ful:ff geo:ka ger:de gla:gd gle:ga glg:gl glv:gv gre:el grn:gn guj:gu hat:ht hau:ha heb:he
her:hz hin:hi hmo:ho hrv:hr hun:hu hye:hy ibo:ig ice:is ido:io iii:ii iku:iu ile:ie ina:ia ind:id ipk:ik isl:is ita:it
jav:jv jpn:ja kal:kl kan:kn kas:ks kat:ka kau:kr kaz:kk khm:km kik:ki kin:rw kir:ky kom:kv kon:kg kor:ko kua:kj kur:ku
lao:lo lat:la lav:lv lim:li lin:ln lit:lt ltz:lb lub:lu lug:lg mac:mk mah:mh mal:ml mao:mi mar:mr may:ms mkd:mk mlg:mg
mlt:mt mon:mn mri:mi msa:ms mya:my nau:na nav:nv nbl:nr nde:nd ndo:ng nep:ne nld:nl nno:nn nob:nb nor:no nya:ny oci:oc
oji:oj ori:or orm:om oss:os pan:pa per:fa pli:pi pol:pl por:pt pus:ps que:qu roh:rm ron:ro rum:ro run:rn rus:ru sag:sg
san:sa sin:si slk:sk slo:sk slv:sl sme:se smo:sm sna:sn snd:sd som:so sot:st spa:es sqi:sq srd:sc srp:sr ssw:ss sun:su
swa:sw swe:sv tah:ty tam:ta tat:tt tel:te tgk:tg tgl:tl tha:th tib:bo tir:ti ton:to tsn:tn tso:ts tuk:tk tur:tr twi:tw
uig:ug ukr:uk urd:ur uzb:uz ven:ve vie:vi vol:vo wel:cy wln:wa wol:wo xho:xh yid:yi yor:yo zha:za zho:zh zul:zu'''.split())   # every ISO 639-2 code with a current two-letter equivalent (Debian iso-codes)
TWO_LETTER = set(ISO_639_2.values()) | {'sh'}   # the current ISO 639-1 codes, and sh, which the IANA registry keeps for Serbo-Croatian
ISO_639_2.update({'iw': 'he', 'in': 'id', 'ji': 'yi', 'jw': 'jv', 'mo': 'ro', 'bh': 'bih'})   # withdrawn two-letter codes, read as their successors
LANGUAGE_NAMES = {'english': 'en', 'russian': 'ru', 'русский': 'ru'}   # only languages with shipped defaults; other names are refused
ABBREVIATIONS = {
    'en': {'mr', 'mrs', 'ms', 'dr', 'st', 'jr', 'sr', 'prof', 'mt', 'no', 'vs', 'etc', 'e.g', 'i.e', 'capt', 'col', 'gen', 'lt', 'sgt', 'rev', 'hon'},
    'ru': {'т', 'е', 'д', 'п', 'др', 'г', 'гг', 'в', 'вв', 'ул', 'им', 'ок', 'см', 'стр', 'тыс', 'млн', 'руб', 'коп', 'проф', 'акад', 'св', 'пр'},
}
FUNCTION_WORDS = {
    'en': ('the and to of a in that it was he she i you his her for on with as at had but not be they is this from by all '
           'so we there were or an have one what if would no out up about into then them when could him me my been more now only like just over').split(),
    'ru': ('и в не на я он что с она а как это по но его к у все так ее же мне из за был было бы только вы от когда уже еще о то нет да '
           'ты они мы была для до вот если или ни тоже даже чтобы потом себя там тут может где ну').split(),
}
PRONOUN_OPENERS = {'en': {'i', 'he', 'she', 'it', 'they', 'we', 'you'}, 'ru': {'я', 'он', 'она', 'оно', 'они', 'мы', 'ты', 'вы'}}
CONJUNCTION_OPENERS = {'en': {'and', 'but', 'or', 'so', 'yet'}, 'ru': {'и', 'но', 'а', 'да', 'или'}}
ARTICLE_OPENERS = {'en': {'the', 'a', 'an'}, 'ru': set()}
FIRST_PERSON = {'en': {'i', 'me', 'my', 'mine', 'myself', 'we', 'us', 'our', 'ours', 'ourselves'},
                'ru': {'я', 'меня', 'мне', 'мной', 'мною', 'мой', 'моя', 'мое', 'мои', 'моего', 'моей', 'моих', 'моим', 'моими', 'моему',
                       'мы', 'нас', 'нам', 'нами', 'наш', 'наша', 'наше', 'наши', 'нашего', 'нашей', 'наших', 'нашим', 'нашими', 'нашему'}}
THIRD_PERSON = {'en': {'he', 'she', 'him', 'her', 'his', 'hers', 'himself', 'herself', 'they', 'them', 'their', 'theirs', 'themselves', 'themself', 'it', 'its', 'itself'},
                'ru': {'он', 'она', 'его', 'ее', 'ему', 'ей', 'им', 'ним', 'нее', 'нему', 'ней', 'нем', 'они', 'их', 'ими', 'них', 'ними', 'оно', 'него', 'ею', 'нею'}}
SPEECH_VERBS = {
    'en': {'said', 'says', 'asked', 'asks', 'replied', 'answered', 'whispered', 'shouted', 'muttered', 'cried', 'called', 'added',
           'murmured', 'snapped', 'exclaimed', 'demanded', 'yelled', 'screamed', 'hissed', 'insisted', 'continued', 'began', 'told',
           'laughed', 'sighed', 'breathed', 'growled', 'protested', 'agreed', 'admitted', 'suggested', 'warned', 'repeated'},
    'ru': {'сказал', 'сказала', 'сказали', 'спросил', 'спросила', 'ответил', 'ответила', 'прошептал', 'прошептала', 'крикнул', 'крикнула',
           'закричал', 'закричала', 'пробормотал', 'пробормотала', 'добавил', 'добавила', 'произнес', 'произнесла', 'воскликнул', 'воскликнула',
           'заметил', 'заметила', 'возразил', 'возразила', 'продолжил', 'продолжила', 'усмехнулся', 'усмехнулась', 'вздохнул', 'вздохнула',
           'попросил', 'попросила', 'повторил', 'повторила', 'согласился', 'согласилась', 'буркнул', 'буркнула', 'сказал', 'говорит', 'говорил', 'говорила'},
}
# Russian speech verbs: the past tense of each, in every gender and number, and the common present forms. A curated list,
# so a rarer verb of speech is found only by its past-tense form near the speech (TAG_FORM).
RU_SAYING = ('сказал спросил ответил говорил переспросил отозвался поинтересовался прошептал шепнул крикнул закричал вскрикнул '
             'выкрикнул прокричал пробормотал забормотал добавил воскликнул заметил возразил продолжил продолжал попросил повторил '
             'согласился буркнул пробурчал проворчал проговорил промолвил молвил объяснил пояснил сообщил признался позвал окликнул '
             'уточнил напомнил предложил подтвердил отрезал перебил прервал оборвал выдавил выпалил заявил рявкнул протянул подхватил '
             'вставил вмешался откликнулся поправил обратился поздоровался попрощался приказал скомандовал велел потребовал взмолился '
             'пожаловался огрызнулся парировал отпарировал съязвил пошутил усмехнулся вздохнул хмыкнул доложил объявил распорядился '
             'посоветовал предупредил пообещал рассказал пролепетал прошипел прорычал процедил простонал спохватился настаивал '
             'поблагодарил извинился рассмеялся засмеялся начал').split()
RU_SAYING_NOW = ('говорит говорят спрашивает спрашивают переспрашивает переспрашивают отвечает отвечают шепчет шепчут кричит кричат '
                 'бормочет бормочут произносит произносят добавляет добавляют восклицает восклицают замечает замечают возражает возражают '
                 'продолжает продолжают просит просят повторяет повторяют соглашается соглашаются бурчит бурчат ворчит ворчат объясняет '
                 'объясняют поясняет поясняют сообщает сообщают признается признаются зовет зовут окликает окликают уточняет уточняют '
                 'напоминает напоминают предлагает предлагают подтверждает подтверждают перебивает перебивают прерывает прерывают '
                 'заявляет заявляют интересуется интересуются отзывается отзываются обращается обращаются усмехается усмехаются '
                 'вздыхает вздыхают командует командуют требует требуют рассказывает рассказывают шутит шутят смеется смеются').split()


def _past_forms(verb):
    """A Russian past-tense verb in every gender and number: сказал, сказала, сказало, сказали."""
    stem, end = (verb[:-3], 'ся') if verb.endswith('лся') else (verb[:-1], '')
    return {stem + suffix + ('сь' if end and suffix != 'л' else end) for suffix in ('л', 'ла', 'ло', 'ли')}


# First-person present tags (говорю я) and present-tense action verbs that stand in a tag's place (кивает он): read as a
# tag's verb near its speech only, a first-person form never right after я or мы («— я спрашиваю, чтобы сменить тему» is speech).
RU_SAYING_I = ('говорю говорим спрашиваю спрашиваем отвечаю отвечаем переспрашиваю переспрашиваем шепчу шепчем кричу кричим '
               'бормочу бормочем произношу произносим добавляю добавляем восклицаю восклицаем замечаю замечаем возражаю возражаем '
               'продолжаю продолжаем прошу просим повторяю повторяем соглашаюсь соглашаемся объясняю объясняем сообщаю сообщаем '
               'признаюсь признаемся зову зовем окликаю окликаем уточняю уточняем напоминаю напоминаем предлагаю предлагаем '
               'подтверждаю подтверждаем перебиваю перебиваем заявляю заявляем интересуюсь интересуемся отзываюсь отзываемся '
               'усмехаюсь усмехаемся вздыхаю вздыхаем').split()
RU_ACTION_NOW = ('кивает кивают киваю киваем улыбается улыбаются улыбаюсь улыбаемся пожимает пожимают пожимаю пожимаем качает '
                 'качают качаю качаем хмурится хмурятся хмурюсь хмуримся морщится морщатся морщусь морщимся машет машут машу машем '
                 'оборачивается оборачиваются оборачиваюсь оборачиваемся смеюсь смеемся').split()
SPEECH_VERBS['ru'] = ({form for verb in RU_SAYING for form in _past_forms(verb)} | set(RU_SAYING_NOW)
                      | {'произнес', 'произнесла', 'произнесло', 'произнесли', 'изрек', 'изрекла', 'изрекло', 'изрекли'})
NEAR_VERBS = {'ru': frozenset(RU_SAYING_I) | frozenset(RU_ACTION_NOW)}
PLAIN_TAGS = {'en': {'said', 'says', 'asked', 'asks'},
              'ru': {form for verb in ('сказал', 'спросил', 'ответил', 'говорил') for form in _past_forms(verb)}
                    | {'говорит', 'говорят', 'спрашивает', 'спрашивают', 'отвечает', 'отвечают',
                       'говорю', 'говорим', 'спрашиваю', 'спрашиваем', 'отвечаю', 'отвечаем'}}
TAG_FORM = {'ru': re.compile(r'(?:л|ла|ли|лся|лась|лось|лись)$')}   # past tense; neuter -ло is left out, as adverbs end that way
NOT_TAG_VERBS = {'ru': frozenset('если или либо мысли земли дела тела сила'.split())}   # frequent words that end like a past tense
PREPOSITIONS = {'ru': frozenset('в во на с со к ко у о об обо от ото до из изо за по под подо над надо при про для без через перед '
                                'передо между около возле вокруг мимо после среди кроме вдоль сквозь ради против внутри вне из-за '
                                'из-под'.split())}
MANNER_WORDS = {'ru': frozenset('вдруг снова опять вновь вполголоса шепотом'.split())}   # manner words that are not in -о or -е
SUBORDINATORS = {'ru': frozenset('что чтобы потому поскольку если когда как ибо раз хотя пока будто словно'.split())}
TIME_WORDS = {'ru': frozenset('давно уже еще потом тогда теперь сейчас всегда никогда иногда часто долго вчера сегодня '
                              'раньше позже'.split())}   # between a name and a speech verb, these tell narration from a tag
TAG_WINDOW = 6   # a present or past-tense form is a tag's verb only this near its speech; a listed speech verb may stand further
MEASURE_METHOD = {'ru': 2}   # how a language's measures are read; a profile from another method is not compared on what changed
METHOD_CHANGES = {('ru', 2): frozenset({   # TI-03: Russian speech tags, dash-led segments and the sentences tags continue
    'plain_tag_share', 'dialogue_word_share', 'first_person_per_1000', 'third_person_per_1000', 'opener_pronoun_share',
    'opener_conjunction_share', 'sentence_len_median', 'sentence_len_mean', 'sentence_len_p90', 'short_sentence_share',
    'long_sentence_share', 'sentence_len_cv', 'rhythm_shift', 'one_sentence_paragraph_share'})}
SIMILE = {'en': re.compile(r'\b(?:like (?:a|an|the|some)|as if|as though)\b', re.I),
          'ru': re.compile(r'(?<![\w-])(?:как будто|словно|будто|точно бы|как бы)(?![\w-])', re.I)}
PAST_EN = {'was', 'were', 'had', 'did', 'said', 'went', 'came', 'saw', 'took', 'got', 'made', 'knew', 'thought', 'felt', 'told', 'found',
           'gave', 'left', 'began', 'stood', 'sat', 'ran', 'held', 'brought', 'kept', 'heard', 'turned', 'looked', 'seemed', 'could', 'would'}
PRESENT_EN = {'is', 'are', 'am', 'has', 'does', 'says', 'goes', 'comes', 'sees', 'takes', 'gets', 'makes', 'knows', 'thinks', 'feels',
              'tells', 'finds', 'gives', 'leaves', 'begins', 'stands', 'sits', 'runs', 'holds', 'can', 'will'}
NOT_ADVERBS = {'only', 'family', 'early', 'likely', 'ugly', 'holy', 'reply', 'supply', 'apply', 'fly', 'july', 'italy', 'lily', 'belly',
               'jelly', 'silly', 'daily', 'friendly', 'lonely', 'lovely', 'elderly', 'curly', 'hilly', 'bully', 'rally', 'ally', 'tally'}
DASHES = '—–'
SKIP_TYPES = {'toc', 'copyright-page', 'titlepage', 'title-page', 'bibliography', 'index', 'colophon', 'cover', 'loi', 'lot',
              'other-credits', 'imprint'}   # not prose: left out entirely
APPARATUS_TYPES = {'dedication', 'acknowledgments', 'acknowledgements', 'appendix', 'glossary', 'endnotes', 'footnotes', 'notes', 'rearnotes',
                   'epigraph', 'preface', 'foreword', 'afterword'}   # the author's text, but not the voice of the chapters: guarded, not measured
NOTE_TYPE = re.compile(r'\b(?:foot|end|rear)?notes?\b')
NOTE_REF = re.compile(r'\bnoteref\b')   # a note's marker in the text: skipped, not kept
FRONT_MARKERS = re.compile(r'all rights reserved|isbn(?:-1[03])?[\s:]*[\dx](?:[\s-]?[\dx]){9,12}|copyright ©|© \d{4}|copyright\s+(?:\(c\)\s*)?\d{4}|все права защищены|project gutenberg|this ebook is for the use of anyone', re.I)
BOOK_START = re.compile(r'\*{3}\s*start of (?:the|this) project gutenberg', re.I)   # distributors' wrappers around a book's text
BOOK_END = re.compile(r'\*{3}\s*end of (?:the|this) project gutenberg', re.I)
SHORT_SECTION = 150   # words: a shorter section feeds the copy guard but not the measures
PAGE_MARKS = {'pagenum', 'page-number', 'pagebreak'}   # class tokens of a page marker, matched whole
ROMAN = r'(?=[mdclxvi])m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})'   # a well-formed Roman numeral
PAGE_WORDS = ('page pg pp p seite s página pagina pág pag blz strona str strana stránka sida side sivu oldal o sayfa '
              'стр страница стор сторінка с σελίδα σελ صفحة صفحه ص עמוד עמ׳ עמ पृष्ठ पृ পৃষ্ঠা หน้า')   # what a page label says before its number, in the languages of most EPUBs
PAGE_LABEL = re.compile(r'[\[(]?\s*(?:(?:(?P<word>' + '|'.join(PAGE_WORDS.split()) + r')(?:\.\s*|\s+))?(?:\d{1,5}|' + ROMAN + r')'   # \d: any decimal digits, ١٢ or १२ too
                        r'|(?P<cjk>第?\s*(?:\d{1,5}|[〇零一二三四五六七八九十百千两]{1,8})\s*(?:ページ|頁|页|쪽|페이지)))\s*[\])]?', re.I)   # Page 12, Seite 12, [Pg 12], xii; never Chapter 12
def page_label(text, marker_only):
    """Whether an element's whole text is a page label; with a layout class beside the marker class, only one that names
    the page (Page 12, 12ページ) counts, so (I) or 12 stays as a chapter number."""
    label = PAGE_LABEL.fullmatch(text.strip())
    return bool(label and (marker_only or label['word'] or label['cjk']))


VOID_TAGS = {'br', 'hr', 'img', 'wbr', 'meta', 'link', 'input', 'col', 'area', 'base', 'source', 'track', 'embed', 'param', 'keygen'}
NEVER_SHOWN = {'datalist', 'noembed', 'noframes'}   # drawn by no reader, as a closed dialog; a template is skipped outright


def never_shown(tag, attrs, displays=(), ancestors=None):
    """Whether a reader draws nothing of the element, as a scan judges it (styles.Styler.scan_hides): the winning
    display and visibility among the stylesheets' rules that can reach it and its own style; hidden="until-found" stays
    hidden whatever display it is given. displays: the document's styler (sheet_styler), or (selector, display[,
    important]) rules; ancestors: (tag, attrs) pairs, nearest first."""
    if 'hidden' in attrs and (attrs['hidden'] or '').strip().lower() == 'until-found':
        return True
    if isinstance(displays, S.Styler):
        styler = displays
    else:
        css = '\n'.join(f'{selector} {{ display: {value}' + (' !important' if rest and rest[0] else '') + ' }'
                         for selector, value, *rest in displays)
        styler = S.Styler(S.parse_stylesheet(css)[0], css) if css else EMPTY_STYLER
    element = ET.Element(tag, {k: v or '' for k, v in attrs.items()})
    above = None if ancestors is None else [ET.Element(t, {k: v or '' for k, v in a.items()}) for t, a in ancestors]
    return styler.scan_hides(element, above)   # a scan asks no decision: every rule that can reach it counts


EMPTY_STYLER = S.Styler([])


XHTML_NS = 'http://www.w3.org/1999/xhtml'


EMPHASIS_PROPERTIES = frozenset({'font-style', 'font-weight', 'font', '*'})


def text_style(displays, tag, attrs, parent):
    """(flags, emphasis it cannot apply) of an element's text as the import computes them (styles.Styler.effective)
    below its parent's, the body's below the defaults, where the import starts: the second, the element's emphasis
    declarations beyond the subset (EMPHASIS_PROPERTIES, the font shorthand included), which the import lists for the
    author."""
    styler = displays if isinstance(displays, S.Styler) else EMPTY_STYLER
    element = ET.Element(tag, {k: v or '' for k, v in attrs.items()})
    flags, problems = styler.effective(element, S.DEFAULT if tag == 'body' else parent)
    return flags, {p for p in problems if isinstance(p, str) and p.split(':', 1)[0].strip().lower() in EMPHASIS_PROPERTIES}


SVG_NS, MATHML_NS = 'http://www.w3.org/2000/svg', 'http://www.w3.org/1998/Math/MathML'
ATTRIBUTE_PREFIXES = {'http://www.idpf.org/2007/ops': 'epub', 'http://www.w3.org/XML/1998/namespace': 'xml',
                      'http://www.w3.org/1999/xlink': 'xlink'}


def feed_tree(handler, root):
    """Drive an html.parser handler from a parsed XML tree, so a well-formed document is read with the names its XML
    reader gives, the import's: an element of the XHTML, SVG or MathML namespace, or of none, by its local name as
    html.parser gives names, any other by its expanded name, which no HTML name matches; an epub:, xml: or xlink:
    attribute by that prefix, whichever prefix the document bound."""
    def name(key, attribute=False):
        if not key.startswith('{'):
            return key if attribute else key.lower()
        ns, local = key[1:].split('}', 1)
        if attribute:
            return f'{ATTRIBUTE_PREFIXES[ns]}:{local}' if ns in ATTRIBUTE_PREFIXES else key
        return local.lower() if ns in (XHTML_NS, SVG_NS, MATHML_NS) else key
    todo = [(root, True)]   # in document order, without recursion however deep the tree
    while todo:
        element, opening = todo.pop()
        tag = name(element.tag)
        if opening:
            handler.handle_starttag(tag, [(name(k, True), v) for k, v in element.attrib.items()])
            if element.text:
                handler.handle_data(element.text)
            todo.append((element, False))
            todo.extend((child, True) for child in reversed(element))
        else:
            handler.handle_endtag(tag)
            if element is not root and element.tail:
                handler.handle_data(element.tail)


def shown_here(tag, attrs, displays=(), ancestors=None, inherited=True):
    """Whether an element's own text shows by visibility, as a scan judges it (styles.Styler.scan_visible): the
    winning visibility of the rules that reach it and its own style, or what its parent passes down."""
    styler = displays if isinstance(displays, S.Styler) else EMPTY_STYLER
    element = ET.Element(tag, {k: v or '' for k, v in attrs.items()})
    above = None if ancestors is None else [ET.Element(t, {k: v or '' for k, v in a.items()}) for t, a in ancestors]
    return styler.scan_visible(element, above, inherited)


def xml_text(raw):
    """Character data as an XML parser gives it, for a style element's text that html.parser leaves raw: comments and
    processing instructions dropped, CDATA sections kept as written, and outside them each character reference and the
    five entities XML defines expanded; a reference XML does not define is left as it stands."""
    def expand(s):
        def ref(m):
            name = m.group(1)
            if name.startswith('#'):
                n = int(name[2:], 16) if name[1] == 'x' else int(name[1:])
                return chr(n) if 0 < n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else m.group(0)
            return {'lt': '<', 'gt': '>', 'amp': '&', 'quot': '"', 'apos': "'"}.get(name, m.group(0))
        return re.sub(r'&(#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][\w.-]*);', ref, s)
    out, i = [], 0
    for m in re.finditer(r'<!\[CDATA\[(.*?)\]\]>|<!--.*?-->|<\?.*?\?>', raw, re.S):
        out.append(expand(raw[i:m.start()]))
        out.append(m.group(1) or '')
        i = m.end()
    return ''.join(out) + expand(raw[i:])


class _XhtmlTags:
    """html.parser's tag names with a prefix bound to the XHTML namespace taken off, so <h:p> is a p and <h:style> a
    style, as an XML reader takes them: each binding read from the parsed attributes (references expanded, as XML
    expands them) and in force where XML puts it, on its element and inside it."""

    def scopes(self):
        if not hasattr(self, '_scopes'):
            self._scopes = [({}, None)]   # (prefix bindings, local tag) of each open element
        return self._scopes

    def open_tag(self, tag, attrs):
        scopes = self.scopes()
        bindings = {**scopes[-1][0], **{k[6:].lower(): v for k, v in attrs if k.lower().startswith('xmlns:') and v is not None}}
        prefix, _, name = tag.partition(':')
        local = name if name and bindings.get(prefix) == XHTML_NS else tag
        if local not in VOID_TAGS:
            scopes.append((bindings, local))
        return local

    def close_tag(self, tag):
        scopes = self.scopes()
        prefix, _, name = tag.partition(':')
        local = name if name and scopes[-1][0].get(prefix) == XHTML_NS else tag
        for i in range(len(scopes) - 1, 0, -1):   # the open element it closes, as a lenient reader pairs them
            if scopes[i][1] == local:
                del scopes[i:]
                break
        return local


class _SheetNodes(_XhtmlTags, html.parser.HTMLParser):
    """The link and style elements of a document, in document order, as S.stylesheets takes them: comments are no
    markup, and a style element's text is read whole, as an XML reader reads it (xml_text)."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.nodes, self.style = [], None

    def handle_starttag(self, tag, attrs):
        tag = self.open_tag(tag, attrs)
        a = {k.lower(): v or '' for k, v in attrs}
        if tag == 'link':
            self.nodes.append(('link', a.get('href', ''), a.get('media'), a.get('rel', ''), a.get('type')))
        elif tag == 'style':
            self.style = (a.get('media'), a.get('type'), [])

    def handle_data(self, data):
        if self.style is not None:
            self.style[2].append(data)

    def handle_endtag(self, tag):
        tag = self.close_tag(tag)
        if tag == 'style' and self.style is not None:
            text = xml_text(''.join(self.style[2]))
            self.nodes.append(('style', text, self.style[0], self.style[1]))
            self.style = None


def sheet_styler(text, href, read, names, root=None):
    """The styler of a document's stylesheets, collected as the import collects them (S.stylesheets): those its prolog's
    xml-stylesheet instructions name, then its links and <style> elements in document order, links resolved as the
    import resolves them. root: the document as an XML reader parsed it; None for markup no XML parser takes."""
    remote = []

    def fetch(link):
        target = resolve(posixpath.dirname(href), link)   # no query or fragment, decoded; an outside sheet is never fetched
        if external(link):
            remote.append(link)   # a reader may load it, the scan never does: what it does to the text is unsettled
        return _decode(read(target)) if target and target in names else None

    if root is not None:   # the document as an XML reader parses it, the import's own collection
        nodes = S.style_nodes(root)
    else:   # markup no XML parser takes, read leniently instead
        collector = _SheetNodes()   # parsed markup, so a stylesheet inside a comment is no stylesheet
        collector.feed(text)
        collector.close()
        nodes = collector.nodes
    css = S.stylesheets(S.xml_stylesheets(text), nodes, fetch)
    rules, outside = S.parse_stylesheet(css)
    styler = S.Styler(rules, css)
    styler.unresolved |= {f'stylesheet the scan does not fetch: {link}' for link in remote}
    # rules beyond the subset that set emphasis on an element's text on a reader's screen (not print, not a ::before box):
    # the scan counts emphasis as the import does, so it cannot count these, which the import lists for the author; a sheet
    # it does not fetch may hold such rules too
    styler.emphasis_unresolved = ({str(o) for o in outside if not getattr(o, 'never', False) and not getattr(o, 'boxes', False)
                                   and set(getattr(o, 'properties', ())) & EMPHASIS_PROPERTIES}
                                  | {f'stylesheet the scan does not fetch: {link}' for link in remote})
    return styler

HTML_ELEMENTS = set('''a abbr acronym address area article aside audio b base bdi bdo big blink blockquote body br button canvas caption center
cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure font footer form frame frameset h1
h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark marquee menu meta meter nav nobr noframes
noscript object ol optgroup option output p param picture pre progress q rp rt ruby s samp search section select slot small source span strike
strong sub summary sup table tbody td textarea tfoot th thead time tr track tt u ul var video wbr'''.split())
BLOCK_ELEMENTS = set('''address article aside blockquote body br caption dd details dialog div dl dt fieldset figcaption figure footer form h1 h2
h3 h4 h5 h6 header hgroup hr html legend li main menu nav ol p pre search section summary table tbody td tfoot th thead tr ul'''.split())
HTML_TAG = re.compile(r'</?([A-Za-z][A-Za-z0-9-]*)(?:\s(?:[^<>"\']|"[^"]*"|\'[^\']*\')*)?/?>')   # a quoted > does not end the tag
ONLY_EVERY = ('\ue010', '\ue011')   # around what only the guard's every-word reading holds (visible_text's mark)


# What one scan may read. Measured on public-domain EPUBs: a novel holds 0.1 to 0.6 MiB of text entries and 50,000 to
# 85,000 words; scanning one peaks near 50 MB of memory, six books (300,000 words) near 72 MB. The defaults leave room
# for an omnibus while keeping a hostile or broken archive well short of exhausting memory.
MAX_INPUT_MB = 256       # one EPUB file, read once to hash and unpack it
MAX_MEMBERS = 10_000     # entries in one archive
MAX_ENTRY_MB = 16        # one text entry, expanded
MAX_WORDS = 4_000_000    # words across one scan; tokens and copy-guard runs grow with them
TEXT_MB = 64             # expanded text read across one scan: the one budget a user sets (the scan's --max-expanded-mb)


class Budget:
    """Expanded text bytes and words left for one scan, counted across every book in it."""

    def __init__(self, text_mb=TEXT_MB):
        self.text_mb, self.bytes_left, self.words_left = text_mb, int(text_mb * 2**20), MAX_WORDS

    def take_bytes(self, count, where):
        self.bytes_left -= count
        if self.bytes_left < 0:
            raise LimitError(f'{where}: the scan would read more than {self.text_mb} MiB of expanded text across its books; '
                             'pass --max-expanded-mb to allow more')

    def take_words(self, count, where):
        self.words_left -= count
        if self.words_left < 0:
            raise LimitError(f'{where}: the scan would hold more than {MAX_WORDS:,} words across its books, the fixed ceiling')


def tidy(text):
    """Text as a reader sees it, whatever the typesetting: compatibility forms folded (NFKC: ligatures, no-break spaces,
    decomposed letters), soft hyphens and zero-width characters removed, typographic hyphens and the modifier apostrophe
    made plain. Book text and drafts both pass through it before they are measured or hashed."""
    text = APOSTROPHE_LIKE.sub('’', text)   # before NFKC, which turns ´ into a space and an accent
    text = COMBINING.sub('', unicodedata.normalize('NFKC', text)).translate(TIDY)
    return re.sub(r'(?<=[а-яА-ЯёЁ])[áàéèóòýíìúù]|[áàéèóòýíìúù](?=[а-яА-ЯёЁ])', lambda m: STRESSED_LATIN[m.group(0)], text)   # a Latin stressed vowel in a Russian word


def tag_script(tag, default_lang='en'):
    """cyrillic or latin: a tag's script subtag (sr-Latn, sr-Cyrl) when it has one, else its language's usual script."""
    parts = re.split(r'[-_]', (tag or '').lower())
    if 'latn' in parts:
        return 'latin'
    if 'cyrl' in parts:
        return 'cyrillic'
    return 'cyrillic' if lang_code(tag, default_lang) in CYRILLIC_LANGS else 'latin'


def plain_title(title):
    return re.sub(r'[^\w ]+', '', (title or '').lower()).strip()


def lang_code(tag, default='en'):
    """A language tag as the code profiles use, two letters wherever the language has them (ISO_639_2): en-GB, en_US and
    eng all read as en, a language with no two-letter code keeps its three, and the names of
    the languages with shipped defaults (LANGUAGE_NAMES). An empty, undetermined or private-use tag gives default;
    anything else that is no tag, such as "German" or a number from a malformed file, gives None, which a caller that
    needs the language refuses."""
    if tag is not None and not isinstance(tag, str):
        return None
    tag = (tag or '').strip().lower()
    code = LANGUAGE_NAMES.get(tag) or re.split(r'[-_]', tag)[0]
    if code in {'', 'und', 'mul', 'zxx', 'mis', 'x', 'i'}:   # undetermined, multiple, none, private use: no language
        return default
    if not re.fullmatch(r'[a-z]{2,3}', code) or re.fullmatch(r'q[a-t][a-z]', code):
        return None   # not a code, or reserved for local use (qaa-qtz)
    code = ISO_639_2.get(code, code)
    return code if len(code) == 3 or code in TWO_LETTER else None   # no ISO 639-1 language, such as zz


def required_lang(tag):
    """lang_code for a language the caller needs, such as --lang: an empty, undetermined or non-tag value is refused."""
    code = lang_code(tag, '')
    if not code:
        raise ValueError(f'{tag!r} is not a language code; use one such as en or ru')
    return code


# ---- reading -------------------------------------------------------------------------------------------------

class _Extractor(_XhtmlTags, html.parser.HTMLParser):
    BLOCK = BLOCK_ELEMENTS - {'br', 'hr'}   # the draft reader's list, so both sides split words at the same tags; br and hr apart
    SKIP = {'script', 'style', 'head', 'title', 'nav', 'template'}
    CONTAINERS = {'body', 'section', 'div', 'article', 'aside', 'blockquote', 'figure', 'header', 'footer', 'main', 'p'}
    HEADING = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def __init__(self, anchors=None, displays=EMPTY_STYLER):
        super().__init__(convert_charrefs=True)
        self.displays = displays   # the document's styler, which judges display as the import does
        self.paragraphs, self.notes = [], []   # paragraphs are (text, emphasis, language tag)
        self.buffer, self.emphasis, self.heading = [], 0, None
        self.skip_tag, self.skip_depth = None, 0   # a skipped element ends at its own closing tag
        self.stack = []   # (tag, attrs) of each open element, beside langs, for the rules a stylesheet draws with
        self.visible = [True]   # whether each open element's own text shows, beside langs: visibility is inherited, and can return
        self.styled = [S.DEFAULT]   # the flags of each open element's text, beside langs, as the import computes them
        self.emphasis_unresolved = set()   # elements' emphasis values beyond the subset, which the scan cannot count
        self.note, self.anchors, self.langs = None, anchors or {}, [None]
        self.note_lang, self.anchored, self.links, self.sup = None, None, [], 0   # anchored: [tag, depth] of an element a landmark names
        self.labels = []   # [tag, depth, first paragraph] of a block whose class names a page marker
        self.inline_labels = []   # [tag, depth, buffer position, marker only, emphasis so far] of an inline element whose class names one

    def flush(self):
        text = re.sub(r'\s+', ' ', tidy(''.join(self.buffer))).strip()
        if text:
            if self.heading is not None:
                self.paragraphs.append((HEADING, text))
            elif BREAK_LINE.match(text):
                self.paragraphs.append(SCENE_BREAK)
            else:
                self.paragraphs.append((text, self.emphasis, self.langs[-1]))
        self.buffer, self.emphasis = [], 0

    def handle_starttag(self, tag, attrs):
        tag = self.open_tag(tag, attrs)
        a = dict(attrs)
        if self.skip_tag:
            self.skip_depth += tag == self.skip_tag
            if self.note is not None and tag in self.BLOCK | {'br', 'aside'}:
                self.note.append(' ')
            return
        kind = f'{a.get("epub:type") or ""} {a.get("role") or ""}'.lower()
        classes = set((a.get('class') or '').lower().split())   # a marker class drops only a page label (page_label)
        marker = re.search(r'\b(?:pagenum|page-number|pagebreak)\b', kind) \
            or (a.get('aria-hidden') or '').lower() == 'true' or never_shown(tag, a, self.displays, self.stack[::-1])
        if tag in self.SKIP or NOTE_TYPE.search(kind) or NOTE_REF.search(kind) or marker:
            if tag not in VOID_TAGS:
                self.skip_tag, self.skip_depth = tag, 1
                note = NOTE_TYPE.search(kind) and tag not in self.SKIP   # a note's text goes to the copy guard, not the measures
                self.note = [] if note else None
                self.note_lang = (a.get('xml:lang') or a.get('lang') or self.langs[-1]) if note else None
            return
        if tag not in VOID_TAGS:
            self.langs.append(a.get('xml:lang') or a.get('lang') or self.langs[-1])
            self.visible.append(shown_here(tag, a, self.displays, self.stack[::-1], self.visible[-1]))
            flags, beyond = text_style(self.displays, tag, a, self.styled[-1])
            self.styled.append(flags)
            self.emphasis_unresolved |= beyond
            self.stack.append((tag, a))
        if tag in self.BLOCK:
            self.flush()
            if self.labels and tag == self.labels[-1][0]:
                self.labels[-1][1] += 1
            elif classes & PAGE_MARKS:   # dropped at its end only if all it held is a page label
                self.labels.append([tag, 1, len(self.paragraphs), classes <= PAGE_MARKS])
        elif tag not in VOID_TAGS:
            if self.inline_labels and tag == self.inline_labels[-1][0]:
                self.inline_labels[-1][1] += 1
            elif classes & PAGE_MARKS:   # <span class="pagenum">[Pg 12]</span>
                self.inline_labels.append([tag, 1, len(self.buffer), classes <= PAGE_MARKS, self.emphasis])
        if self.anchored and tag == self.anchored[0]:
            self.anchored[1] += 1
        tokens = {t[4:] if t.startswith('doc-') else t for t in kind.split()}   # role="doc-appendix" is epub:type="appendix"
        if tag in self.CONTAINERS and not self.anchored and tokens & (SKIP_TYPES | APPARATUS_TYPES):   # <section epub:type="appendix">
            self.flush()
            self.paragraphs.append((ANCHOR, 'open:' + ('skip' if tokens & SKIP_TYPES else 'apparatus')))
            self.anchored = [tag, 1]
        elif a.get('id') in self.anchors:
            self.flush()
            if tag in self.CONTAINERS and not self.anchored:   # the kind covers the element up to its closing tag
                self.paragraphs.append((ANCHOR, 'open:' + self.anchors[a['id']]))
                self.anchored = [tag, 1]
            else:   # a point anchor: the section it falls in, or the next heading's
                self.paragraphs.append((ANCHOR, self.anchors[a['id']]))
        if tag in self.HEADING:
            self.heading = tag
        if tag == 'a':   # an in-book link whose text is a note marker: a letter in a superscript, [A], or a symbol
            self.links.append((len(self.buffer), self.sup > 0) if '#' in (a.get('href') or '') else None)
        if tag == 'sup':
            self.sup += 1
        if tag == 'hr':
            self.flush()
            if shown_here(tag, a, self.displays, self.stack[::-1], self.visible[-1]):   # a rule no reader sees, its own
                self.paragraphs.append(SCENE_BREAK)   # visibility or its parents', breaks no scene
        if tag == 'br':
            self.buffer.append(' ')

    def handle_endtag(self, tag):
        tag = self.close_tag(tag)
        if self.skip_tag:
            if self.note is not None and tag in self.BLOCK | {'aside'}:
                self.note.append(' ')
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if not self.skip_depth:
                    self.skip_tag = None
                    text = re.sub(r'\s+', ' ', tidy(''.join(self.note or []))).strip()
                    if text:
                        self.notes.append((text, 0, self.note_lang))
                    self.note = None
            return
        if tag == 'a' and self.links:
            link = self.links.pop()
            if link is not None:
                text = ''.join(self.buffer[link[0]:]).strip()
                if (link[1] and re.fullmatch(r'[^\W\d_]{1,2}', text)) or re.fullmatch(r'\[[^\W\d_]{1,2}\]|[*†‡§¶]{1,3}', text):
                    del self.buffer[link[0]:]
        if tag == 'sup':
            self.sup = max(0, self.sup - 1)
        if self.inline_labels and tag == self.inline_labels[-1][0]:
            self.inline_labels[-1][1] -= 1
            if not self.inline_labels[-1][1]:
                _, _, start, marker_only, emphasis = self.inline_labels.pop()
                if page_label(''.join(self.buffer[start:]), marker_only):
                    del self.buffer[start:]
                    self.emphasis = emphasis   # its words were never prose, emphasized or not
        if tag in self.BLOCK:
            self.flush()
            if tag in self.HEADING:
                self.heading = None
            if self.labels and tag == self.labels[-1][0]:
                self.labels[-1][1] -= 1
                if not self.labels[-1][1]:
                    _, _, start, marker_only = self.labels.pop()
                    held = self.paragraphs[start:]
                    text = None if len(held) != 1 or held[0] == SCENE_BREAK or held[0][0] == ANCHOR else held[0][held[0][0] == HEADING]
                    if text is not None and page_label(text, marker_only):
                        del self.paragraphs[start:]
        if self.anchored and tag == self.anchored[0]:
            self.anchored[1] -= 1
            if not self.anchored[1]:
                self.flush()
                self.paragraphs.append((ANCHOR, 'end'))
                self.anchored = None
        if tag not in VOID_TAGS and len(self.langs) > 1:
            self.langs.pop()
            self.stack.pop()
            self.visible.pop()
            self.styled.pop()

    def handle_data(self, data):
        if self.skip_tag:
            if self.note is not None:
                self.note.append(data)
            return
        if not self.visible[-1]:   # text a hidden visibility keeps out of sight; a visible descendant shows again
            return
        self.buffer.append(data)
        if self.styled[-1]['italic'] or self.styled[-1]['weight'] >= 600:   # emphasis as the import marks it: italic, or bold
            self.emphasis += len(WORD.findall(data))


def read_epub(path, budget=None):
    """Book metadata (with the SHA-256 of the bytes read) and its text sections, in reading order. A section under
    SHORT_SECTION words is marked short, and one the EPUB marks as apparatus (a dedication, notes, an appendix, a
    non-linear item) is marked apparatus: the copy guard reads both, the measures leave them out. Contents, copyright
    and other non-prose pages are left out entirely. Raises DRMError for encrypted content and LimitError past the
    limits above; budget counts expanded text across several books (default: a fresh Budget)."""
    budget = budget or Budget()
    if not Path(path).is_file():   # a pipe or a device has no size to check, and may never end
        raise ValueError(f'{path}: not a regular file; give the EPUB file itself')
    with open(path, 'rb') as epub:
        data = epub.read(MAX_INPUT_MB * 2**20 + 1)   # bounded, so a file growing while it is read stays within the limit
    if len(data) > MAX_INPUT_MB * 2**20:
        raise LimitError(f'{path}: over the {MAX_INPUT_MB} MiB a scan reads from one EPUB')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if len(z.infolist()) > MAX_MEMBERS:
            raise LimitError(f'{path}: {len(z.infolist())} archive entries, over the {MAX_MEMBERS:,} a scan reads')
        seen_names = set()
        for info in z.infolist():   # zipfile serves the last of two entries named alike; which a reader takes cannot be told
            if info.filename in seen_names:
                raise ValueError(f'{path}: entry {info.filename!r} appears twice; which copy a reader takes cannot be told')
            seen_names.add(info.filename)

        obfuscated = set()   # fonts the package obfuscates, never read as text
        entries = {}   # each entry read, and charged to the budget, once however often the scan needs it

        def read(name):   # one entry, checked against its declared size before and while reading
            info = z.getinfo(name)
            if info.flag_bits & 0x1 or name in obfuscated:   # first, so a name the package turns out to obfuscate is never served
                raise DRMError(f'{path}: {name} is encrypted; only DRM-free EPUBs can be read')
            if name in entries:
                return entries[name]
            if info.file_size > MAX_ENTRY_MB * 2**20:
                raise LimitError(f'{path}: {name} expands to {info.file_size / 2**20:.0f} MiB, over the {MAX_ENTRY_MB} MiB a scan reads from one entry')
            budget.take_bytes(info.file_size, path)
            with z.open(info) as entry:
                content = entry.read(info.file_size + 1)
            if len(content) != info.file_size:
                raise ValueError(f'{path}: {name} does not hold the {info.file_size} bytes its archive entry declares')
            entries[name] = content
            return content

        names = set(z.namelist())
        obfuscated |= check_epub_drm(names, read, path)
        rootfile = package_path(_xml(read('META-INF/container.xml')))   # its URL path decoded, as the import reads it
        if not rootfile:
            raise ValueError(f'{path}: container.xml names no package file')
        opf = _xml(read(rootfile))
        base = posixpath.dirname(rootfile)
        meta = {'title': '', 'author': '', 'language': '', 'sha256': hashlib.sha256(data).hexdigest()}
        declared = []   # every dc:language: a book that names two languages is no one language's sample
        for e in opf.iter():
            name = _local(e.tag)
            if name == 'language' and (e.text or '').strip():
                declared.append(e.text.strip())
            if name in ('title', 'creator', 'language') and (e.text or '').strip():
                key = {'creator': 'author'}.get(name, name)
                meta[key] = meta[key] or e.text.strip()
        manifest = {}
        for e in opf.iter():
            if _local(e.tag) == 'item':
                manifest[e.get('id')] = (resolve(base, e.get('href', '')) or '', e.get('media-type', ''), e.get('properties', '') or '')   # as the import resolves it
        skip, apparatus, fragments = set(), set(), {}
        unresolved = set()   # stylesheet rules the scan could not settle that might change what shows
        unresolved_emphasis = set()   # rules and values setting emphasis beyond the subset, which the scan cannot count

        def mark(kind, folder, target):   # a #fragment marks only the section it anchors; the rest of the file stays in
            tokens = set((kind or '').lower().split())   # epub:type holds tokens, such as "backmatter colophon"
            if not tokens & (SKIP_TYPES | APPARATUS_TYPES):
                return
            kind = 'skip' if tokens & SKIP_TYPES else 'apparatus'
            file, _, fragment = target.partition('#')
            path = resolve(folder, file) or ''
            if fragment:
                fragments.setdefault(path, {})[unquote(fragment)] = kind
            else:
                (skip if kind == 'skip' else apparatus).add(path)

        for e in opf.iter():   # EPUB 2 guide
            if _local(e.tag) == 'reference':
                mark(e.get('type'), base, e.get('href', ''))
        for href, kind, props in manifest.values():   # EPUB 3 landmarks
            if 'nav' in props.split():
                skip.add(href)
                try:
                    nav = _xml(read(href))
                except ET.ParseError:   # an HTML entity XML does not know; the landmarks then stay unread
                    continue
                for nav_el in nav.iter():
                    if _local(nav_el.tag) == 'nav' and 'landmarks' in (nav_el.get('{http://www.idpf.org/2007/ops}type') or ''):
                        for a in nav_el.iter():
                            if _local(a.tag) == 'a':
                                mark(a.get('{http://www.idpf.org/2007/ops}type'), posixpath.dirname(href), a.get('href', ''))
        chapters, ended, listed, source_section = [], False, set(), 0
        for e in opf.iter():
            if ended or _local(e.tag) != 'itemref':
                continue
            href, kind, props = manifest.get(e.get('idref'), (None, '', ''))
            if not href or href in skip or media_type(kind) != 'application/xhtml+xml':   # XHTML as media types compare, and only XHTML
                continue
            if href in listed:   # read twice, its prose would count twice; the import refuses it too
                raise ValueError(f'{path}: the spine lists {href} more than once')
            listed.add(href)
            data = read(href)   # read and charged once: decoded for a lenient reading, parsed for the tree
            text = _decode(data)
            try:
                root = _xml(data)
            except (ET.ParseError, ValueError):
                root = None
            parser = _Extractor(fragments.get(href), sheet_styler(text, href, read, names, root))
            try:
                if root is not None:   # read with the names the import's XML reader gives, namespaces as XML binds them
                    feed_tree(parser, root)
                else:   # markup no XML parser takes, read leniently
                    parser.feed(text)
            except AssertionError as error:   # html.parser before 3.13 asserts on some malformed declarations
                raise ValueError(f'{path}: {href} has markup the parser cannot read: {error}') from error
            parser.flush()
            unresolved |= parser.displays.unresolved
            unresolved_emphasis |= parser.emphasis_unresolved | getattr(parser.displays, 'emphasis_unresolved', set())
            paragraphs = parser.paragraphs
            starts = [i for i, p in enumerate(paragraphs) if p != SCENE_BREAK and BOOK_START.search(p[1] if p[0] == HEADING else p[0])]
            if starts:   # the wrapper's header ends here
                paragraphs = paragraphs[starts[-1] + 1:]
            ends = [i for i, p in enumerate(paragraphs) if p != SCENE_BREAK and BOOK_END.search(p[1] if p[0] == HEADING else p[0])]
            if ends:   # the wrapper's licence starts here, and nothing after it is the book
                paragraphs, ended = paragraphs[:ends[0]], True
            sections, title, current, kind, pending, inside = [], '', [], None, None, None
            for p in paragraphs:   # one file may hold several chapters: a heading starts the next, and so does an anchor
                if p != SCENE_BREAK and p[0] == ANCHOR and p[1].startswith('open:'):   # an anchored element opens
                    if current:
                        sections.append((title, current, kind))
                        title, current = '', []
                    inside = kind = p[1][5:]
                    pending = None
                elif p != SCENE_BREAK and p[0] == ANCHOR and p[1] == 'end':   # it closed: what follows is not it
                    if current:
                        sections.append((title, current, kind))
                        title, current = '', []
                    kind = pending = inside = None
                elif p != SCENE_BREAK and p[0] == ANCHOR:
                    pending = p[1]
                elif p != SCENE_BREAK and p[0] == HEADING:
                    if current:
                        sections.append((title, current, kind))
                        title = ''
                    title = f'{title} {p[1]}'.strip() if not current and title else p[1]   # stacked headings keep every title
                    current, kind, pending = [], inside or pending or (kind if not current and title != p[1] else None), None
                else:
                    pending = None   # a point anchor marks only a heading that follows it at once, never the text after
                    current.append(p)
            sections.append((title, current, kind))
            real_sections = len(sections)
            if parser.notes:   # notes in the file: guarded, not measured, never taken for front matter
                sections.append(('', parser.notes, 'notes'))
            for index, (title, body, kind) in enumerate(sections):
                text = ' '.join(p[0] for p in body if p != SCENE_BREAK)
                words = count_words(text)
                position = None
                if index < real_sections and (words or count_words(title)):
                    source_section += 1   # inline notes appended above are guard entries, not source sections
                    position = source_section
                if not words and count_words(title) and kind != 'skip' and plain_title(title) not in FRONT_TITLES:   # a heading-only section: guarded
                    chapters.append({'title': title, 'paragraphs': [], 'short': True, 'apparatus': True, 'source_section': position})
                    continue
                blurb = words < FRONT_MATTER_MAX and plain_title(title) in BLURB_TITLES
                front = FRONT_MARKERS.search(f'{title} {text[:300]}') or plain_title(title) in FRONT_TITLES
                if not words or kind == 'skip' or (kind != 'notes' and not blurb and words < FRONT_MATTER_MAX and front):
                    continue   # a short section that opens on a copyright or ISBN notice is front matter
                chapters.append({'title': title, 'paragraphs': body, 'short': words < SHORT_SECTION,
                                 'apparatus': kind in ('apparatus', 'notes') or href in apparatus or e.get('linear') == 'no'
                                              or blurb, 'source_section': position})
    if len({(lang_code(t, t), tag_script(t)) for t in declared}) > 1:   # en and en-US are one language; sr-Latn and sr-Cyrl are not one script
        raise ValueError(f"{path}: its dc:language elements name several languages or scripts ({', '.join(declared)}); a profile "
                         "measures one, so scan a book whose dc:language names only its own")
    tag, meta['language'] = meta['language'], lang_code(meta['language'], '')   # a book measured as one language must name it
    if not meta['language']:
        raise ValueError(f"{path}: its language, {tag!r}, is not a language tag naming one language; set dc:language to the book's code, such as en or ru"
                         if tag else f"{path}: it has no dc:language; set it to the book's code, such as en or ru")
    meta['script'] = tag_script(tag or 'en')
    meta['unresolved_styles'] = sorted(unresolved)
    meta['unresolved_emphasis'] = sorted(unresolved_emphasis)
    return meta, chapters


YAML_LINE = re.compile(r'(?:[A-Za-z0-9_-]+[ \t]*:(?:[ \t].*)?|[ \t]+\S.*|-[ \t]+.*|#.*)$')
LIST_MARKER = re.compile(r'^([ \t]*)(?:[-*+]|\d{1,3}[.)])[ \t]+(?=\S)')
BREAK_ONLY = re.compile(r'^[ \t]*(?:[-*_][ \t]*){3,}$')
TABLE_RULE = re.compile(r'^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$')


def _pairs(text, opening, closing):
    """Each opening bracket's index mapped to its closing one's, nesting counted within a paragraph, as a link's label
    or title may wrap a line; escaped brackets neither open nor close. One pass, however many brackets stay open."""
    pairs, stack, i = {}, [], 0
    while i < len(text):
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == opening:
            stack.append(i)
        elif c == closing and stack:
            pairs[stack.pop()] = i
        elif c == '\n':
            following = text.find('\n', i + 1)
            if not text[i + 1:following if following >= 0 else len(text)].strip():   # a blank line ends the paragraph
                stack = []
        i += 1
    return pairs


def _escaped(text, index):
    """Whether the character at index follows an odd run of backslashes."""
    run = index
    while run and text[run - 1] == '\\':
        run -= 1
    return (index - run) % 2 == 1


def _inline_links(text, defined=frozenset(), every_word=False, titles=None, mark=False):
    """Markdown links as their labels and images as nothing, at any depth of [brackets] and (parentheses); a shortcut
    or collapsed reference image counts when its label is defined. every_word keeps an image's label too, as screen
    readers show it, and its title after it, as a reader sees it in place of the picture: an inline image's own, a
    reference image's from its definition (titles, by label_key); mark puts them between the ONLY_EVERY marks."""
    out, i = [], 0
    brackets, parens = _pairs(text, '[', ']'), _pairs(text, '(', ')')
    while True:
        start = text.find('[', i)
        if start < 0:
            return ''.join(out) + text[i:]
        if _escaped(text, start):   # \[ is a literal bracket
            out.append(text[i:start + 1])
            i = start + 1
            continue
        end = brackets.get(start)
        close = None
        if end is not None and text[end + 1:end + 2] == '(':
            close = parens.get(end + 1)
        elif end is not None and text[end + 1:end + 2] == '[':   # [label][reference]: the reference is not shown
            close = brackets.get(end + 1)
        image = start > 0 and text[start - 1] == '!' and not _escaped(text, start - 1)   # \! is a literal ! before a link
        if close is None and image and end is not None and label_key(text[start + 1:end]) in defined:
            close = end + 2 if text[end + 1:end + 3] == '[]' else end   # ![label] or ![label][] with a definition
        if close is None:
            out.append(text[i:start + 1])
            i = start + 1
            continue
        label = _inline_links(text[start + 1:end], defined, every_word, titles, mark) if every_word or not image else ''
        if every_word and image:
            if text[end + 1:end + 2] == '(':
                title = _link_title(text[end + 2:close])
            else:   # ![label][reference], ![label][] or ![label]: the title its definition gives
                reference = text[end + 2:close] if text[end + 1:end + 2] == '[' else ''
                title = (titles or {}).get(label_key(reference or text[start + 1:end]), '')
            label += ' ' + title if title else ''
            label = ONLY_EVERY[0] + label + ONLY_EVERY[1] if mark else label
        out.append(text[i:start - image] + label + '\n' * (text[start:close + 1].count('\n') - label.count('\n')))   # line numbers kept
        i = close + 1


def label_key(label):
    """A link label as references match it: case folded, its runs of white space one space (CommonMark 4.7)."""
    return ' '.join(label.split()).casefold()


def _destination_end(inner):
    """Where the destination in an inline link's parentheses ends (<a b.png> or one run without spaces, its own
    parentheses balanced), the white space before it counted."""
    lead = len(inner) - len(inner.lstrip())
    rest = inner[lead:]
    if rest.startswith('<'):
        end = rest.find('>')
        return lead + (end + 1 if end >= 0 else len(rest))
    depth, j = 0, 0
    while j < len(rest) and not (rest[j].isspace() and depth == 0):
        if rest[j] == '\\':
            j += 2
            continue
        depth += {'(': 1, ')': -1}.get(rest[j], 0)
        j += 1
    return lead + min(j, len(rest))


def _link_title(inner):
    """The title in an inline link's parentheses, after its destination: "title", 'title' or (title); '' when there
    is none."""
    rest = inner[_destination_end(inner):]
    m = re.fullmatch(r'\s+(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|\(((?:[^()\\]|\\.)*)\))\s*', rest, re.S)
    return next((g for g in m.groups() if g is not None), '') if m else ''


ATTRIBUTE = re.compile(r'([^\s=/>"\']+)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+))?')


def is_hidden(tag):
    """Whether a start tag hides its element: a hidden visibility winning in its style (Markdown keeps no stylesheet, so
    the whole element goes), aria-hidden=true, or what never_shown finds (a display of none in its style, or an element
    a reader does not draw that its style does not draw). Only those attributes count, not CSS-like text elsewhere."""
    name = re.match(r'<([^\s>/]*)', tag).group(1).lower()
    attrs = {k.lower(): (v or '').strip('"\'') for k, v in ATTRIBUTE.findall(re.sub(r'^<[^\s>/]+|/?>$', '', tag))}
    return (S.visibility_of(attrs.get('style', ''))[0] in ('hidden', 'collapse')   # the winning declaration, as a scan reads it
            or attrs.get('aria-hidden', '').lower() == 'true' or never_shown(name, attrs))


def _remove_hidden(text, mark=False):
    """Text without the elements is_hidden finds hidden, contents and nested elements included, quoted attributes
    respected; line breaks are kept. mark keeps each between the ONLY_EVERY marks instead."""
    pos = 0
    while True:
        m = next((m for m in HTML_TAG.finditer(text, pos) if not m.group(0).startswith('</') and not m.group(0).endswith('/>')
                  and is_hidden(m.group(0))), None)
        if not m:
            return text
        name, depth, end = m.group(1).lower(), 1, len(text)
        if name in VOID_TAGS:   # <img hidden>: nothing to close
            if mark:
                text, pos = text[:m.start()] + ONLY_EVERY[0] + m.group(0) + ONLY_EVERY[1] + text[m.end():], m.end() + 2
            else:
                text, pos = text[:m.start()] + text[m.end():], m.start()
            continue
        for t in HTML_TAG.finditer(text, m.end()):
            if t.group(1).lower() == name and not t.group(0).endswith('/>'):
                depth += -1 if t.group(0).startswith('</') else 1
                if not depth:
                    end = t.end()
                    break
        if mark:
            text, pos = text[:m.start()] + ONLY_EVERY[0] + text[m.start():end] + ONLY_EVERY[1] + text[end:], end + 2
        else:
            text, pos = text[:m.start()] + '\n' * text[m.start():end].count('\n') + text[end:], m.start()


def _front_matter(text, mark=False):
    """Text without a YAML front matter block, kept as blank lines; a block of prose between two rules stays. mark
    keeps the block between the ONLY_EVERY marks instead."""
    m = re.match(r'---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*\n', text, re.S)
    if m and m.group(1).strip() and all(YAML_LINE.match(line) for line in m.group(1).split('\n')):
        if mark:
            return ONLY_EVERY[0] + m.group(0) + ONLY_EVERY[1] + text[m.end():]
        return '\n' * m.group(0).count('\n') + text[m.end():]
    return text


def visible_text(text, for_measure=False, every_word=False, mark=False):
    """Markdown as the reader sees it, line for line: YAML front matter, comments, script and style, hidden elements,
    fence lines, table rules, link targets, footnote markers, blockquote and list markers, emphasis markers and HTML
    tags removed, character references decoded and -- or --- read as dashes, so markup inside a copied passage does not
    split it. Text in fences, footnotes and autolinks stays, as a reader sees it. Line numbers are kept. for_measure
    keeps emphasis markers (counted as emphasis) and starts a new paragraph at each list item. every_word, for the copy
    guard, also keeps the words a reader does not see: hidden elements, front matter, image text and reference
    definitions. What interrupts prose (comments, script-like blocks, tags, link addresses and titles) goes in both, so
    it splits no passage; the guard's raw reading scans what it holds. mark, with every_word, puts what only that reading
    holds between the ONLY_EVERY marks, so the guard can tell which source copy each reading reads."""
    blank = lambda m: '\n' * m.group(0).count('\n')
    mark = mark and every_word
    text = tidy(text.replace('\r\n', '\n').replace('\r', '\n'))
    if not every_word or mark:
        text = _front_matter(text, mark)
    text = re.sub(r'<!--.*?-->', blank, text, flags=re.S)
    text = re.sub(r'<(script|style|template|title|head|svg|math)\b[^>]*>.*?</\1\s*>', blank, text, flags=re.S | re.I)   # not prose a reader reads
    if not every_word or mark:
        text = _remove_hidden(text, mark)
    defined = {label_key(m.group(1)) for m in re.finditer(r'(?m)^[ \t]{0,3}\[(?!\^)([^\]\n]+)\]:', text)}
    title = r'(?:"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|\((?:[^()\\\n]|\\.)*\))'
    definition = (r'(?m)^[ \t]{0,3}\[(?!\^)([^\]\n]+)\]:[ \t]*\n?[ \t]*(?:<[^>\n]*>|\S+)'   # the address may start the next line
                  r'(?:[ \t]+(' + title + r')|[ \t]*\n[ \t]*(' + title + r'))?[ \t]*$')   # and so may the title, indented or not (CommonMark 4.7)
    titles = {}
    for m in re.finditer(definition, text):
        titles.setdefault(label_key(m.group(1)), (m.group(2) or m.group(3) or '')[1:-1])   # the first definition counts
    text = _inline_links(text, defined, every_word, titles, mark)
    text = re.sub(r'\[\^[^\]\s]+\](?!:)', '', text)   # a footnote marker
    if not every_word:   # the guard keeps a reference definition's line: its title shows as a tooltip
        text = re.sub(definition, lambda m: '\n' * m.group(0).count('\n'), text)
    elif mark:
        text = re.sub(definition, lambda m: ONLY_EVERY[0] + m.group(0) + ONLY_EVERY[1], text)
    text = re.sub(r'(?m)^([ \t]{0,3})\[\^[^\]\n]+\]:', r'\1', text)   # a footnote keeps its text, loses its label
    text = re.sub(r'<(https?://[^>\s]*)>', r'\1', text)   # an autolink shows its address
    if for_measure:   # raw HTML keeps its emphasis, headings and paragraphs for measuring
        text = re.sub(r'<(em|i|strong|b)\b[^>]*>(.*?)</\1\s*>', r'*\2*', text, flags=re.S | re.I)
        text = re.sub(r'<span\b(?=[^>]*(?:font-style\s*:\s*italic|class\s*=\s*["\'][^"\']*\b(?:italic|emphasis|em)\b))[^>]*>(.*?)</span\s*>', r'*\1*', text,
                      flags=re.S | re.I)   # an italic span, as the epub side counts it
        text = re.sub(r'<h([1-6])\b[^>]*>(.*?)</h\1\s*>', lambda m: '\n\n' + '#' * int(m.group(1)) + ' ' + re.sub(r'\s+', ' ', m.group(2)) + '\n\n',
                      text, flags=re.S | re.I)
    def tag(m):   # a standard element's tag goes; a block or <br> leaves a space between words; anything else is text
        name = m.group(1).lower()
        if name not in HTML_ELEMENTS and '-' not in name:   # a custom element's name holds a hyphen
            return m.group(0)
        if every_word and name == 'img' and not m.group(0).startswith('</'):   # its alt and title, as a Markdown image's
            attrs = {k.lower(): (v or '').strip('"\'') for k, v in ATTRIBUTE.findall(re.sub(r'^<[^\s>/]+|/?>$', '', m.group(0)))}
            words = ' '.join(w for w in (attrs.get('alt', ''), attrs.get('title', '')) if w.strip())
            words = ONLY_EVERY[0] + words + ONLY_EVERY[1] if mark and words else words
            return ' ' + words + ' ' + blank(m) if words else blank(m)
        if name in BLOCK_ELEMENTS:
            return '\n\n' if for_measure and name != 'br' else ' ' + blank(m)
        return blank(m)
    text = HTML_TAG.sub(tag, text)
    lines = []
    for line in text.split('\n'):
        if re.match(r'^[ \t]*(?:```|~~~)', line) or ('|' in line and TABLE_RULE.match(line)):
            line = ''
        elif not BREAK_ONLY.match(line):
            line = re.sub(r'^[ \t]{0,3}(?:>[ \t]?)+', '', line)   # blockquote markers
            marker = LIST_MARKER.match(line)
            if marker:
                line = ('\n' if for_measure else '') + marker.group(1) + line[marker.end():]
            if not for_measure:
                line = re.sub(r'(\*{1,3})(?=\S)(.+?)(?<=\S)\1', r'\2', line)   # paired emphasis markers split no word; a lone * stays
                line = re.sub(r'(?<!\w)_+|_+(?!\w)', '', line)
            line = line.replace('---', '—').replace('--', '–')
        lines.append(line)
    return html.unescape('\n'.join(lines))   # &eacute; reads as é


def interruptions(text):
    """The spans of raw text that neither visible reading reads as prose: comments, script-like blocks, standard tags
    (an img's alt and title apart, which the every-word reading reads), a link's destination and title or reference
    (an image's title apart, read the same way), footnote markers and labels, fence lines, and character references
    (their names are no words a reader sees)."""
    spans = [m.span() for m in re.finditer(r'<!--.*?-->', text, re.S)]
    spans += [m.span() for m in re.finditer(r'<(script|style|template|title|head|svg|math)\b[^>]*>.*?</\1\s*>', text, re.S | re.I)]
    for m in HTML_TAG.finditer(text):
        name = m.group(1).lower()
        if name not in HTML_ELEMENTS and '-' not in name:
            continue
        at = m.start()
        if name == 'img' and not m.group(0).startswith('</'):
            for a in ATTRIBUTE.finditer(m.group(0)):
                if a.group(1).lower() in ('alt', 'title') and a.group(2):
                    spans.append((at, m.start() + a.start(2)))
                    at = m.start() + a.end(2)
        spans.append((at, m.end()))
    brackets, parens = _pairs(text, '[', ']'), _pairs(text, '(', ')')
    for start, end in brackets.items():
        if text[end + 1:end + 2] == '(' and end + 1 in parens:
            close = parens[end + 1]
            if start > 0 and text[start - 1] == '!':
                spans += [(end + 1, end + 2 + _destination_end(text[end + 2:close])), (close, close + 1)]
            else:
                spans.append((end + 1, close + 1))
        elif text[end + 1:end + 2] == '[' and end + 1 in brackets:
            spans.append((end + 1, brackets[end + 1] + 1))
    for pattern in (r'\[\^[^\]\s]+\](?!:)', r'(?m)^[ \t]{0,3}\[\^[^\]\n]+\]:', r'(?m)^[ \t]*(?:```|~~~).*$',
                    r'&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);'):
        spans += [m.span() for m in re.finditer(pattern, text)]
    return sorted(spans)


def plain_positions(block):
    """For each character of a Markdown block, its index in the block's plain text (emphasis markers out, white space
    collapsed, as read_markdown makes it); None for a marker it drops."""
    dropped = set()
    for m in re.finditer(r'[*_]{1,3}([^*_]+)[*_]{1,3}', block):
        dropped.update(range(m.start(), m.start(1)), range(m.end(1), m.end()))
    where, n, space = [None] * len(block), 0, False
    for i, ch in enumerate(block):
        if i in dropped:
            continue
        if re.match(r'\s', ch):
            n += 0 if space else 1
            space = True
        else:
            n += 1
            space = False
        where[i] = n - 1
    return where


def read_markdown(text, exclude=()):
    """A candidate in Markdown as one chapter per top heading, or one chapter, measured as the reader sees it. Footnote
    definitions are left out of the measures, as a book's notes are; the copy guard still reads them. exclude: passages
    (white space collapsed) cut out of the paragraphs that hold them, each kept in its chapter's 'apart' list with the
    words it emphasizes, the rest of its paragraph measured with the rest of its emphasis. source_paragraphs keeps
    each retained paragraph's reader position before exclusions, with None for a scene break."""
    text = re.sub(r'(?m)^[ \t]{0,3}\[\^[^\]\n]+\]:.*(?:\n(?:[ \t]*\n)*(?:[ \t]{4}|\t).*)*', lambda m: '\n' * m.group(0).count('\n'),
                  text.replace('\r\n', '\n').replace('\r', '\n'))
    text = visible_text(text, for_measure=True)
    chapters, current, paragraph = [], {'title': '', 'paragraphs': [], 'source_paragraphs': []}, 0
    for block in re.split(r'\n\s*\n', text):
        block = block.strip()
        if not block:
            continue
        setext = re.match(r'^(.+?)\n[ \t]*(?:=+|-+)[ \t]*$', block, re.S)   # Title over === or --- is a heading too
        heading = re.match(r'^#{1,6}\s+(.*)', block) or (setext if setext and '\n' not in setext.group(1).strip() else None)
        if heading:
            if current['paragraphs'] or current.get('apart'):
                chapters.append(current)
            current, paragraph = {'title': heading.group(1).strip(), 'paragraphs': [], 'source_paragraphs': []}, 0
            block = block[heading.end():].strip()
            if not block:
                continue
        if BREAK_LINE.match(block) or re.match(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$', block):
            current['paragraphs'].append(SCENE_BREAK)
            current['source_paragraphs'].append(None)
            continue
        paragraph += 1
        marks = list(re.finditer(r'(?<![\w*_])(\*{1,3}|_{1,3})(?!\s)(.+?)(?<!\s)\1(?![\w*_])', block, re.S))
        plain = re.sub(r'\s+', ' ', re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', block))
        cuts = sorted({(m.start(), m.end(), e) for e in exclude if e for m in re.finditer(re.escape(e), plain)})
        if not cuts:
            current['paragraphs'].append((plain, sum(count_words(m.group(2)) for m in marks)))
            current['source_paragraphs'].append(paragraph)
            continue
        where = plain_positions(block)   # each emphasized stretch where it stands, by position in the markup
        spans = []
        for m in marks:
            kept = [where[i] for i in range(m.start(2), m.end(2)) if where[i] is not None]
            spans.append((min(kept), max(kept) + 1, count_words(m.group(2))) if kept else (-1, -1, 0))
        merged = []   # overlapping or touching passages are cut as one stretch, every offset the paragraph's own
        for a, b, _passage in cuts:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])

        def left(a, b):   # what of plain[a:b] the cuts leave
            parts, at = [], a
            for x, y in merged:
                if x < b and y > at:
                    parts.append(plain[at:max(at, x)])
                    at = max(at, y)
            return ' '.join(parts + [plain[at:b]] if at < b else parts)
        for a, b, passage in cuts:
            current.setdefault('apart', []).append((passage, sum(s[2] for s in spans if s[0] >= 0 and a <= s[0] and s[1] <= b)))
        rest = re.sub(r'\s+', ' ', left(0, len(plain))).strip()
        if rest:   # the emphasis the cuts leave: each emphasized stretch counted by its words outside them
            current['paragraphs'].append((rest, sum(count_words(left(s[0], s[1])) if s[0] >= 0 else s[2] for s in spans)))
            current['source_paragraphs'].append(paragraph)
    if current['paragraphs'] or current.get('apart'):
        chapters.append(current)
    return chapters


# ---- language ------------------------------------------------------------------------------------------------

def mostly_cyrillic(text):
    return len(CYRILLIC.findall(text)) > len(LATIN.findall(text))


def paragraph_language(text, default, default_script=None):
    """A paragraph's language from its script: the book's language when the script fits it, else ru or en."""
    cyrillic = mostly_cyrillic(text)
    book_cyrillic = (default_script or tag_script(default)) == 'cyrillic'
    if cyrillic:
        return default if book_cyrillic else 'ru'
    return 'en' if book_cyrillic else default


def split_by_language(chapters, default, default_script=None):
    """{language: chapters}, each paragraph sent to the language its script shows, or to its XHTML language tag when
    the tag names a language of that script (French tagged inside an English book goes to fr). A chapter's 'gaps' are the
    positions after which another language's paragraphs were taken out, so neighbours there were never adjacent.
    Source locators survive language filtering and any earlier import exclusions."""
    out = {}
    for section, ch in enumerate(chapters, 1):
        parts, positions, gaps, previous, paragraph = {}, {}, {}, None, 0
        for index, p in enumerate(ch['paragraphs']):
            if p == SCENE_BREAK:
                for lang in parts:
                    parts[lang].append(SCENE_BREAK)
                    positions[lang].append(None)
                previous = None
                continue
            paragraph += 1
            lang = paragraph_language(p[0], default, default_script)
            tagged = lang_code(p[2], '') if len(p) > 2 and p[2] else ''
            if tagged and (tag_script(p[2]) == 'cyrillic') == mostly_cyrillic(p[0]):
                lang = tagged   # a language tag decides between languages that share a script
            if previous is not None and previous != lang and parts.get(lang):
                gaps.setdefault(lang, set()).add(len(parts[lang]) - 1)
            parts.setdefault(lang, []).append(p)
            positions.setdefault(lang, []).append(ch['source_paragraphs'][index] if 'source_paragraphs' in ch else paragraph)
            previous = lang
        for lang, paragraphs in parts.items():
            out.setdefault(lang, []).append({'title': ch['title'], 'paragraphs': paragraphs, 'short': ch.get('short', False),
                                             'apparatus': ch.get('apparatus', False), 'gaps': frozenset(gaps.get(lang, ())),
                                             'source_section': ch.get('source_section', section), 'source_paragraphs': positions[lang],
                                             **({'source_unit': ch['source_unit']} if 'source_unit' in ch else {})})
    return out


# ---- units ---------------------------------------------------------------------------------------------------

def base(word):
    """A word without an English contraction, so I'm, we're and they'd count as I, we and they."""
    return re.sub(r"['’](?:m|s|re|ve|d|ll)$", '', word)


def norm(word):
    return word.lower().replace('ё', 'е').replace('’', "'")


def unsegmented(text):
    """Whether text contains word characters whose script needs a segmenter this tool does not have."""
    text = unicodedata.normalize('NFKC', text)
    prefixes = ('CJK', 'IDEOGRAPHIC', 'HIRAGANA', 'KATAKANA', 'HENTAIGANA', 'MYANMAR', 'THAI', 'LAO', 'KHMER')
    # Names cover supplementary/extended blocks too, using the same Unicode version as WORD.
    return not text.isascii() and any(WORD.fullmatch(c) and unicodedata.name(c, '').startswith(prefixes)
                                     for c in set(text) if not c.isascii())


def words_of(text):
    return [norm(w) for w in WORD.findall(tidy(text))]


def word_spans(text):
    """tidy(text), and words_of(text) with each word's span in it."""
    tidied = tidy(text)
    return tidied, [(norm(m.group(0)), m.start(), m.end()) for m in WORD.finditer(tidied)]


def count_words(text):
    return len(WORD.findall(tidy(text)))


def sentences(text, lang):
    """Sentences of one paragraph; an abbreviation or an initial does not end one."""
    abbreviations = ABBREVIATIONS.get(lang, set())
    parts, start = [], 0
    for m in SENTENCE_END.finditer(text):
        before = text[start:m.start(1)]
        if before[-5:].lower().replace(' ', '').endswith(('e.g', 'i.e', 'т.е', 'т.д', 'т.п', 'и.т')):
            continue
        if lang in TAG_FORM:
            mark = '…' if m.group(1).startswith('...') else m.group(1)[0]
            rest = text[m.end():].lstrip()
            if mark in '?!…' and rest[:1] in DASHES + '-' and _attributes(mark, re.split(r'\s[—–-]\s', rest[1:])[0], lang):
                continue   # «— Правда? — переспросил он.»: the narration that attributes speech continues its sentence
        elif m.group(1)[0] in '?!…' and set(words_of(text[m.end():m.end() + 40])[:3]) & SPEECH_VERBS.get(lang, set()):
            continue   # "Are you coming?" Tom asked: the tag continues the sentence
        last = WORD.findall(before[-12:])
        token = norm(last[-1]) if last else ''
        if m.group(1).startswith('.') and len(m.group(1).rstrip('"\'»”’)]')) == 1 and (token in abbreviations or (len(token) == 1 and token.isalpha() and before[-1:].isalpha() and before[-1:].isupper())):
            continue
        parts.append(text[start:m.end(1)])
        start = m.end()
    parts.append(text[start:])
    return [s.strip() for s in parts if count_words(s)]


def tag_verb(clause, lang, before=False, aside=False):
    """The verb of a clause attributing speech, the one nearest the speech: in the clause's first sentence, read from the
    start (before=True: its last sentence, read back from the colon that opens the speech), a listed speech verb wherever
    it stands; among the TAG_WINDOW words nearest the speech, a first-person present tag or a present action verb
    (NEAR_VERBS: говорю я, я говорю, мы шепчем), or a past-tense form written lowercase (not a name such as Михаил) and
    not right after a preposition (со стула). In an aside (aside=True: after a comma and a dash, which also stand inside
    speech), я or мы before the verb and a subordinate clause after it go on speaking: «я спрашиваю, чтобы сменить тему».
    The first such word decides: a present or past-tense one further away is the predicate of something else, so a
    listed verb after it attributes nothing («…, ты видела двух мужчин, и они говорили»). None when no word decides, or
    the language has no tag forms."""
    if lang not in TAG_FORM:
        return None
    pieces = _clause_sentences(clause.strip(), lang)
    words = WORD.findall(tidy(pieces[-1] if before else pieces[0])) if pieces else []
    for near, i in enumerate(range(len(words) - 1, -1, -1) if before else range(len(words))):
        word = norm(words[i])
        if word in SPEECH_VERBS[lang]:
            return word
        after = norm(words[i - 1]) if i else ''
        if word in NEAR_VERBS[lang] and aside and after in ('я', 'мы') and SUBORDINATORS[lang] & {norm(w) for w in words[i + 1:]}:
            return None   # the speaker goes on: «я спрашиваю, чтобы…» decides, and nothing in its clause is a tag's verb
        if word in NEAR_VERBS[lang] or (
                words[i][:1].islower() and len(word) > 3 and TAG_FORM[lang].search(word) and word not in NOT_TAG_VERBS[lang]
                and after not in PREPOSITIONS[lang]):
            return word if near < TAG_WINDOW else None   # the clause's own first predicate, too far from the speech for a tag
    return None


def _clause_sentences(text, lang):
    """The sentences of an attributing clause, for tag_verb: as sentences() ends them, an initial (И. И. Сидоров) or an
    abbreviation (т. е.) ending none."""
    parts, start = [], 0
    for m in re.finditer(r'[.!?…]+\s+', text):
        last = WORD.findall(text[start:m.start()][-12:])
        token = last[-1] if last else ''
        if m.group(0).rstrip() == '.' and ((len(token) == 1 and token.isupper()) or norm(token) in ABBREVIATIONS.get(lang, ())):
            continue
        parts.append(text[start:m.end()].strip())
        start = m.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _attributes(mark, clause, lang):
    """Whether narration right after speech ending with mark attributes that speech, by Russian punctuation of direct
    speech: after a comma, when it holds a tag verb (a comma also stands before a dash inside speech); after ?!…, when it
    opens lowercase, or with a name followed by a listed speech verb («— Правда? — Иван спросил.»), with up to two words of
    manner between them («Иван тихо спросил»); anything else there, an action or a word of time, makes narration of its own
    («Иван сел и спросил», «Селдон давно заметил»); never after a full stop."""
    clause = clause.lstrip()
    if mark == ',':
        return tag_verb(clause, lang, aside=True) is not None
    if mark not in ('?', '!', '…'):
        return False
    if clause[:1].islower():
        return True
    words = WORD.findall(tidy(clause[:80]))
    names = 0
    while names < min(3, len(words)) and words[names][:1].isupper() and norm(words[names]) not in PRONOUN_OPENERS[lang]:   # Иван Иванович Сидоров
        names += 1
    verb = names
    while verb < min(names + 2, len(words)) and _manner(words[verb], lang):
        verb += 1
    return 0 < names and verb < len(words) and norm(words[verb]) in SPEECH_VERBS[lang]


def _manner(word, lang):
    """Whether word, written lowercase, is a word of manner that may stand between a speaker's name and the speech verb:
    an adverb in -о or -е (тихо, негромко, тоже) or one of MANNER_WORDS (вдруг, снова); never a word of time, nor a
    speech verb that ends the same way (ответило)."""
    w = norm(word)
    return (word[:1].islower() and w not in TIME_WORDS[lang] and w not in SPEECH_VERBS[lang]   # сказало ends like тихо
            and (w in MANNER_WORDS[lang] or (len(w) > 2 and w[-1] in 'ое')))


def _speech_mark(segment):
    """The mark ending a stretch of speech, closing quotes and brackets aside: '…' for three dots too."""
    end = segment.rstrip().rstrip('"\'»”’)]')
    return '…' if end.endswith('...') else end[-1:]


def dash_segments(text, lang):
    """Russian: the speech and narration of a dash-led paragraph, alternating from speech; None for any other paragraph or
    language. A spaced dash turns speech into narration where the narration attributes it (_attributes), and after a
    sentence mark, where Russian punctuation opens the author's words («— Да. — Он молчит.», «— Правда? — Иван закрыл
    окно.»). Only what holds no narration (no predicate, no он, она, оно or они opening it) can go on as speech there: after
    an ellipsis, a pause («— Бластер... — А теперь говори.»), or when the next dash attributes it («— Демократом? — Мой
    премьер-министр, — продолжил Клеон»). A dash turns narration back into speech after a sentence mark, a colon or a
    comma. Any other dash stays inside its speech or narration («А я — ни капельки»)."""
    stripped = text.lstrip()
    if lang not in TAG_FORM or not (stripped[:1] in DASHES or stripped[:2] == '- '):
        return None
    pieces = re.split(r'(\s[—–-]\s)', stripped[1:].strip())
    segments = [pieces[0]]
    for k, (dash, piece) in enumerate(zip(pieces[1::2], pieces[2::2])):
        mark = _speech_mark(segments[-1])
        if len(segments) % 2:   # in speech
            following = pieces[2 * k + 4] if 2 * k + 4 < len(pieces) else None
            narration = _predicate(piece, lang) or norm((WORD.findall(tidy(piece)) or [''])[0]) in ('он', 'она', 'оно', 'они')
            goes_on = mark == '…' or (following is not None and _attributes(_speech_mark(piece), following, lang))
            change = _attributes(mark, piece, lang) or (mark in ('.', '?', '!', '…') and (narration or not goes_on))
        else:
            change = mark in ('.', '?', '!', '…', ':', ',')
        if change:
            segments.append(piece)
        else:
            segments[-1] += dash + piece
    return segments


def _predicate(text, lang):
    """Whether text holds a predicate of narration: a listed speech verb, or a tag's verb among its first words."""
    return tag_verb(text, lang) is not None or any(norm(w) in SPEECH_VERBS[lang] for w in WORD.findall(tidy(text)))


def _quote_pattern(text):
    return DOUBLE_QUOTED if DOUBLE_QUOTED.search(text) else SINGLE_QUOTED   # British style marks speech with single quotes


def speech_spans(text, lang):
    """Russian: a paragraph as (speech?, text) spans in reading order, dash-led or quoted with “ ” or " "; [] without speech.
    «» are not read as speech: Russian prose uses them for titles, names, thoughts and quotations as often as for speech."""
    segments = dash_segments(text, lang)
    if segments is not None:
        return [(i % 2 == 0, s) for i, s in enumerate(segments)]
    spans, at = [], 0
    for m in _quote_pattern(text).finditer(text):
        spans += [(False, text[at:m.start()]), (True, m.group(1) if m.group(1) is not None else m.group(2))]
        at = m.end()
    tail = text[at:]
    opened = _unclosed_quote(tail)
    spans += [(False, tail)] if opened is None else [(False, tail[:opened]), (True, tail[opened + 1:])]
    return [s for s in spans if s[1].strip() or s[0]] if any(speech and count_words(t) for speech, t in spans) else []


def opens_with_speech(text, lang):
    spans = speech_spans(text, lang)
    return bool(spans) and spans[0][0]


def attributions(text, lang, speech_follows=False):
    """Russian: the verbs of the clauses attributing speech in a paragraph, None where none is found. Narration right after
    speech attributes it as _attributes says, with its verb nearest the speech; narration ending with a colon right before
    speech (speech_follows: the next paragraph opens with it) attributes that speech, with its verb nearest the colon.
    Other narration, however many speech verbs it holds, attributes nothing."""
    quoted = dash_segments(text, lang) is None
    spans = speech_spans(text, lang) or [(False, text)]
    verbs = []
    for i, (speech, part) in enumerate(spans):
        if speech:
            continue
        if i and spans[i - 1][0]:
            mark, clause = _speech_mark(spans[i - 1][1]), part.lstrip()
            if quoted:   # a quotation's comma stands after it, and a dash opens its attribution: “Да”, — сказал он.
                if clause[:1] == ',':
                    mark, clause = ',', clause[1:].lstrip()
                clause = clause[1:] if clause[:1] in DASHES + '-' else None
            if clause is not None and _attributes(mark, clause, lang):
                verbs.append(tag_verb(clause, lang, aside=mark == ','))
        follows = spans[i + 1][0] if i + 1 < len(spans) else speech_follows
        if follows and part.rstrip().endswith(':'):
            verbs.append(tag_verb(part.rstrip()[:-1], lang, before=True))
    return verbs


def dialogue_split(text, lang):
    """(speech words, remark text) of one paragraph: quoted speech, or Russian-style dash-led speech."""
    speech, remark = speech_and_remark(text, lang)
    return count_words(speech), remark


def speech_and_remark(text, lang, mark_spoken_ends=False):
    """(speech text, remark text) of one paragraph, as dialogue_split reads it; ('', '') when it holds no speech.
    mark_spoken_ends: a quotation's kept sentence end becomes SPOKEN_END_MARK, so a caller can tell it from the narrator's."""
    segments = dash_segments(text, lang)
    if segments is not None:
        return ' '.join(segments[0::2]), ' '.join(segments[1::2])
    stripped = text.lstrip()
    if lang != 'en' and lang not in TAG_FORM and (stripped[:1] in DASHES or stripped[:2] == '- '):   # dash-led speech; English marks speech with quotes
        body = stripped[1:].strip()
        segments = re.split(r'\s[—–-]\s', body)
        return ' '.join(segments[0::2]), ' '.join(segments[1::2])
    pattern = _quote_pattern(text)
    parts = [m.group(1) if m.group(1) is not None else m.group(2) for m in pattern.finditer(text)]
    remark = pattern.sub(_mark_end if mark_spoken_ends else _keep_end, text)
    opened = _unclosed_quote(remark)   # speech that runs on into the next paragraph opens here and does not close
    if opened is not None:
        parts.append(remark[opened + 1:])
        remark = remark[:opened]
    speech = ' '.join(p for p in parts if p)
    if count_words(speech):
        return speech, remark
    return '', ''


def _keep_end(m):
    """A quotation removed from a remark leaves its sentence end, so the narration after it still opens a sentence."""
    end = re.search(r'[.!?…]+$', (m.group(1) if m.group(1) is not None else m.group(2) or '').strip())
    return f' {end.group(0) if end else ""} '


def _mark_end(m):
    return f' {SPOKEN_END_MARK} ' if _keep_end(m).strip() else '  '


def _unclosed_quote(text):
    """Index of an opening quote left unclosed in text, or None: a double quote anywhere, a single quote only at the
    paragraph's start (where continued speech opens), so an elision such as ‘tis inside narration is not speech."""
    i = text.rfind('“')
    if i >= 0 and '”' not in text[i:]:
        return i
    stripped = len(text) - len(text.lstrip())
    if text[stripped:stripped + 1] == '‘' and not re.search(r'’(?!\w)', text[stripped:]):   # an apostrophe in a word closes nothing
        return stripped
    if text.count('"') % 2:
        return text.rfind('"')
    return None


# ---- measuring -----------------------------------------------------------------------------------------------

def _q(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return values[f] if f == c else values[f] + (values[c] - values[f]) * (k - f)


def mattr(words, window=500):
    if len(words) < window:
        return len(set(words)) / len(words) if words else None
    counts, uniques, total, n = {}, 0, 0.0, 0
    for i, w in enumerate(words):
        counts[w] = counts.get(w, 0) + 1
        if counts[w] == 1:
            uniques += 1
        if i >= window:
            old = words[i - window]
            counts[old] -= 1
            if counts[old] == 0:
                uniques -= 1
        if i >= window - 1:
            total += uniques / window
            n += 1
    return total / n


def measure(chapters, lang):
    """Scalar measures of a body of text, with its counts. A measure that needs more text than there is stays None."""
    sent_lengths, para_words, para_sentences = [], [], []
    words_all, narration_words = [], []
    dialogue_paras = paras = dialogue_words = 0
    tags = plain = 0
    openers = {'pronoun': 0, 'conjunction': 0, 'article': 0}
    opener_total = emphasis = scene_breaks = 0
    punct = {'comma': 0, 'semicolon': 0, 'colon': 0, 'dash': 0, 'ellipsis': 0, 'exclamation': 0, 'question': 0, 'parenthesis': 0}
    simile = 0
    for ch in chapters:
        for pi, p in enumerate(ch['paragraphs']):
            if p == SCENE_BREAK:
                scene_breaks += 1
                continue
            text, emph = p[0], p[1]
            emphasis += emph
            ws = words_of(text)
            if not ws:
                continue
            paras += 1
            words_all.extend(ws)
            speech, remark = dialogue_split(text, lang)
            if lang in TAG_FORM:   # the clauses attributing speech, not every speech verb of the narration
                following = ch['paragraphs'][pi + 1] if pi + 1 < len(ch['paragraphs']) and pi not in ch.get('gaps', ()) else SCENE_BREAK
                for w in attributions(text, lang, following != SCENE_BREAK and opens_with_speech(following[0], lang)):
                    tags += 1
                    plain += w in PLAIN_TAGS[lang]
            if speech:
                dialogue_paras += 1
                dialogue_words += speech
                remark_words = words_of(remark)
                narration_words.extend(remark_words)   # narration around the speech in the same paragraph
                for w in remark_words if lang not in TAG_FORM else ():
                    if w in SPEECH_VERBS.get(lang, ()):
                        tags += 1
                        plain += w in PLAIN_TAGS.get(lang, ())
            else:
                narration_words.extend(ws)
            body = text.lstrip()
            dash_led = lang != 'en' and speech and (body[:1] in DASHES or body[:2] == '- ')   # its dashes mark speech, not prose
            punct['comma'] += body.count(',')
            punct['semicolon'] += body.count(';')
            punct['colon'] += body.count(':')
            punct['dash'] += 0 if dash_led else sum(body.count(d) for d in DASHES) + body.count(' - ')
            punct['ellipsis'] += body.count('…') + body.count('...')
            punct['exclamation'] += body.count('!')
            punct['question'] += body.count('?')
            punct['parenthesis'] += body.count('(')
            simile += len(SIMILE[lang].findall(text)) if lang in SIMILE else 0
            ss = sentences(text, lang)
            para_words.append(len(ws))
            para_sentences.append(len(ss))
            for s in ss:
                sw = words_of(s)
                if sw:
                    sent_lengths.append(len(sw))
            for s in (sentences(remark, lang) if speech else ss):   # openers of narration only, never of speech
                first = re.sub(r'^[\s"\'«“‘(\[—–-]+', '', s)
                fw = words_of(first[:40])
                if fw and not (s.lstrip()[:1] in '"\'«“‘' + DASHES):
                    opener_total += 1
                    openers['pronoun'] += base(fw[0]) in PRONOUN_OPENERS.get(lang, ())
                    openers['conjunction'] += fw[0] in CONJUNCTION_OPENERS.get(lang, ())
                    openers['article'] += fw[0] in ARTICLE_OPENERS.get(lang, ())
    n = len(words_all)
    per_k = (lambda x: 1000.0 * x / n) if n else (lambda x: None)
    out = {'words': n, 'narration_words': len(narration_words), 'sentences': len(sent_lengths), 'paragraphs': paras}
    if sent_lengths:
        mean = statistics.fmean(sent_lengths)
        out.update({
            'sentence_len_median': statistics.median(sent_lengths), 'sentence_len_mean': mean, 'sentence_len_p90': _q(sent_lengths, 0.9),
            'short_sentence_share': sum(1 for x in sent_lengths if x <= 6) / len(sent_lengths),
            'long_sentence_share': sum(1 for x in sent_lengths if x >= 30) / len(sent_lengths),
            'sentence_len_cv': statistics.pstdev(sent_lengths) / mean if mean else None,
            'rhythm_shift': (statistics.fmean(abs(a - b) for a, b in zip(sent_lengths, sent_lengths[1:])) / mean) if len(sent_lengths) > 1 and mean else None,
        })
    if para_words:
        out['paragraph_words_median'] = statistics.median(para_words)
        out['one_sentence_paragraph_share'] = sum(1 for x in para_sentences if x == 1) / len(para_sentences)
    if paras:
        out['dialogue_paragraph_share'] = dialogue_paras / paras
    if n:
        out['dialogue_word_share'] = dialogue_words / n
        for k, v in punct.items():
            out[f'{k}_per_1000'] = per_k(v)
        if lang in SIMILE:
            out['simile_per_1000'] = per_k(simile)
        out['emphasis_per_1000'] = per_k(emphasis)
        out['word_len_mean'] = statistics.fmean(len(w) for w in words_all)
        out['mattr'] = mattr(words_all)
        if lang == 'en':
            out['adverb_ly_per_1000'] = per_k(sum(1 for w in words_all if w.endswith('ly') and len(w) > 4 and w not in NOT_ADVERBS))
    if tags >= 5:
        out['plain_tag_share'] = plain / tags
    if opener_total:
        for k, v in openers.items():
            if lang in {'pronoun': PRONOUN_OPENERS, 'conjunction': CONJUNCTION_OPENERS, 'article': ARTICLE_OPENERS}[k] and (k != 'article' or lang == 'en'):
                out[f'opener_{k}_share'] = v / opener_total
    if narration_words and lang in FIRST_PERSON:   # person needs a language's pronoun lists
        nk = 1000.0 / len(narration_words)
        out['first_person_per_1000'] = nk * sum(1 for w in narration_words if base(w) in FIRST_PERSON.get(lang, ()))
        out['third_person_per_1000'] = nk * sum(1 for w in narration_words if base(w) in THIRD_PERSON.get(lang, ()))
        if lang == 'en':
            past = sum(1 for w in narration_words if w in PAST_EN or (w.endswith('ed') and len(w) > 4))
            present = sum(1 for w in narration_words if w in PRESENT_EN)
            if past + present >= 20:
                out['past_tense_share'] = past / (past + present)
    out['scene_breaks'] = scene_breaks
    out['function_words'] = function_profile(words_all, lang)
    return out


def function_profile(words, lang):
    fw = FUNCTION_WORDS.get(lang)
    if not fw or not words:
        return {}
    counts = {w: 0 for w in fw}
    for w in words:
        if w in counts:
            counts[w] += 1
    return {w: 1000.0 * c / len(words) for w, c in counts.items()}


def cosine(a, b):
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return min(1.0, dot / (na * nb)) if na and nb else None   # rounding can push identical profiles past 1


# ---- targets ---------------------------------------------------------------------------------------------------

# measure: (label, the fewest candidate words that make it meaningful, absolute slack added to each side)
TARGETS = {
    'sentence_len_median': ('median sentence length, words', 400, 1.5),
    'sentence_len_mean': ('mean sentence length, words', 400, 1.5),
    'sentence_len_p90': ('long end of sentence length (90th percentile), words', 600, 3),
    'short_sentence_share': ('share of sentences of 6 words or fewer', 600, 0.04),
    'long_sentence_share': ('share of sentences of 30 words or more', 600, 0.03),
    'sentence_len_cv': ('variation of sentence length (sd / mean)', 600, 0.06),
    'rhythm_shift': ('length shift between consecutive sentences (/ mean)', 600, 0.06),
    'paragraph_words_median': ('median paragraph length, words', 500, 4),
    'one_sentence_paragraph_share': ('share of one-sentence paragraphs', 600, 0.05),
    'dialogue_paragraph_share': ('share of paragraphs with dialogue', 800, 0.06),
    'dialogue_word_share': ('share of words spoken in dialogue', 800, 0.05),
    'plain_tag_share': ('share of plain speech tags (said, asked)', 1200, 0.1),
    'comma_per_1000': ('commas per 1000 words', 1000, 6),
    'semicolon_per_1000': ('semicolons per 1000 words', 1500, 0.6),
    'colon_per_1000': ('colons per 1000 words', 1500, 0.8),
    'dash_per_1000': ('dashes in the prose per 1000 words', 1500, 1.5),
    'ellipsis_per_1000': ('ellipses per 1000 words', 1500, 0.8),
    'exclamation_per_1000': ('exclamation marks per 1000 words', 1500, 0.8),
    'question_per_1000': ('question marks per 1000 words', 1500, 1.2),
    'parenthesis_per_1000': ('parentheses per 1000 words', 1500, 0.5),
    'simile_per_1000': ('simile markers per 1000 words', 1500, 0.6),
    'emphasis_per_1000': ('emphasized words per 1000 words', 1500, 1.0),
    'word_len_mean': ('mean word length, letters', 800, 0.15),
    'mattr': ('vocabulary variety (MATTR, 500-word window)', 1000, 0.02),
    'adverb_ly_per_1000': ('-ly adverbs per 1000 words', 1500, 1.5),
    'opener_pronoun_share': ('sentences opening on a pronoun', 600, 0.05),
    'opener_conjunction_share': ('sentences opening on a conjunction', 800, 0.03),
    'opener_article_share': ('sentences opening on an article', 600, 0.04),
    'first_person_per_1000': ('first-person pronouns in narration per 1000 words', 300, 4),
    'third_person_per_1000': ('third-person pronouns in narration per 1000 words', 300, 4),
    'past_tense_share': ('past-tense share of tense markers in narration', 400, 0.08),
}
FINGERPRINT_MIN_WORDS = 1500
NARRATION_MEASURES = {'first_person_per_1000', 'third_person_per_1000', 'past_tense_share', 'opener_pronoun_share',
                      'opener_conjunction_share', 'opener_article_share'}   # counted on narration only, so judged by its length


def available_targets(lang):
    """The target names measure() can produce for a language: some need its word lists, some are English only."""
    needs = {'adverb_ly_per_1000': lang == 'en', 'past_tense_share': lang == 'en', 'opener_article_share': lang == 'en',
             'opener_pronoun_share': lang in PRONOUN_OPENERS, 'opener_conjunction_share': lang in CONJUNCTION_OPENERS,
             'first_person_per_1000': lang in FIRST_PERSON, 'third_person_per_1000': lang in THIRD_PERSON,
             'simile_per_1000': lang in SIMILE, 'plain_tag_share': lang in PLAIN_TAGS}
    return {k for k in TARGETS if needs.get(k, True)} | ({'function_word_similarity'} if lang in FUNCTION_WORDS else set())


def chapter_values(chapters, lang, min_words=1200):
    """Measures of each chapter long enough to measure, so a target range reflects variation at chapter scale."""
    rows = []
    for ch in chapters:
        m = measure([ch], lang)
        if m['words'] >= min_words:
            rows.append(m)
    return rows


def build_targets(pooled, chapter_rows, half_cosines):
    """half_cosines: how alike each book's halves are, and each book is to the pool: the fingerprint's floor."""
    targets = {}
    for key, (label, min_words, slack) in TARGETS.items():
        values = [r[key] for r in chapter_rows if r.get(key) is not None]
        center = pooled.get(key)
        if center is None:
            continue
        if len(values) >= 4:
            low, high = _q(values, 0.2), _q(values, 0.8)
        else:
            low, high = center * 0.8, center * 1.2
        low, high = min(low, center) - slack, max(high, center) + slack
        if key.endswith('_share') or key == 'mattr':
            low, high = max(0.0, low), min(1.0, high)
        else:
            low = max(0.0, low)
        targets[key] = {'label': label, 'value': round(center, 4), 'low': round(low, 4), 'high': round(high, 4), 'min_words': min_words,
                        'basis': 'chapter spread' if len(values) >= 4 else 'pooled fallback', 'sample_count': len(values)}
    if half_cosines:
        targets['function_word_similarity'] = {'label': 'function-word fingerprint, cosine with the profile', 'value': round(min(half_cosines), 4),
                                               'low': round(max(0.0, min(half_cosines) - 0.05), 4), 'high': 1.0, 'min_words': FINGERPRINT_MIN_WORDS,
                                               'basis': 'source/half comparisons', 'sample_count': len(half_cosines)}
    return targets


def fingerprint(chapters, lang):
    """Word count and function-word rates; avoid sentence and dialogue analysis for cosine-only work."""
    words = [w for ch in chapters for p in ch['paragraphs'] if p != SCENE_BREAK for w in words_of(p[0])]
    return {'words': len(words), 'function_words': function_profile(words, lang)}


def source_to_pool_cosine(chapters, pooled, lang):
    """How alike one book is to the pooled sources in function words, so a draft in any one source's voice stays in range."""
    m = fingerprint(chapters, lang)
    if m['words'] < FINGERPRINT_MIN_WORDS:
        return []
    c = cosine(m['function_words'], pooled['function_words'])
    return [c] if c is not None else []


def half_split_cosines(chapters, lang):
    """How alike the two halves of a book are in function words: a floor for how alike a draft and the profile should be."""
    if len(chapters) < 2:
        return []
    mid = len(chapters) // 2
    a, b = fingerprint(chapters[:mid], lang), fingerprint(chapters[mid:], lang)
    if a['words'] < FINGERPRINT_MIN_WORDS or b['words'] < FINGERPRINT_MIN_WORDS:
        return []
    c = cosine(a['function_words'], b['function_words'])
    return [c] if c is not None else []


# ---- registers and calibration --------------------------------------------------------------------------------
# Ideas adapted from AuthorStyle by Fernando Paladini (MIT, paladini/authorstyle d73e7fc): a draft's distance reported
# against the spread of the author's own held-out text, and style measured by mode. Implemented here on this tool's own
# measures; no AuthorStyle code is used.

REGISTERS = ('narration', 'dialogue')
REGISTER_MIN_WORDS = {'narration': 600, 'dialogue': 400}   # a register is part of a chapter: smaller than the 1,200 words a whole chapter needs
REGISTER_DROP = {name: {'dialogue_paragraph_share', 'dialogue_word_share', 'plain_tag_share', 'emphasis_per_1000'}   # a split paragraph keeps
                 | ({'first_person_per_1000', 'third_person_per_1000', 'past_tense_share', 'opener_pronoun_share', 'opener_conjunction_share',
                     'opener_article_share'} if name == 'dialogue' else set()) for name in ('narration', 'dialogue')}   # no emphasis count
SPOKEN_END_MARK = '\ue000'   # a private-use character: never in a book's text, so only a cut quotation's end carries it
CALIBRATION_METHOD = 1
CALIBRATION_MIN_CHAPTERS = 5
DISTANCE_CAP = 6.0   # one measure far off counts as six spreads, so it cannot swamp the rest
ROBUST_SCALE = 1.4826   # MAD to standard deviation for normally spread values
MEAN_DEVIATION_SCALE = 1.2533   # mean absolute deviation to standard deviation, likewise


def register_chapters(chapters, lang, register):
    """The chapters cut to one register, in order: the spoken words of each paragraph (dialogue), or the author's words,
    a whole paragraph without speech and the narration around speech in one that has it (narration)."""
    out = []
    for ch in chapters:
        keep = []
        for p in ch['paragraphs']:
            if p == SCENE_BREAK:
                continue
            speech, remark = speech_and_remark(p[0], lang, mark_spoken_ends=True)
            if count_words(speech):   # a quotation's kept sentence end stays a break in the narration, not its ? ! or …
                part = speech if register == 'dialogue' else remark.replace(SPOKEN_END_MARK, '.')
            else:
                part = '' if register == 'dialogue' else p[0]
            if words_of(part):
                keep.append((part, 0))
        out.append({'title': ch.get('title', ''), 'paragraphs': keep})
    return out


def register_targets(chapters, lang):
    """Target ranges for narration and for dialogue apart, where at least four chapters hold enough of each."""
    out = {}
    for name in REGISTERS:
        part = register_chapters(chapters, lang, name)
        pooled = measure(part, lang)
        rows = chapter_values(part, lang, REGISTER_MIN_WORDS[name]) if pooled['words'] else []
        if len(rows) < 4:
            continue
        targets = {k: v for k, v in build_targets(pooled, rows, []).items()
                   if k not in REGISTER_DROP[name] and k in available_targets(lang)}
        if targets:   # each register calibrated on its own chapters: a restyle rewrites the narration, and dialogue share is not in it
            out[name] = {'targets': targets, 'chapters_measured': len(rows), 'words': pooled['words'], 'min_words': REGISTER_MIN_WORDS[name],
                         'calibration': calibration(rows, list(targets), REGISTER_MIN_WORDS[name])}
    return out


def _spread(values):
    """Median and robust scale. When most chapters share one value exactly, as whole-number measures often do, the median
    absolute deviation is zero though the measure varies: the mean absolute deviation, scaled alike, stands in."""
    center = statistics.median(values)
    deviations = [abs(v - center) for v in values]
    scale = statistics.median(deviations) * ROBUST_SCALE
    return center, scale if scale > 1e-9 else statistics.fmean(deviations) * MEAN_DEVIATION_SCALE


def _spreads(rows, keys):
    out = {}
    for key in keys:
        values = [r[key] for r in rows if r.get(key) is not None]
        if len(values) >= 4:
            center, scale = _spread(values)
            if scale > 1e-6 * max(1.0, abs(center)):   # a measure every chapter shares, or all but exactly, says nothing about distance
                out[key] = (center, scale)
    return out


def distance(measures, centers, scales):
    """Mean robust distance over the measures both sides have: |value - center| / scale, each capped."""
    parts = [min(abs(measures[k] - centers[k]) / scales[k], DISTANCE_CAP) for k in centers if measures.get(k) is not None and k in scales]
    return (statistics.fmean(parts), len(parts)) if parts else (None, 0)


def calibration(rows, keys, min_words=1200):
    """Leave-one-out distances of the source chapters: each chapter against the spread of all the others, so a draft's
    distance can be read against how far the sources' own chapters lie from the rest."""
    keys = [k for k in keys if k != 'function_word_similarity']
    if len(rows) < CALIBRATION_MIN_CHAPTERS:
        return {'method': CALIBRATION_METHOD, 'status': 'unavailable', 'chapters': len(rows),
                'reason': f'{len(rows)} chapter(s) long enough to measure; {CALIBRATION_MIN_CHAPTERS} are needed'}
    # one panel for every comparison: a measure every chapter has and that still varies when any one chapter is held out,
    # so each held-out distance and a draft's distance average the same measures
    full = _spreads(rows, [k for k in keys if all(r.get(k) is not None for r in rows)])
    folds = [_spreads(rows[:i] + rows[i + 1:], full) for i in range(len(rows))]
    panel = [k for k in full if all(k in f for f in folds)]
    if not panel:
        return {'method': CALIBRATION_METHOD, 'status': 'unavailable', 'chapters': len(rows),
                'reason': 'no measure varies between the chapters with any one of them held out'}
    held_out = sorted(round(distance(row, {k: fold[k][0] for k in panel}, {k: fold[k][1] for k in panel})[0], 4)
                      for row, fold in zip(rows, folds))
    full = {k: full[k] for k in panel}
    return {'method': CALIBRATION_METHOD, 'status': 'available', 'chapters': len(held_out), 'min_words': min_words, 'cap': DISTANCE_CAP,
            'centers': {k: c for k, (c, _) in full.items()}, 'scales': {k: s for k, (_, s) in full.items()},   # unrounded: a small scale stays positive
            'distances': held_out,
            'quantiles': {'p10': round(_q(held_out, 0.1), 4), 'p50': round(_q(held_out, 0.5), 4), 'p90': round(_q(held_out, 0.9), 4), 'max': held_out[-1]}}


def calibrated(measures, cal):
    """A draft's distance and where it falls among the sources' own chapters, or None without a usable calibration."""
    if not cal or cal.get('status') != 'available':
        return None
    if any(measures.get(k) is None for k in cal['centers']):   # the held-out chapters were all measured on the whole panel
        return None
    d, used = distance(measures, cal['centers'], cal['scales'])
    held_out = cal['distances']
    return {'distance': round(d, 4), 'measures_used': used, 'closer_than_share': round(sum(1 for x in held_out if x > d) / len(held_out), 4),
            'beyond_sources': d > held_out[-1], 'source_chapters': len(held_out)}


# ---- copy guard ----------------------------------------------------------------------------------------------

SHINGLE = 8
WINDOW = 8
CAUGHT = SHINGLE + WINDOW - 1   # a shared run this long or longer is always caught


def shingle_hashes(words):
    """(hash, index) of each run of SHINGLE words."""
    return [(hashlib.sha1(' '.join(words[i:i + SHINGLE]).encode('utf-8')).hexdigest()[:12], i)
            for i in range(len(words) - SHINGLE + 1)]


def guard_hashes(words):
    """A book's copy-guard hashes, by winnowing: the smallest run hash in every WINDOW consecutive runs. A draft run
    of CAUGHT words shared with the book holds WINDOW whole runs of it, so their smallest hash is kept, and checking
    every run of the draft finds it. Shorter shared runs are found only when one of their hashes was kept."""
    runs = [h for h, _ in shingle_hashes(words)]
    if len(runs) < WINDOW:
        return set(runs)
    return {min(runs[i:i + WINDOW]) for i in range(len(runs) - WINDOW + 1)}


# ---- comparing -----------------------------------------------------------------------------------------------

def method_gap(profile):
    """The targets this tool reads differently from the scan that built profile, for the profile's language: the changes
    between its measure_method (1 when it records none) and MEASURE_METHOD. A method this tool does not know, a newer
    release's, shares no meaning it can vouch for: every target. Profiles are validated first, which refuses one."""
    lang = lang_code(profile.get('language'), '')
    have, now = profile.get('measure_method', 1), MEASURE_METHOD.get(lang, 1)
    if type(have) is not int or not 1 <= have <= now:
        return frozenset(profile.get('targets', ()))
    return frozenset().union(*(METHOD_CHANGES.get((lang, m), ()) for m in range(have + 1, now + 1)))


def compare(candidate, profile):
    """Rows of (key, label, value, low, high, status) for each target the profile sets. A target whose measure this tool
    reads differently from the profile's scan is 'incomparable': rescan the profile before comparing it."""
    rows = []
    words = candidate['words']
    gap = method_gap(profile)
    for key, t in profile['targets'].items():
        if key == 'function_word_similarity':
            value = cosine(candidate.get('function_words', {}), profile['function_words'])
        else:
            value = candidate.get(key)
        if key in gap:   # before availability: an older profile's target is never merely unmeasured
            rows.append((key, t['label'], value, t['low'], t['high'], 'incomparable (another measure method: rescan the profile)'))
            continue
        if value is None:
            rows.append((key, t['label'], None, t['low'], t['high'], 'not measured'))
            continue
        width = max(t['high'] - t['low'], 1e-9)
        if t['low'] <= value <= t['high']:
            status = 'within'
        elif t['low'] - 0.15 * width <= value <= t['high'] + 0.15 * width:
            status = 'near'
        else:
            status = 'outside'
        if (candidate.get('narration_words', words) if key in NARRATION_MEASURES else words) < t['min_words']:
            status += ' (weak: short text)'
        rows.append((key, t['label'], value, t['low'], t['high'], status))
    return rows

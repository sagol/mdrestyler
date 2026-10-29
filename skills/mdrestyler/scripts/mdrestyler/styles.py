"""The CSS subset that decides what an EPUB shows, read as a scan reads it: each element's effective display, visibility
and emphasis from the book's stylesheets and inline declarations, by importance, the style attribute, specificity and
order. No browser engine and no general CSS: a rule outside the subset is reported, never guessed. Standard library only."""
import copy
import functools
import re
import xml.etree.ElementTree as ET

SUPPORTED_ELEMENTS = {'p', 'span', 'div', 'em', 'i', 'b', 'strong', 'small', 'sup', 'sub', 'blockquote'}
PROPERTIES = {'font-style', 'font-weight', 'font-variant', 'text-transform', 'text-decoration', 'text-decoration-line',
              'vertical-align', 'display', 'visibility', 'font'}
UNSUPPORTED_VALUES = {'initial', 'unset', 'revert', 'revert-layer'}
CSS_NUMBER = r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'   # CSS's number: no bare dot, no underscore
ANGLE_DEGREES = {'deg': 1.0, 'grad': 0.9, 'rad': 57.29577951308232, 'turn': 360.0}
NAMED_COLORS = set('aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen transparent currentcolor'.split())
FONT_VARIANT = {'caps': {'small-caps', 'all-small-caps', 'petite-caps', 'all-petite-caps', 'unicase', 'titling-caps'},
                'common': {'common-ligatures', 'no-common-ligatures'}, 'discretionary': {'discretionary-ligatures', 'no-discretionary-ligatures'},
                'historical': {'historical-ligatures', 'no-historical-ligatures'}, 'contextual': {'contextual', 'no-contextual'},
                'figure': {'lining-nums', 'oldstyle-nums'}, 'spacing': {'proportional-nums', 'tabular-nums'},
                'fraction': {'diagonal-fractions', 'stacked-fractions'}, 'ordinal': {'ordinal'}, 'zero': {'slashed-zero'},
                'variant': {'jis78', 'jis83', 'jis90', 'jis04', 'simplified', 'traditional'}, 'width': {'full-width', 'proportional-width'},
                'ruby': {'ruby'}, 'position': {'sub', 'super'}, 'forms': {'historical-forms'}, 'emoji': {'text', 'emoji', 'unicode'}}
DECORATION = {'line': {'underline', 'overline', 'line-through', 'blink'}, 'style': {'solid', 'double', 'dotted', 'dashed', 'wavy'}}
VERTICAL = {'baseline', 'sub', 'super', 'text-top', 'text-bottom', 'middle', 'top', 'bottom'}
CHECKED = {'font-style', 'font-weight', 'font-variant', 'text-transform', 'text-decoration', 'text-decoration-line', 'vertical-align'}
SELECTOR = re.compile(r'^([a-z][a-z0-9]*)?(?:\.([A-Za-z_][\w-]*))?$')
NEVER_SHOWN = {'template', 'datalist', 'noembed', 'noframes'}   # elements a reader does not draw, as a closed dialog
DEFAULT = {'italic': False, 'weight': 400.0, 'smallcaps': False, 'upper': False, 'underline': False, 'strike': False,
           'sup': False, 'sub': False, 'hidden': False}


def local(tag):
    return tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else ''


NUMBER = re.compile(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z%]*)$')
EMS = {'em': 1, 'rem': 1, 'ex': 0.5, 'ch': 0.5, 'px': 1 / 16, 'pt': 1 / 12, 'pc': 1, 'in': 6, 'cm': 6 / 2.54,
       'mm': 0.6 / 2.54, 'q': 0.15 / 2.54}   # at a 16px root
SIZE_WORDS = {'xx-small', 'x-small', 'small', 'medium', 'large', 'x-large', 'xx-large', 'xxx-large', 'smaller', 'larger', 'math'}


def ems(value, percent=None):
    """A CSS length in ems at a 16px root, percent being the ems of 100%; None when it cannot be told."""
    m = NUMBER.match(value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if number == 0:
        return 0.0
    if unit == '%':
        return number / 100 * percent if percent is not None else None
    return number * EMS[unit] if unit in EMS else None


def far(value):
    """An offset, indent or margin of ten ems or a whole containing block, enough to leave the page; one that cannot be
    told counts as far."""
    if value == 'auto':
        return False
    m = NUMBER.match(value)
    if m and m.group(2) == '%':
        return abs(float(m.group(1))) >= 100
    size = ems(value)
    return size is None or abs(size) >= 10


def tiny(value):
    """A font size under a quarter of an em, zero included, or one that cannot be told."""
    size = None if value in SIZE_WORDS else ems(value, percent=1)
    return value not in SIZE_WORDS and (size is None or size < 0.25)


def faded(value):
    """An opacity short of opaque."""
    m = NUMBER.match(value)
    return not m or m.group(2) not in ('', '%') or float(m.group(1)) < (100 if m.group(2) == '%' else 1)


def see_through(value):
    """A colour a reader sees through, wholly or in part."""
    if 'transparent' in value:
        return True
    m = re.fullmatch(r'#([0-9a-f]{4}|[0-9a-f]{8})', value)
    if m:
        return not m.group(1).endswith('f' if len(m.group(1)) == 4 else 'ff')
    m = re.fullmatch(r'[a-z-]+\((.*)\)', value)
    args = m.group(1) if m else ''
    alpha = args.rsplit('/', 1)[1] if '/' in args else args.split(',')[3] if args.count(',') == 3 else None
    return alpha is not None and faded(alpha.strip())


QUIET_FEATURES = {'liga', 'clig', 'dlig', 'calt', 'rlig', 'kern', 'onum', 'lnum', 'pnum', 'tnum', 'case', 'cpsp', 'locl', 'ccmp',
                  'mark', 'mkmk'}   # ligatures, kerning, numeral styles and the like: the same letters, unemphasized


def loud_features(value):
    """font-feature-settings that switch on a feature beyond QUIET_FEATURES, such as small caps or superscripts."""
    for part in value.split(','):
        m = re.fullmatch(r'\s*["\']([\w ]{4})["\']\s*(on|off|\d+)?\s*', part)
        if not m or (m.group(1) not in QUIET_FEATURES and m.group(2) not in ('off', '0')):
            return True
    return False


LISTED = {   # properties outside the read subset that can hide text, move it out of view or change what it shows
    'opacity': faded, 'filter': lambda v: v != 'none', 'color': see_through, '-webkit-text-fill-color': see_through,
    'font-size': tiny, 'zoom': lambda v: v not in ('normal', 'reset') and tiny(v if v.endswith('%') else v + 'em'),
    'clip': lambda v: v != 'auto', 'position': lambda v: v in ('absolute', 'fixed'),
    'content-visibility': lambda v: v == 'hidden', 'unicode-bidi': lambda v: 'override' in v,
    'z-index': lambda v: v != 'auto' and not v.isdigit(), 'text-indent': lambda v: any(far(p) for p in v.split() if p not in ('hanging', 'each-line')),
    'quotes': lambda v: v != 'auto', 'font-variant-caps': lambda v: v != 'normal', 'all': lambda v: True,
    'white-space': lambda v: v not in ('normal', 'nowrap'), 'white-space-collapse': lambda v: v != 'collapse',
    **{p: lambda v: bool(css_references(v)) for p in ('background', 'background-image', 'list-style', 'list-style-image',
                                                      'border-image', 'border-image-source', '-webkit-border-image')},   # artwork
    'font-feature-settings': lambda v: v != 'normal' and loud_features(v)}
LISTED.update({p: lambda v: v != 'none' for p in (
    'clip-path', '-webkit-clip-path', 'mask', 'mask-image', '-webkit-mask', '-webkit-mask-image', 'transform', 'translate',
    'scale', 'rotate', '-webkit-text-security', 'line-clamp', '-webkit-line-clamp', 'max-lines', 'text-emphasis',
    'text-emphasis-style', '-webkit-text-emphasis', '-webkit-text-emphasis-style')})
LISTED.update({p: lambda v: v != 'normal' for p in ('font-variation-settings', 'font-variant-position')})
LISTED.update({p: lambda v: v != 'visible' for p in ('overflow', 'overflow-x', 'overflow-y', 'overflow-block', 'overflow-inline')})
LISTED.update({p: lambda v: any(far(part) for part in v.split()) for p in (
    'left', 'right', 'top', 'bottom', 'inset', 'inset-block', 'inset-inline', 'inset-block-start', 'inset-block-end',
    'inset-inline-start', 'inset-inline-end', 'margin', 'margin-left', 'margin-right', 'margin-top', 'margin-bottom',
    'margin-block', 'margin-inline', 'margin-block-start', 'margin-block-end', 'margin-inline-start', 'margin-inline-end')})


def listed(prop, value):
    """Whether a declaration of a LISTED property could hide text or change what a reader sees. inherit and the
    defaults hide nothing a parent's own declaration does not; a value the import cannot evaluate counts."""
    if prop != 'all' and (value == 'inherit' or value in UNSUPPORTED_VALUES):   # all: initial and the like reset everything
        return False
    return 'var(' in value or bool(re.search(r'\b(?:calc|min|max|clamp|env|attr)\(', value)) or LISTED[prop](value)


DISPLAY_OUTSIDE = {'block', 'inline', 'run-in'}
DISPLAY_INSIDE = {'flow', 'flow-root', 'table', 'flex', 'grid', 'ruby', 'math'}
DISPLAY_ALONE = {'list-item', 'contents', 'inline-block', 'inline-table', 'inline-flex', 'inline-grid', 'table-row-group',
                 'table-header-group', 'table-footer-group', 'table-row', 'table-cell', 'table-column-group', 'table-column',
                 'table-caption', 'ruby-base', 'ruby-text', 'ruby-base-container', 'ruby-text-container', '-webkit-box',
                 '-webkit-inline-box', '-moz-box', '-moz-inline-box', 'inherit', 'initial', 'unset'}


def shows(value):
    """Whether a display value draws its element: one CSS Display defines other than none (a single keyword, an outside
    and an inside keyword, or list-item with an outside keyword and flow or flow-root), a legacy or internal one, or
    inherit, initial or unset, which draw it as its parent or as inline. A value a reader does not know, it ignores."""
    words = (value or '').lower().split()
    if len(words) == 1:
        return words[0] in DISPLAY_ALONE | DISPLAY_OUTSIDE | DISPLAY_INSIDE
    outside = [w for w in words if w in DISPLAY_OUTSIDE]
    inside = [w for w in words if w in DISPLAY_INSIDE]
    item = words.count('list-item')
    return (1 < len(words) <= 3 and len(outside) <= 1 and len(inside) <= 1 and item <= 1
            and len(outside) + len(inside) + item == len(words)
            and (inside in ([], ['flow'], ['flow-root']) if item else bool(outside and inside)))


def priority(raw):
    """(value as written, important, joined) of a declaration's raw value: at most one top-level final !important, so
    a mark inside a function is part of the value and !important\\ (an escaped space joining the keyword) is none; None
    when anything else makes the declaration invalid. joined: an escaped space joins an identifier in the value."""
    top, spaces = top_level(raw)
    bangs = [i for i, ch in enumerate(top) if ch == '!']
    important = (len(bangs) == 1 and unescape(raw[bangs[0] + 1:]).strip().lower() == 'important'
                 and not any(i > bangs[0] for i in spaces))
    if bangs and not important:
        return None
    cut = bangs[0] if important else len(raw)
    return raw[:cut], important, any(i < cut for i in spaces)


CSS_WIDE = {'initial', 'inherit', 'unset', 'revert', 'revert-layer'}


def scan_value(text, prop, valid):
    """(value, important) of the declaration of prop a rule body or style attribute gives, read as parse_declarations
    reads one: a value valid() accepts, a CSS-wide keyword (initial, inherit, unset, revert, revert-layer) or one
    holding var(), which only the reader can resolve; (None, False) when it gives none a reader takes."""
    found = {}
    for part in split_outside_strings(nested(text)[0], ';'):
        if ':' in part and unescape(part.split(':', 1)[0]).strip().lower() == prop:
            read = priority(part.split(':', 1)[1])
            value = unescape(read[0]).strip().lower() if read and not read[2] else None
            if value and (valid(value) or value in CSS_WIDE or 'var(' in value):
                found[read[1]] = value
    return (found[True], True) if True in found else (found.get(False), False)


def visibility_of(text):
    """(visibility, important) a rule body or style attribute gives (scan_value)."""
    return scan_value(text, 'visibility', lambda v: v in ('visible', 'hidden', 'collapse'))


def display_of(text):
    """(display, important) a rule body or style attribute gives (scan_value), CSS-wide keywords and var() kept."""
    return scan_value(text, 'display', lambda v: v == 'none' or shows(v))


def parse_display(text):
    """(display, important) a rule body or style attribute gives, as parse_declarations reads it; (None, False) when it
    gives none."""
    return winner(parse_declarations(text)[0])


def winner(declared):
    """(display, important) of a set of declarations: an important display ranks above an ordinary one."""
    return (declared['display !important'], True) if 'display !important' in declared else (declared.get('display'), False)


def matters(prop, value):
    """Whether a declaration could change a text's emphasis or visibility; others are layout and never listed. An
    important display (parse_declarations keeps it as 'display !important') counts as a display."""
    prop = prop[:-len(' !important')] if prop.endswith(' !important') else prop
    if prop in LISTED:
        return listed(prop, value)
    if prop in ('font-style', 'font-weight', 'font-variant', 'text-transform', 'vertical-align', 'font'):
        return True
    if prop in ('text-decoration', 'text-decoration-line'):
        return value not in ('none', 'inherit')
    if prop == 'display':
        return value in ('none',) or value in UNSUPPORTED_VALUES or 'var(' in value
    if prop == 'visibility':
        return value in ('hidden', 'collapse') or value in UNSUPPORTED_VALUES or 'var(' in value
    return False


def preprocess(css):
    """CSS text as a reader takes it in (CSS Syntax 3.3): CR LF, a lone CR and FF read as one line feed, NULL and
    surrogates as U+FFFD, so an escape absorbs the CR LF after it as one white space."""
    return re.sub(r'[\x00\ud800-\udfff]', '\ufffd', re.sub(r'\r\n?|\f', '\n', css or ''))


def unescape(text):
    """CSS text with its escapes decoded (CSS Syntax 4.3.7): a backslash and up to six hex digits, a following space
    absorbed, is that code point; a backslash and any other character is that character."""
    def code(m):
        if m.group(1):
            n = int(m.group(1), 16)
            return chr(n) if 0 < n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF else '\ufffd'
        return m.group(2)
    return re.sub(r'\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(.))', code, preprocess(text), flags=re.S)


AT_KEYWORD = re.compile(r'@((?:[\w-]|[^\x00-\x7f]|\\(?:[0-9a-fA-F]{1,6}[ \t\n\r\f]?|[^\n\r\f0-9a-fA-F]))+)')
GROUPS = ('media', 'supports', 'layer', 'container', 'document', 'scope')   # at-rules whose blocks hold style rules


def at_rule(prelude):
    """(name, rest) of an at-rule's prelude, its at-keyword read as CSS reads it: the name in lower case with its escapes
    decoded, ended by the first character no name holds, so @import-theme is no @import, @\\69mport is one and
    @media(min-width: 1px) is a media rule; (None, prelude) when no name follows the @."""
    prelude = preprocess(prelude)
    m = AT_KEYWORD.match(prelude)
    return (unescape(m.group(1)).lower(), prelude[m.end():]) if m else (None, prelude)


def length_percentage(word):
    """Whether a word is a CSS length in a known unit, a percentage, or zero."""
    m = re.fullmatch(rf'({CSS_NUMBER})([a-z]+|%)?', word)
    return bool(m) and (m.group(2) == '%' or m.group(2) in LENGTH_UNITS or m.group(2) is None and float(m.group(1)) == 0)


def kinds(words, groups):
    """The group each word belongs to (groups: name to its words), None for a word in none."""
    return [next((name for name, members in groups.items() if word in members), None) for word in words]


def value_check(prop, value):
    """Whether a reader takes a value of a supported property by its CSS grammar: True; False for one it drops as
    invalid, so the declaration before it stands; None for one the import cannot judge, such as a function, which is
    listed and never applied. value: unescaped, lower case, its priority taken off."""
    words = value.split()
    if value == 'inherit':
        return True
    if '(' in value:   # calc(), a colour function, an alternate: beyond what the import weighs
        return None
    if prop == 'font-style':
        m = re.fullmatch(rf'oblique\s+({CSS_NUMBER})(deg|grad|rad|turn)', value)
        return value in ('normal', 'italic', 'oblique') or bool(m) and -90 <= float(m.group(1)) * ANGLE_DEGREES[m.group(2)] <= 90
    if prop == 'font-weight':
        return value in ('normal', 'bold', 'bolder', 'lighter') or bool(re.fullmatch(CSS_NUMBER, value)) and 1 <= float(value) <= 1000
    if prop == 'font-variant':
        found = kinds(words, FONT_VARIANT)
        return value in ('normal', 'none') or None not in found and len(set(found)) == len(found)
    if prop == 'text-transform':
        found = kinds(words, {'case': {'capitalize', 'uppercase', 'lowercase'}, 'width': {'full-width'}, 'kana': {'full-size-kana'}})
        return value in ('none', 'math-auto') or None not in found and len(set(found)) == len(found)
    if prop == 'text-decoration-line':
        return (value in ('none', 'spelling-error', 'grammar-error')
                or all(w in DECORATION['line'] for w in words) and len(set(words)) == len(words))
    if prop == 'text-decoration':
        if value == 'none':
            return True
        groups = {**DECORATION, 'none': {'none'}, 'colour': NAMED_COLORS, 'thickness': {'auto', 'from-font'}}
        found = [g if g or not re.fullmatch(r'#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})', w) else 'colour'
                 for w, g in zip(words, kinds(words, groups))]
        found = [g if g or not length_percentage(w) else 'thickness' for w, g in zip(words, found)]
        lines = [w for w, g in zip(words, found) if g == 'line']
        if None in found:
            return None   # a word it does not know may be a colour it does not list
        return (len(set(lines)) == len(lines) and not ('none' in found and lines)
                and all(found.count(g) <= 1 for g in ('style', 'colour', 'thickness', 'none')))
    if prop == 'vertical-align':
        if value in VERTICAL:
            return True
        m = re.fullmatch(rf'({CSS_NUMBER})([a-z]+|%)?', value)
        return (None if m and m.group(2) and m.group(2) != '%' and m.group(2) not in LENGTH_UNITS
                else bool(m) and (m.group(2) is not None or float(m.group(1)) == 0))
    return True


def slanted(value):
    """Whether a valid font-style draws its text slanted: italic, oblique, or oblique at an angle other than zero."""
    m = re.fullmatch(rf'oblique\s+({CSS_NUMBER})(deg|grad|rad|turn)', value or '')
    return value in ('italic', 'oblique') or bool(m) and float(m.group(1)) != 0


def parse_declarations(text):
    """(supported declarations, constructs outside the subset) of one rule body or style attribute, its comments
    removed and its escapes decoded as a reader removes and decodes them, a nested rule left out (nested)."""
    found, outside = {}, []
    for part in split_outside_strings(nested(text)[0], ';'):
        if ':' not in part:
            continue
        prop, raw = part.split(':', 1)
        prop, value = unescape(prop).strip().lower(), unescape(raw).strip()
        if prop == 'content' and value.lower() not in ('none', 'normal', '""', "''"):
            outside.append(f'content: {value}')   # generated text a reader sees, which neither reading carries
            continue
        if prop not in PROPERTIES and prop not in LISTED:
            continue
        read = priority(raw)
        if read is None:   # anything but one top-level final !important makes the declaration invalid, so a reader drops it
            continue
        written, important, joined = read
        value = unescape(written).strip().lower()
        if joined:   # an escaped space joins an identifier no keyword matches
            outside.append(f'{prop}: {written.strip()}' + (' !important' if important else ''))   # listed as it is written, never applied
            continue
        state = value_check(prop, value) if prop in CHECKED and value not in UNSUPPORTED_VALUES and 'var(' not in value else True
        if state is False:   # a value no reader takes is dropped, as a reader drops it: the one before stands
            continue
        if state is None:   # one the import cannot judge is listed as it is, never applied
            outside.append(f'{prop}: {value}' + (' !important' if important else ''))
            continue
        if prop in LISTED:   # never read: listed wherever it could hide text or change what shows
            if listed(prop, value):
                outside.append(f'{prop}: {value}' + (' !important' if important else ''))
            continue
        if prop == 'display' and value not in UNSUPPORTED_VALUES and 'var(' not in value:
            if value == 'none' or shows(value):   # a value no reader knows is dropped, as a reader drops it: the one before stands
                found['display !important' if important else 'display'] = value   # an important one outranks the rest (winner)
            continue
        if important or value in UNSUPPORTED_VALUES or 'var(' in value or prop in ('visibility', 'font'):
            if matters(prop, value):
                outside.append(f'{prop}: {value}' + (' !important' if important else ''))
            continue
        found['text-decoration' if prop == 'text-decoration-line' else prop] = value
    return found, outside


def skip_string(css, i):
    """The index just past the quoted string that opens at css[i], its backslash escapes kept inside it; a line break
    it does not escape ends it unclosed, as CSS ends a bad string, and is left to what follows."""
    j = i + 1
    while j < len(css) and css[j] != css[i]:
        if css[j] in '\n\r\f':
            return j
        j += 2 if css[j] == '\\' else 1
    return j + 1


ESCAPE = re.compile(r'\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(.))', re.S)


def top_level(raw):
    """(masked, spaces) of a declaration value as written: the same text with what escapes, strings and every nested
    function or block hold blanked, so only its top-level marks show, and where a top-level escape stands for white space
    (part of an identifier, never a separator)."""
    out, spaces, i, depth = [], [], 0, 0
    while i < len(raw):
        ch = raw[i]
        if ch == '\\':
            m = ESCAPE.match(raw, i)
            end = m.end() if m else i + 1
            decoded = (chr(int(m.group(1), 16)) if m.group(1) and int(m.group(1), 16) <= 0x10FFFF else m.group(2) or '') if m else ''
            if depth == 0 and decoded in (' ', '\t', '\n', '\r', '\f'):
                spaces.append(i)
            out.append('_' * (end - i))
            i = end
        elif ch in '"\'':
            j = skip_string(raw, i)
            out.append('_' * (j - i))
            i = j
        else:
            if ch in '([{':
                depth += 1
            visible = depth == 0 or depth == 1 and ch in '([{'
            if ch in ')]}' and depth:
                depth -= 1
                visible = depth == 0
            out.append(ch if visible else '_')
            i += 1
    return ''.join(out), spaces


def strip_comments(css):
    """CSS without its comments, preprocessed; a /* inside a quoted string, such as generated text, is text."""
    css, out, i = preprocess(css), [], 0
    while i < len(css):
        if css[i] == '\\':   # an escaped character opens no comment
            out.append(css[i:i + 2])
            i += 2
        elif css[i] in '"\'':
            j = skip_string(css, i)
            out.append(css[i:j])
            i = j
        elif css.startswith('/*', i):
            end = css.find('*/', i + 2)
            j = len(css) if end < 0 else end + 2
            name = re.compile(r'[\w\\-]|[^\x00-\x7f]')
            if out and name.match(out[-1][-1:] or ' ') and name.match(css[j:j + 1] or ' '):
                out.append(' ')   # a comment parts two tokens (bl/**/ock is not block); between others it simply goes
            i = j
        else:
            out.append(css[i])
            i += 1
    return ''.join(out)


def split_outside_strings(text, mark):
    """text split at each mark outside quoted strings and parentheses, so url(data:...;base64,...) or :is(a, b) stays
    whole."""
    parts, start, i, depth = [], 0, 0, 0
    while i < len(text):
        if text[i] == '\\':   # an escaped character is never structure
            i += 2
            continue
        if text[i] in '"\'':
            i = skip_string(text, i)
            continue
        if text[i] == '(':
            depth += 1
        elif text[i] == ')' and depth:
            depth -= 1
        elif text[i] == mark and not depth:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    return parts + [text[start:]]


def nested(body):
    """(declarations, rules) of a rule body as CSS Nesting reads it: the text of its own declarations, comments removed,
    and each rule nested in it as (prelude, body). A reader without nesting drops a nested style rule together with
    what follows it up to the next semicolon, so that stretch is a rule too, with the prelude & (the rule itself); it
    reads past a nested at-rule as an at-rule."""
    text = strip_comments(body or '')
    own, rules, start, i, n, depth, after = [], [], 0, 0, len(text), 0, False
    while i < n:
        if text[i] == '\\':
            i += 2
            continue
        if text[i] in '"\'':
            i = skip_string(text, i)
            continue
        if text[i] in '()':
            depth = depth + 1 if text[i] == '(' else max(depth - 1, 0)
        elif not depth and text[i] == ';':
            if after and text[start:i].strip():
                rules.append(('&', text[start:i]))
            else:
                own.append(text[start:i + 1])
            start, after = i + 1, False
        elif not depth and text[i] == '{':
            j, level = i + 1, 1
            while j < n and level:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] in '"\'':
                    j = skip_string(text, j)
                    continue
                level += {'{': 1, '}': -1}.get(text[j], 0)
                j += 1
            rules.append((text[start:i].strip(), text[i + 1:j - 1] if not level else text[i + 1:j]))
            after = not text[start:i].strip().startswith('@')
            start = i = j
            continue
        i += 1
    if after and text[start:].strip():
        rules.append(('&', text[start:]))
    else:
        own.append(text[start:])
    return ''.join(own), rules


def nest(parent, prelude, body):
    """A rule nested in a style rule as the top-level CSS it stands for: each nested selector relative to each of the
    parent's (& for the parent, a descendant step otherwise), a nested group as the parent's own declarations; '' for
    a group that never holds, such as print, or any other at-rule."""
    if prelude.startswith('@'):
        return '' if group_holds(prelude) is False else f'{parent} {{{body}}}'
    if prelude.strip() == '&':
        return f'{parent} {{{body}}}'
    if selector_list(prelude) is None:
        return ''
    selectors = [c.strip().replace('&', f':is({q.strip()})') if '&' in c else f'{q.strip()} {c.strip()}'
                 for c in split_outside_strings(prelude, ',') for q in split_outside_strings(parent, ',')]
    return f'{", ".join(selectors)} {{{body}}}'


def statements(css):
    """Top-level CSS statements as (prelude, body or None), braces matched outside quoted strings, comments removed;
    the end of the sheet closes a block or a statement left open, as CSS closes them."""
    css = strip_comments(css or '')
    out, start, i, n, depth = [], 0, 0, len(css), 0
    while i < n:
        if css[i] == '\\':   # an escaped brace or semicolon, as in .a\{b, is part of its token
            i += 2
            continue
        if css[i] in '"\'':
            i = skip_string(css, i)
            continue
        if css[i] in '()':   # a semicolon or brace inside url(...) belongs to it
            depth = depth + 1 if css[i] == '(' else max(depth - 1, 0)
            i += 1
            continue
        if depth:
            i += 1
            continue
        if css[i] == ';' and css[start:i].strip().startswith('@'):
            out.append((css[start:i].strip(), None))   # @import, @charset, @namespace
            start = i = i + 1
            continue
        if css[i] == '{':
            depth, j = 1, i + 1
            while j < n and depth:
                if css[j] == '\\':
                    j += 2
                    continue
                if css[j] in '"\'':
                    j = skip_string(css, j)
                    continue
                depth += {'{': 1, '}': -1}.get(css[j], 0)
                j += 1
            out.append((css[start:i].strip(), css[i + 1:j - 1] if not depth else css[i + 1:j]))
            start = i = j
            continue
        i += 1
    if css[start:].strip().startswith('@'):   # @import "a.css" with no semicolon before the end
        out.append((css[start:].strip(), None))
    return out


class Outside(str):
    """An entry of parse_stylesheet's outside list: its text as listed, the properties it sets (properties; '*' for an
    @import, which may set any), whether a condition it stands under never holds on a reader's screen (never), and
    whether its rule styles only pseudo-element boxes such as ::before (boxes), so a reader of one property can tell
    which entries concern the text it reads."""
    def __new__(cls, text, properties=(), never=False, boxes=False):
        entry = super().__new__(cls, text)
        entry.properties, entry.never, entry.boxes = frozenset(properties), never, boxes
        return entry


GENERATED_BOX = re.compile(r'(?i)::?(?:before|after)\b|::marker\b')


def boxes_only(prelude):
    """Whether every selector of a rule names a pseudo-element that generates a box of its own (::before, ::after,
    ::marker), outside quotes and attribute tests, so it styles generated content, never an element's text;
    ::first-line and ::first-letter style the text itself."""
    members = [re.sub(r'\[(?:[^\]"\']|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')*\]', '', m)
               for m in split_outside_strings(prelude or '', ',') if m.strip()]
    return bool(members) and all(GENERATED_BOX.search(m) for m in members)


def group_holds(prelude):
    """Whether a group at-rule's condition holds on a reader's screen: True; False for one that never does, such as
    print or a failed @supports, and for any other at-rule; None for one the import cannot weigh."""
    name, rest = at_rule(prelude)
    return media_applies(rest) if name == 'media' else supports(rest) if name == 'supports' else None if name in GROUPS else False


def set_properties(declarations, bad):
    """The properties a rule body sets that matter (matters) or that the subset could not read, without !important."""
    names = {k[:-len(' !important')] if k.endswith(' !important') else k for k, v in declarations.items() if matters(k, v)}
    return names | {b.split(':', 1)[0].strip().lower() for b in bad}


def parse_stylesheet(css):
    """(rules, outside): rules are (specificity, order, element, class, declarations) for supported selectors;
    outside lists every selector or construct beyond the subset that sets a supported property (Outside entries)."""
    rules, outside, order = [], [], 0

    def conditional(chain, body):   # rules under conditions the import cannot settle, nested groups included
        for inner_prelude, inner_body in statements(body):
            if inner_prelude.startswith('@') and inner_body is not None:
                conditional(chain + [inner_prelude], inner_body)
                continue
            if not inner_prelude.startswith('@') and selector_list(inner_prelude) is None:   # a void list, which CSS drops
                continue
            declarations, bad = parse_declarations(inner_body or '')
            if bad or any(matters(k, v) for k, v in declarations.items()):
                outside.append(Outside(' { '.join(chain + [inner_prelude]) + ' }' * len(chain), set_properties(declarations, bad),
                                       any(group_holds(c) is False for c in chain if c.startswith('@')), boxes_only(inner_prelude)))
            nested_rules(chain + [inner_prelude], inner_body or '')

    def nested_rules(chain, body):   # rules nested in a style rule (CSS Nesting), which the import cannot settle either
        for inner_prelude, inner_body in nested(body)[1]:
            if not inner_prelude.startswith('@') and inner_prelude != '&' and selector_list(inner_prelude) is None:
                continue
            declarations, bad = parse_declarations(inner_body)
            if bad or any(matters(k, v) for k, v in declarations.items()):
                outside.append(Outside(' { '.join(chain + [inner_prelude]) + ' }' * len(chain), set_properties(declarations, bad),
                                       any(group_holds(c) is False for c in chain + [inner_prelude] if c.startswith('@')),
                                       boxes_only(inner_prelude) or any(boxes_only(c) for c in chain if not c.startswith('@'))))
            nested_rules(chain + [inner_prelude], inner_body)

    for prelude, body in ((pr, bo) for sheet in sheets_of(css) for pr, bo in [(None, sheet)] + statements(sheet)):
        if prelude is None:   # a sheet starts: its namespaces are its own
            state = (frozenset(), True)
            continue
        state = declared(state, prelude, body)
        prefixes = state[0]
        if prelude.startswith('@'):
            if body is None:
                if at_rule(prelude)[0] == 'import':
                    outside.append(Outside(prelude, {'*'}))
                continue
            conditional([prelude], body)
            continue
        listed = selector_list(prelude, prefixes)
        if listed is None:   # an empty selector voids the list, so CSS drops the whole rule
            continue
        selectors, readable = listed
        declarations, bad = parse_declarations(body or '')
        outside += [Outside(f'{prelude} {{ {b} }}', set_properties({}, [b]), boxes=boxes_only(prelude)) for b in bad]
        nested_rules([prelude], body or '')
        if not declarations:
            continue
        for selector in selectors if readable else [prelude]:   # a list it cannot read is applied nowhere, listed whole
            m = SELECTOR.match(selector.lower()) if readable else None
            element = m.group(1) if m else None
            cls = selector.split('.', 1)[1] if m and m.group(2) else None
            if not m or (element and element not in SUPPORTED_ELEMENTS) or (not element and not cls):
                relevant = {k: v for k, v in declarations.items() if matters(k, v)}
                if relevant:
                    outside.append(Outside(f'{selector} {{ ' + '; '.join(f'{k[:-11]}: {v} !important' if k.endswith(' !important') else f'{k}: {v}'
                                                                        for k, v in relevant.items()) + ' }', set_properties(relevant, []),
                                           boxes=boxes_only(selector)))
                continue
            order += 1
            rules.append((2 if element and cls else 1 if cls else 0, order, element, cls, declarations))
    return rules, outside


@functools.lru_cache(maxsize=4096)
def steps(selector):
    """(compounds, combinators) of a selector, left to right: each compound as the (element, classes, ids) it requires,
    and between each two the combinator, ' ' for a descendant, '>', '+' or '~'. Pseudo-classes and attribute tests are
    dropped, and a compound the import cannot read requires nothing, so a test built on them errs toward matching."""
    s = re.sub(r'\[[^\]]*\]|::?[\w-]+(?:\([^()]*\))?', '', selector).strip()
    parts = re.split(r'\s*([>+~])\s*|\s+', s) if s else ['']
    compounds = []
    for text in parts[0::2]:
        m = re.fullmatch(r'(\*|[\w-]+)?(?:\|([\w-]+|\*))?((?:[.#][\w-]+)*)', text or '')
        name = (m.group(2) or m.group(1) or '*').lower() if m else '*'
        compounds.append((None if name == '*' else name, frozenset(re.findall(r'\.([\w-]+)', m.group(3))) if m else frozenset(),
                          frozenset(re.findall(r'#([\w-]+)', m.group(3))) if m else frozenset()))
    return tuple(compounds), tuple(c or ' ' for c in parts[1::2])   # cached: every element asks about the same selectors


def pseudo_attributes(data):
    """The pseudo-attributes of a processing instruction's data, such as href and type."""
    return {m.group(1).lower(): m.group(3) if m.group(3) is not None else m.group(4)
            for m in re.finditer(r'([\w-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', data)}


class _Root(Exception):
    pass


def xml_stylesheets(text):
    """The xml-stylesheet processing instructions before a document's root element, each as its pseudo-attributes:
    stylesheets a reader applies besides link and style elements, which the element tree drops. Read as an XML parser
    reads them, so a comment never hides or forges one; text no parser can read is scanned with its comments removed."""
    import xml.parsers.expat as expat
    found = []

    def instruction(target, data):
        if target == 'xml-stylesheet':
            found.append(pseudo_attributes(data))

    def root(*_):
        raise _Root()   # instructions after the root element name no stylesheet

    parser = expat.ParserCreate(encoding='utf-8')   # the text is decoded already; its declaration names the bytes it came from
    parser.ProcessingInstructionHandler, parser.StartElementHandler = instruction, root
    try:
        parser.Parse(text.encode('utf-8'), True)
    except _Root:
        return found
    except expat.ExpatError:
        prolog = re.sub(r'<!--.*?(?:-->|$)|<!\[CDATA\[.*?(?:\]\]>|$)', '', text, flags=re.S)
        start = re.search(r'<[A-Za-z_]', prolog)
        return [pseudo_attributes(pi) for pi in re.findall(r'<\?xml-stylesheet\b(.*?)\?>', prolog[:start.start()] if start else prolog, re.S)]
    return found


def media_applies(media):
    """Whether a stylesheet's media list holds on a reader's screen: True for none, all or screen; False when it names
    only other media, such as print or speech; None for a query with conditions."""
    verdicts = set()
    for query in (media or '').lower().split(','):
        words = query.split()
        if words[:1] == ['only']:
            words = words[1:]
        if not words:
            continue
        if len(words) == 1 and words[0] in ('all', 'screen'):
            verdicts.add(True)
        elif len(words) == 1 and re.fullmatch(r'[a-z][a-z-]*', words[0]):
            verdicts.add(False)
        else:
            verdicts.add(None)
    return True if not verdicts or True in verdicts else (False if verdicts == {False} else None)


def css_references(text):
    """Every address a CSS text names: url() and src() arguments, the strings in image-set(), and @import targets.
    Function names and at-keywords match in any case and with their escapes decoded, as CSS reads them, an @import's
    string after a space, a comment or nothing; the address keeps its own spelling."""
    text = unescape(text)
    found = [m.group(1).strip().strip('\'"') for m in re.finditer(r'(?i)\b(?:url|src)\(\s*([^)]*)\)', text)]
    for m in re.finditer(r'(?i)image-set\(([^)]*)\)', text):
        found += re.findall(r'["\']([^"\']+)["\']', m.group(1))
    return found + [m.group(2) for m in re.finditer(r'(?i)@import(?:\s|/\*[\s\S]*?\*/)*(["\'])(.*?)\1', text)]


def fits(compound, element):
    """Whether an element has the name, classes and id a compound requires."""
    name, classes, ids = compound
    return ((name is None or local(element.tag) == name) and classes <= set((element.get('class') or '').split())
            and ids <= {element.get('id')})


def reaches(selector, element, ancestors=None):
    """Whether a selector can match the element: its subject by the element's name, classes and id, and, where the
    element's ancestors are given (nearest first), each descendant or child step by them; a sibling step, which would
    need the siblings, is taken to hold. Without ancestors only the subject counts, so the test errs toward matching."""
    compounds, combinators = steps(selector)
    if not fits(compounds[-1], element):
        return False
    if ancestors is None:
        return True
    ancestors, known = list(ancestors), {}

    def holds(i, at):   # compounds[:i] can stand above an element whose ancestors are ancestors[at:]
        if (i, at) not in known:   # each state once, however many ways lead to it
            known[i, at] = step_holds(i, at)
        return known[i, at]

    def step_holds(i, at):
        if i == 0:
            return True
        step, compound = combinators[i - 1], compounds[i - 1]
        if step in ('+', '~'):   # a sibling shares the ancestors
            return holds(i - 1, at)
        if step == '>':
            return at < len(ancestors) and fits(compound, ancestors[at]) and holds(i - 1, at + 1)
        return any(fits(compound, ancestors[j]) and holds(i - 1, j + 1) for j in range(at, len(ancestors)))
    return holds(len(compounds) - 1, 0)


def rule_list(css):
    """(selectors, body) of every style rule, those inside the groups that hold style rules (GROUPS: @media, @supports,
    @layer, @scope and the like) included; css: one sheet or a list (sheets_of)."""
    for prelude, body in (pair for sheet in sheets_of(css) for pair in statements(sheet)):
        if body is None:
            continue
        if prelude.startswith('@'):
            if at_rule(prelude)[0] in GROUPS:
                yield from rule_list(body)
            continue
        if selector_list(prelude) is None:   # a void selector list: CSS drops the rule
            continue
        yield prelude, body
        for inner_prelude, inner_body in nested(body)[1]:   # rules nested in it (CSS Nesting)
            yield from rule_list(nest(prelude, inner_prelude, inner_body))


def resolve_weight(value, inherited):
    """A numeric font weight by the CSS Fonts table; None for a value outside the subset."""
    if value == 'normal':
        return 400.0
    if value == 'bold':
        return 700.0
    if value == 'inherit':
        return inherited
    if value == 'bolder':
        return 400.0 if inherited < 350 else 700.0 if inherited < 550 else 900.0 if inherited < 900 else inherited
    if value == 'lighter':
        return inherited if inherited < 100 else 100.0 if inherited < 550 else 400.0 if inherited < 750 else 700.0
    try:
        number = float(value)
    except ValueError:
        return None
    return number if 1 <= number <= 1000 else None


class Styler:
    """The subset's cascade and per-property semantics for one document."""

    def __init__(self, rules, css=''):
        self.rules = sorted(rules, key=lambda r: (r[0], r[1]))
        self.displays = [(selector.strip(), value, important) for prelude, body in rule_list(css)   # every rule that sets display, any selector
                         for value, important in [parse_display(body)] if value for selector in split_outside_strings(prelude, ',')
                         if not pseudo_element(selector)]   # ::before and the like style a box of their own, never the element
        self.parents = {}   # each element's parent, in the trees bound to this styler (a root's is None)
        self.scan = list(scan_rules(css))   # every display and visibility rule, for a reader that asks no decision
        self.unresolved = set(imports(css))   # rules such a reader could not settle that might change what shows: an @import
        # it does not follow is one, wherever it stands, inside a group a sheet's own media condition makes too

    def bind(self, root):
        """Learn the parents of root's elements, so a rule's descendant and child steps can be tested."""
        self.parents.setdefault(root, None)
        self.parents.update((child, parent) for parent in root.iter() for child in parent)

    def ancestors(self, element):
        """The element's ancestors, nearest first; None when its tree was never bound."""
        if element not in self.parents:
            return None
        out, e = [], self.parents[element]
        while e is not None:
            out.append(e)
            e = self.parents.get(e)
        return out

    def declared(self, element):
        tag, classes = local(element.tag), set((element.get('class') or '').split())
        result = {}
        for _spec, _order, rule_element, rule_class, declarations in self.rules:
            if (rule_element is None or rule_element == tag) and (rule_class is None or rule_class in classes):
                result.update(declarations)
        inline, outside = parse_declarations(element.get('style'))
        result.update(inline)   # an inline declaration ranks above any selector
        return result, outside   # an inline important display outranks a rule's (winner)

    def effective(self, element, parent):
        """(flags, constructs outside the subset) for an element below parent's flags."""
        tag = local(element.tag)
        flags = dict(parent)
        problems = []
        if tag in ('em', 'i', 'cite', 'dfn', 'var'):
            flags['italic'] = True
        if tag in ('strong', 'b'):
            flags['weight'] = resolve_weight('bolder', parent['weight'])
        if tag in ('u', 'ins'):
            flags['underline'] = True
        if tag in ('s', 'strike', 'del'):
            flags['strike'] = True
        if tag == 'sup':
            flags['sup'] = True
        if tag == 'sub':
            flags['sub'] = True
        declared, outside = self.declared(element)
        problems += outside
        # explicit inherit takes the parent's computed value, over the element's own default (CSS Cascade 7.3.2)
        v = declared.get('font-style')
        if v:
            if slanted(v):
                flags['italic'] = True
            elif v == 'normal' or v.startswith('oblique'):   # oblique 0deg stands upright
                flags['italic'] = False
            elif v == 'inherit':
                flags['italic'] = parent['italic']
            else:
                problems.append(f'font-style: {v}')
        if 'font-weight' in declared:
            weight = resolve_weight(declared['font-weight'], parent['weight'])
            if weight is None:
                problems.append(f'font-weight: {declared["font-weight"]}')
            else:
                flags['weight'] = weight
        v = declared.get('font-variant')
        if v:
            if {'small-caps', 'all-small-caps'} & set(v.split()):
                flags['smallcaps'] = True
            elif v == 'normal':
                flags['smallcaps'] = False
            elif v == 'inherit':
                flags['smallcaps'] = parent['smallcaps']
            else:
                problems.append(f'font-variant: {v}')
        v = declared.get('text-transform')
        if v == 'uppercase':
            flags['upper'] = True
        elif v == 'none':
            flags['upper'] = False
        elif v == 'inherit':
            flags['upper'] = parent['upper']
        elif v:   # lowercase, capitalize and the rest change what a reader sees, and the reading carries none of them
            problems.append(f'text-transform: {v}')
        v = declared.get('text-decoration', '')
        if 'underline' in v.split():   # decorations propagate: a descendant cannot remove an ancestor's line
            flags['underline'] = True
        if 'line-through' in v.split():
            flags['strike'] = True
        v = declared.get('vertical-align')
        if v == 'super':
            flags['sup'] = True
        elif v == 'sub':
            flags['sub'] = True
        elif v in ('baseline', 'inherit'):   # the element's own raise or drop goes; a raised parent still carries it
            flags['sup'], flags['sub'] = parent['sup'], parent['sub']
        hidden, drawing = self.hides(element, declared=declared)
        problems += drawing
        if (hidden or until_found(element)
                or (element.get('aria-hidden') or '').strip().lower() == 'true'   # as the voice reader judges hidden HTML
                or tag == 'template'):
            flags['hidden'] = True   # not inherited, but it hides the whole subtree
        return flags, problems

    def hides(self, element, above=None, declared=None):
        """(hidden, rules listed) by display, the one judgement the import and the voice reader share: the supported
        cascade's display (winner), an element a reader does not draw by default (undrawn_by_default) drawn only by a
        display, and a rule beyond the subset that can reach it (above: its ancestors, nearest first; by default the bound
        tree's) drawing it where the cascade gives no display, or, when important, over the cascade's ordinary none."""
        display, important = winner(declared if declared is not None else self.declared(element)[0])
        undrawn = undrawn_by_default(element)
        shown = shows(display)   # a stylesheet can draw a closed dialog, never a template
        problems = []
        if not shown and (undrawn or display == 'none' and not important):
            above = self.ancestors(element) if above is None else above
            drawing = [(s, v, imp) for s, v, imp in self.displays if shows(v) and (undrawn or imp) and reaches(s, element, above)]
            if drawing:   # a rule beyond the subset may draw it: the text is kept, and the rule asked about
                problems = [f'{s} {{ display: {v}' + (' !important' if imp else '') + ' }' for s, v, imp in drawing]
                shown = display != 'none' or any(imp for _, _, imp in drawing)   # an important rule beats the cascade's none
            if not shown and display == 'none' and not important:   # so does an ordinary one that outranks it where the scan's
                value, selector, rival = self.certain_display(element, above)   # certain cascade tells (#secret over .secret;
                if selector and value != 'none':   # revert may give back what a reader draws), or one it cannot settle
                    problems.append(f'{selector} {{ display: {value} }}')   # that would win if it held
                    shown = True
                elif rival:
                    problems.append((f'style="display: {rival[1]}"' if rival[0] is None else f'{rival[0]} {{ display: {rival[1]} }}')
                                    + ' (the import cannot tell whether it applies)')
                    shown = True
        return not shown and (display == 'none' or undrawn), problems

    def certain_display(self, element, above=None):
        """(display, selector, rival) of the element among its own style and the rules a scan can tell reach it, by
        importance, the style attribute, specificity and order: the winning display and its selector (None when its own
        style wins or nothing sets one), and rival, the first rule the scan cannot settle (a condition, a query, a
        selector test, a nested rule, var()) that can reach the element with a display other than none and would win if
        it held, as (selector, value), its selector None for the element's own style; None when there is none."""
        value, important = display_of(element.get('style'))
        own = (important, 1, (0, 0, 0), 0)
        best = (own, value, None) if value is not None and 'var(' not in value else None
        unsettled = [(own, value, None)] if value is not None and 'var(' in value else []
        for order, (selector, kind, v, imp, weight, sure) in enumerate(self.scan):
            key = (imp, 0, weight, order)
            if kind != 'display':
                continue
            if sure and (best is None or key > best[0]) and reaches(selector, element, above):
                best = (key, v, selector)
            elif not sure and v != 'none':
                unsettled.append((key, v, selector))
        rival = next(((s, v) for k, v, s in unsettled if (best is None or k > best[0]) and (s is None or reaches(s, element, above))),
                     None)
        return (best[1], best[2], rival) if best else (None, None, rival)

    def scan_hides(self, element, above=None):
        """Whether a reader that asks no decision, such as an EPUB scan, takes the element and all it holds as hidden: the
        winning display among the rules it can tell reach it (above: its ancestors, nearest first) and its own style, by
        importance, then the style attribute, then specificity, then order; an element a reader does not draw by default
        (undrawn_by_default) stays hidden unless a display draws it."""
        undrawn = undrawn_by_default(element)

        def hidden_by(value):   # none hides; revert goes back to the reader's own stylesheet; initial, unset and inherit draw
            return undrawn if value is None or value in ('revert', 'revert-layer') else value == 'none'
        return hidden_by(self._scan_winner(element, above, 'display', display_of(element.get('style')), hidden_by))

    def scan_visible(self, element, above=None, inherited=True):
        """Whether such a reader takes the element's own text as visible: the winning visibility, chosen as scan_hides
        chooses a display, or the visibility its parent passes down (inherited). A descendant can be visible again."""
        def hidden_by(value):   # initial is visible; inherit, unset and revert take the parent's
            return value in ('hidden', 'collapse') if value in ('visible', 'initial', 'hidden', 'collapse') else not inherited
        return not hidden_by(self._scan_winner(element, above, 'visibility', visibility_of(element.get('style')), hidden_by))

    def _scan_winner(self, element, above, kind, own, hidden_by):
        """The winning value of kind for a scan: only rules it can tell reach the element count. A rule it cannot settle
        (an attribute test, a pseudo-class, a sibling step, a condition it cannot weigh, a value holding var()) is never
        applied; where it could hide what shows, or show what is hidden (hidden_by), it goes to unresolved, so the
        reading is reported as partial."""
        value, important = own
        textless = local(element.tag) in TEXTLESS
        best = None
        if value is not None and 'var(' in value:   # only the reader resolves it
            if not textless:
                self.unresolved.add(f'style attribute: {kind}: {value}')
        elif value is not None:
            best = ((important, 1, (0, 0, 0), 0), value)
        unsettled = []
        for order, (selector, k, v, imp, weight, certain) in enumerate(self.scan):
            if k != kind:
                continue
            if not certain:
                unsettled.append((selector, v))
                continue
            key = (imp, 0, weight, order)
            if (best is None or key > best[0]) and reaches(selector, element, above):
                best = (key, v)
        result = best[1] if best else None
        now = hidden_by(result)
        for selector, v in unsettled if not textless else ():
            if ('var(' in v or hidden_by(v) != now) and reaches(selector, element, above):
                self.unresolved.add(selector)
        return result


PSEUDO = re.compile(r'(?i)::|:(?:before|after|first-line|first-letter)\b')


def pseudo_element(selector):
    """Whether a selector names a pseudo-element (::before, :after and the like), outside quotes and attribute tests,
    so [data-x=\"::\"] is none."""
    return bool(PSEUDO.search(re.sub(r'\[(?:[^\]"\']|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')*\]', '', selector)))
TEXTLESS = {'br', 'hr', 'wbr', 'img', 'image', 'col', 'area', 'source', 'track', 'meta', 'link', 'base', 'input', 'param', 'embed'}


def specificity(selector):
    """(ids, classes, types) of a selector, near enough for a cascade: :where() counts nothing, :is(), :not() and
    :has() count as their argument, attribute tests and pseudo-classes as classes, pseudo-elements as types."""
    s = re.sub(r'(?i):where\([^()]*\)', '', selector)
    s = re.sub(r'(?i):(?:is|not|has|matches)\(([^()]*)\)', r' \1 ', s)
    ids = len(re.findall(r'#[\w-]+', s))
    classes = len(re.findall(r'\.[\w-]+|\[[^\]]*\]|(?<!:):(?!:)[\w-]+', s))
    types = len(re.findall(r'(?:^|[\s>+~(,])\s*([a-zA-Z][\w-]*)', s)) + len(re.findall(r'::[\w-]+', s))
    return ids, classes, types


def certain(selector):
    """Whether reaches() can tell for sure whether a selector matches an element whose ancestors it knows: only names,
    classes and ids joined by descendant or child steps."""
    return not re.search(r'[\[:+~\\]', selector) and all(
        re.fullmatch(r'(\*|[\w-]+)?((?:[.#][\w-]+)*)', part) for part in re.split(r'\s*>\s*|\s+', selector.strip()) if part)


ESC = r'\\(?:[0-9a-fA-F]{1,6}[ \t\n]?|[^\n0-9a-fA-F])'
NAME = r'(?:[\w-]|[^\x00-\x7f])'
IDENT = rf'(?:--{NAME}*|-?(?:[A-Za-z_]|[^\x00-\x7f]){NAME}*)'
TYPE = rf'(?:(?:{IDENT}|\*)?\|)?(?:{IDENT}|\*)'
ATTRIBUTE = rf'\[\s*(?:(?:{IDENT}|\*)?\|)?{IDENT}\s*(?:[~|^$*]?=\s*(?:{IDENT}|"")\s*(?:[iIsS]\s*)?)?\]'
SIMPLE = rf'(?:#{IDENT}|\.{IDENT}|{ATTRIBUTE})'
COMPOUND = rf'(?:{TYPE}{SIMPLE}*|{SIMPLE}+)'
COMPLEX = re.compile(rf'{COMPOUND}(?:\s*[>+~]\s*{COMPOUND}|\s+{COMPOUND})*')
PSEUDO_STEP = re.compile(rf'(::?)({IDENT})(?:\(((?:[^()]|\([^()]*\))*)\))?')
EVERY_READER = {'root', 'first-child', 'last-child', 'only-child', 'first-of-type', 'last-of-type', 'only-of-type', 'empty', 'link',
                'visited', 'active', 'hover', 'focus', 'target', 'enabled', 'disabled', 'checked'}   # CSS Selectors 3
NTH = {'nth-child', 'nth-last-child', 'nth-of-type', 'nth-last-of-type'}
OLD_ELEMENTS = {'before', 'after', 'first-line', 'first-letter'}   # the pseudo-elements of CSS 2


def sheets_of(css):
    """The stylesheets css holds, each read alone: the sheets of a list, as stylesheets gives them, or css itself."""
    return list(css) if isinstance(css, (list, tuple)) else [css or '']


STRING = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\''
URL = rf'url\(\s*(?:{STRING}|(?:[^\s"\'()\\\x00-\x08\x0b\x0e-\x1f\x7f]|\\[^\n])*)\s*\)'   # no bad url token
NAMESPACE = re.compile(rf'\s*(?:({IDENT})(?:\s+|(?=["\'])))?({STRING}|{URL})\s*', re.I)


XHTML = 'http://www.w3.org/1999/xhtml'
FOREIGN = '\x00default'   # among a sheet's prefixes: its default namespace is not XHTML's (no identifier holds a NUL)


def declared(state, prelude, body):
    """(namespace prefixes in force, whether the sheet may still declare one) after a top-level statement of a sheet,
    which starts with none: an @namespace whose whole prelude is a prefix and then a string or url() adds the prefix,
    while only @charset, @import, @layer and @namespace statements came before it, as CSS Namespaces requires; one
    written otherwise declares nothing, and anything else ends the declarations. One without a prefix sets the default
    namespace, the last one standing: when it is not XHTML's, FOREIGN joins the prefixes, since every unprefixed name,
    and every compound without one, then matches that namespace's elements only, never the book's text."""
    prefixes, early = state
    name, rest = at_rule(prelude) if body is None else (None, '')
    if name == 'namespace':
        m = NAMESPACE.fullmatch(rest)
        if not (m and early):
            return prefixes, early
        if m.group(1):
            return prefixes | {unescape(m.group(1))}, early
        uri = m.group(2).strip()
        uri = uri[4:-1].strip() if uri[:4].lower() == 'url(' else uri
        uri = unescape(uri[1:-1] if uri[:1] in '"\'' else uri)
        return (prefixes - {FOREIGN} if uri == XHTML else prefixes | {FOREIGN}), early
    return prefixes, early and name in ('charset', 'import', 'layer')


def readable_selector(selector, prefixes=frozenset()):
    """Whether every reader takes a selector, as far as the import can tell: compounds of a name, ids, classes and
    attribute tests joined by combinators, the pseudo-classes of CSS Selectors 3 (:not of one simple selector), a
    pseudo-element of CSS 2 only at the very end, and a namespace prefix only where the sheet declares it. Anything else
    may be invalid in a reader, which voids the whole list there."""
    s = re.sub(ESC, 'x', preprocess(selector).strip())   # an escape is one character of a name
    s = re.sub(r'"(?:[^"\\\n])*"|\'(?:[^\'\\\n])*\'', '""', s)
    if any(m.group(1) not in prefixes for m in re.finditer(rf'({IDENT})\|(?!\|)', s)):
        return False   # an undeclared prefix is invalid
    steps = list(PSEUDO_STEP.finditer(s))
    for m in steps:
        colons, name, argument = m.group(1), m.group(2).lower(), m.group(3)
        if colons == '::' or name in OLD_ELEMENTS:
            ok = argument is None and name in OLD_ELEMENTS and m.end() == len(s)
        elif argument is None:
            ok = name in EVERY_READER
        elif name in NTH:
            ok = re.fullmatch(r'\s*(?:odd|even|[+-]?\d*n(?:\s*[+-]\s*\d+)?|[+-]?\d+)\s*', argument, re.I)
        elif name == 'lang':
            ok = re.fullmatch(rf'\s*{IDENT}\s*', argument)
        else:   # :not of one simple selector, as CSS Selectors 3 has it
            ok = name == 'not' and (re.fullmatch(rf'\s*(?:{TYPE}|{SIMPLE})\s*', argument)
                                    or re.fullmatch(r'\s*:[\w-]+(?:\([^()]*\))?\s*', argument)
                                    and readable_selector('*' + argument.strip(), prefixes) and 'not(' not in argument.lower())
        if not ok:
            return False
    for m in reversed(steps):   # each pseudo step stands for a class, so a compound it ends or alone stays a compound
        s = s[:m.start()] + '.x' + s[m.end():]
    return bool(COMPLEX.fullmatch(s))


def selector_list(prelude, prefixes=frozenset()):
    """A rule's selectors as CSS takes its list: None when one is empty, as in `.a, { }`, which voids the whole list, so
    CSS drops the rule; else (selectors, readable), readable False when one is beyond what every reader takes and so
    might void the list in some (readable_selector), in which case none of them is certain."""
    selectors = [s.strip() for s in split_outside_strings(prelude, ',')]
    if not all(selectors):
        return None
    return selectors, FOREIGN not in prefixes and all(readable_selector(s, prefixes) for s in selectors)


def scan_rules(css, sure=True, prefixes=frozenset(), top=True):
    """(selector, 'display' or 'visibility', value, important, specificity, certain) of every rule that sets either, in
    order, conditional groups included: one that never holds (print or speech, a feature query that fails) is left out,
    and one the import cannot settle (a condition or query it cannot weigh, a layer, a container, a scope) makes its
    rules uncertain, as does nesting (nested). Any other at-rule, such as @font-face or @keyframes, styles no element.
    css: one sheet or a list (sheets_of), each read alone; prefixes: the namespace prefixes in force where css starts, at
    the top each sheet's own, which follow from its statements (declared)."""
    if isinstance(css, (list, tuple)):
        for sheet in css:
            yield from scan_rules(sheet, sure, frozenset(), top)
        return
    state = (prefixes, True)
    for prelude, body in statements(css):
        if top:
            state = declared(state, prelude, body)
            prefixes = state[0]
        if body is None:
            continue
        if prelude.startswith('@'):
            holds = group_holds(prelude)
            if holds is not False:   # one that never holds, such as print, counts for nothing; one it cannot weigh makes its rules unsettled
                yield from scan_rules(body, sure and holds is True, prefixes, False)
            continue
        listed = selector_list(prelude, prefixes)
        if listed is None:   # CSS drops a rule whose selector list holds an empty selector, nested rules and all
            continue
        selectors, readable = listed
        found = [(kind, value, important) for kind, (value, important) in (('display', display_of(body)), ('visibility', visibility_of(body)))
                 if value is not None]
        for selector in selectors:
            if pseudo_element(selector):   # a generated box of its own, never the element
                continue
            for kind, value, important in found:
                yield (selector, kind, value, important, specificity(selector),   # a list it cannot read settles nothing,
                       sure and readable and certain(selector) and 'var(' not in value)   # nor does a var() value
        for inner_prelude, inner_body in nested(body)[1]:   # a rule nested in this one, which a reader without CSS Nesting
            yield from scan_rules(nest(prelude, inner_prelude, inner_body), False, prefixes, False)   # drops: never certain


def supports(condition):
    """Whether a feature query holds in a reader: True, False, or None when the import cannot tell. It weighs a test of
    display or visibility by the values it reads, and of font-size by font_size_valid, CSS-wide keywords included, with
    not, and and or; anything else, a value it cannot parse included, it cannot weigh."""
    c = condition.strip()
    if re.match(r'(?i)not\b', c):
        inner = supports(c[3:])
        return None if inner is None else not inner
    for word in ('or', 'and'):
        parts = [part for part in re.split(rf'(?i)\s+{word}\s+', c)]
        if len(parts) > 1 and all(part.strip().startswith('(') or re.match(r'(?i)not\b', part.strip()) for part in parts):
            values = [supports(part) for part in parts]
            if word == 'or':
                return True if True in values else None if None in values else False
            return False if False in values else None if None in values else True
    if not (c.startswith('(') and c.endswith(')')):
        return None
    inner = c[1:-1].strip()
    if inner.startswith('(') or re.match(r'(?i)not\b', inner):
        return supports(inner)
    prop, _, value = inner.partition(':')
    prop, value = prop.strip().lower(), value.strip().lower()
    if prop == 'display':
        return value == 'none' or shows(value) or value in CSS_WIDE
    if prop == 'visibility':
        return value in ('visible', 'hidden', 'collapse') or value in CSS_WIDE
    if prop == 'font-size':
        return font_size_valid(value)
    return None


LENGTH_UNITS = {'px', 'em', 'rem', 'ex', 'rex', 'ch', 'rch', 'cap', 'rcap', 'ic', 'ric', 'lh', 'rlh', 'pt', 'pc', 'in', 'cm', 'mm', 'q',
                'vw', 'vh', 'vi', 'vb', 'vmin', 'vmax', '%'} | {p + u for p in ('sv', 'lv', 'dv') for u in ('w', 'h', 'i', 'b', 'min', 'max')} \
               | {'cq' + u for u in ('w', 'h', 'i', 'b', 'min', 'max')}
FONT_SIZES = {'xx-small', 'x-small', 'small', 'medium', 'large', 'x-large', 'xx-large', 'xxx-large', 'smaller', 'larger', 'math'}


def font_size_valid(value):
    """Whether a font-size value is valid: True for zero however written, a length or percentage that is not negative
    in a known unit, a keyword or a CSS-wide keyword; False only for what is surely invalid (a negative size, a number
    other than zero without a unit); None for anything else, such as calc() or a unit the import does not know."""
    if value in FONT_SIZES or value in CSS_WIDE:
        return True
    m = re.fullmatch(r'([+-]?)((?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:e[+-]?[0-9]+)?)([a-z]+|%)?', value)   # CSS's number: no bare dot
    if not m:
        return None
    sign, number, unit = m.group(1), float(m.group(2)), m.group(3)
    if number == 0:
        return True if unit is None or unit in LENGTH_UNITS else None
    if sign == '-' or unit is None:
        return False
    return True if unit in LENGTH_UNITS else None


def imports(css):
    """Every @import statement of a stylesheet, those inside conditional groups included (a sheet under a condition
    the import cannot settle is wrapped in one by stylesheets); css: one sheet or a list (sheets_of)."""
    for prelude, body in (pair for sheet in sheets_of(css) for pair in statements(sheet)):
        if body is None and at_rule(prelude)[0] == 'import':   # the at-keyword itself: never @import-theme
            yield prelude
        elif body is not None and prelude.startswith('@'):
            yield from imports(body)


def css_type(kind):
    """Whether a linked sheet's or a stylesheet instruction's declared type is CSS: none given, or text/css with any
    parameters, such as a charset."""
    return not (kind or '').strip() or kind.split(';')[0].strip().lower() == 'text/css'


def style_type(kind):
    """Whether a style element's type makes it CSS: absent, empty or text/css exactly, in any case. HTML's update a
    style block refuses any other value, one with parameters included."""
    return kind is None or kind == '' or kind.lower() == 'text/css'


def sealed(css):
    """A stylesheet closed as its own end closes it (CSS Syntax 3), read as statements reads it: comments removed, one
    left open running to the end; a backslash at the very end read as CSS reads it, U+FFFD outside a string and nothing
    inside one; then a string or block left open is closed, a statement at-rule given its semicolon, and a rule's
    selectors that never reach a block dropped, as CSS drops them. Sheets joined one after another, or wrapped in an
    @media block, then never run into each other."""
    css = strip_comments(css or '')
    quote, start, i, n, depth, level = '', 0, 0, len(css), 0, 0
    while i < n:
        ch = css[i]
        if ch == '\\':
            i += 2
            continue
        if ch in '"\'':
            j = skip_string(css, i)
            quote = ch if j > n else ''
            i = j
            continue
        if level:   # inside a block, where statements counts braces alone
            level += {'{': 1, '}': -1}.get(ch, 0)
            start = i + 1 if not level else start
        elif ch in '()':
            depth = depth + 1 if ch == '(' else max(depth - 1, 0)
        elif not depth and ch == ';' and css[start:i].strip().startswith('@'):
            start = i + 1
        elif not depth and ch == '{':
            level = 1
        i += 1
    if (len(css) - len(css.rstrip('\\'))) % 2:   # an escape the end cuts short (CSS Syntax 4.3.7)
        css = css[:-1] + ('' if quote else '\ufffd')
    if level:
        return css + quote + '}' * level
    if css[start:].strip().startswith('@'):   # a statement at-rule with no semicolon, such as a last @import
        return css + quote + ')' * depth + ';'
    return css[:start]   # selectors with no block, which CSS drops at the end, never reach the next sheet


def style_nodes(root):
    """The link and style elements of a parsed document, in document order, as stylesheets takes them: a style element's
    text is its child text content as the XML parser gives it, references expanded, CDATA as written, comments and
    processing instructions left out."""
    nodes = []
    for e in root.iter():
        if local(e.tag) == 'link':
            nodes.append(('link', e.get('href', ''), e.get('media'), e.get('rel'), e.get('type')))
        elif local(e.tag) == 'style':
            nodes.append(('style', (e.text or '') + ''.join(c.tail or '' for c in e), e.get('media'), e.get('type')))
    return nodes


def stylesheets(pis, nodes, fetch):
    """The CSS a reader's screen takes for a document: the sheets its prolog's xml-stylesheet instructions name, then its
    links and style elements in document order. An alternate sheet is a reader's option and one for print or speech is
    left out, and so is one whose type is not CSS (style_type, css_type); one under a condition the import cannot
    settle is kept as the @media block it amounts to. The sheets come as a list, each sealed as its own end closes it,
    so the readers take each alone and what belongs to one sheet, such as its namespace prefixes, stays its own; no
    mark in a sheet's text can join or part them. nodes: ('link', href, media, rel, type) or ('style', text, media,
    type); fetch(href): a packaged sheet's text, or None."""
    sheets = []

    def add(text, media):
        text = sealed(text)
        applies = media_applies(media)
        if applies:
            sheets.append(text)
        elif applies is None:
            sheets.append(f'@media {media} {{\n{text}\n}}')

    for pi in pis:
        if css_type(pi.get('type')) and (pi.get('alternate') or '').lower() != 'yes' and media_applies(pi.get('media')) is not False:
            text = fetch(pi.get('href', ''))   # one for print or speech is never fetched
            if text is not None:
                add(text, pi.get('media'))
    for node in nodes:
        if node[0] == 'style':
            if style_type(node[3]):
                add(node[1], node[2])
            continue
        rel = (node[3] or '').lower().split()
        if 'stylesheet' in rel and 'alternate' not in rel and css_type(node[4]) and media_applies(node[2]) is not False:
            text = fetch(node[1])
            if text is not None:
                add(text, node[2])
    return sheets


def undrawn_by_default(element):
    """Whether a reader's own stylesheet gives the element display: none, which the book's stylesheets can override:
    an element no reader draws (a template never shows), a dialog not open, or the hidden attribute (HTML 15.3.1)."""
    tag = local(element.tag)
    return (tag in NEVER_SHOWN or tag == 'dialog' and element.get('open') is None
            or element.get('hidden') is not None and not until_found(element))


def until_found(element):
    """The hidden attribute set to until-found, whose content a reader shows only when a search finds it, whatever
    display it is given."""
    return (element.get('hidden') or '').strip().lower() == 'until-found'



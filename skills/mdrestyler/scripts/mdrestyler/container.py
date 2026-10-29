"""Safe reading of EPUB and DOCX containers, shared by the measures and by importers built on mdrestyler. Standard library only.

It parses XML with entity declarations refused, decodes markup by its BOM or declaration, refuses DRM, and reads
archives within explicit limits. It renders nothing: an importer renders text and structure itself, and the measuring
reader in metrics.py keeps its own limits."""
import hashlib
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.parsers import expat

FONT_OBFUSCATION = {'http://www.idpf.org/2008/embedding', 'http://ns.adobe.com/pdf/enc#RC'}
FONT_EXTENSIONS = ('.otf', '.ttf', '.woff', '.woff2')   # font obfuscation applies to fonts only
OPS = '{http://www.idpf.org/2007/ops}'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'

# What one importer may read. The measuring reader keeps its own smaller limits: an importer carries images.
IMPORT_LIMITS = {'source_mb': 256, 'members': 10_000, 'expanded_mb': 1024, 'member_mb': 256, 'ratio': 100}


class LimitError(ValueError):
    """Input beyond what a reader may read."""


class DRMError(ValueError):
    """Encrypted or rights-managed content, never read."""


def parse_xml(data):
    """An element tree, refusing entity declarations: text in comments, CDATA and processing instructions is not one."""
    def refuse_entity(*_):
        raise ET.ParseError('entity declarations are not supported')

    parser = expat.ParserCreate()
    parser.EntityDeclHandler = refuse_entity
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise ET.ParseError(str(error)) from None
    return ET.fromstring(data)


def member_xml(read, name):
    """A package member's element tree; a member that is not well-formed XML is refused by name, never a traceback."""
    try:
        return parse_xml(read(name))
    except ET.ParseError as error:
        raise ValueError(f'{name} is not well-formed XML ({error})') from None


def decode_markup(data, strict=False):
    """XHTML bytes as text, by the BOM or the XML declaration's encoding, UTF-8 otherwise. Strict, a byte the encoding
    cannot read raises UnicodeDecodeError instead of becoming U+FFFD."""
    errors = 'strict' if strict else 'replace'
    for bom, codec in ((b'\xff\xfe\x00\x00', 'utf-32'), (b'\x00\x00\xfe\xff', 'utf-32'), (b'\xef\xbb\xbf', 'utf-8-sig'),
                       (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16')):   # UTF-32's little-endian mark starts like UTF-16's
        if data.startswith(bom):
            return data.decode(codec, errors=errors)
    for start, codec in ((b'\x00\x00\x00<', 'utf-32-be'), (b'<\x00\x00\x00', 'utf-32-le'), (b'\x00<\x00?', 'utf-16-be'),
                         (b'<\x00?\x00', 'utf-16-le')):   # no mark: the first characters tell, as an XML parser reads them (XML 1.0, F.1)
        if data.startswith(start):
            return data.decode(codec, errors=errors)
    declared = re.match(rb'<\?xml\s[^>]*?\bencoding\s*=\s*["\']([A-Za-z][A-Za-z0-9._-]*)["\']', data)   # the whole declaration, Eq: S? '=' S?
    try:
        codec = declared.group(1).decode('ascii').lower() if declared else 'utf-8'
        if codec.replace('_', '-').startswith(('utf-16', 'utf16', 'utf-32', 'utf32')):
            codec = 'utf-8'   # a declaration readable as ASCII rules out UTF-16 and UTF-32 without a BOM
        return data.decode(codec, errors=errors)
    except LookupError:   # an encoding Python does not know
        return data.decode('utf-8', errors=errors)


def local_name(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def package_path(container):
    """The package document a parsed container.xml names: its full-path, a URL path from the archive root (EPUB 3.3),
    decoded as the archive names its members (content%20file.opf is "content file.opf"); None when it names none, or a
    path outside the archive."""
    full = next((e.get('full-path') for e in container.iter() if local_name(e.tag) == 'rootfile'), None)
    path = resolve('', full) if full else None
    return path if path and not unsafe_member(path) else None


def package_media(names, read):
    """The media type the package manifest declares for each archive member it lists."""
    if 'META-INF/container.xml' not in names:
        return {}
    rootfile = package_path(member_xml(read, 'META-INF/container.xml'))
    if not rootfile or rootfile not in names:
        return {}
    base = posixpath.dirname(rootfile)
    return {resolve(base, e.get('href', '')): e.get('media-type', '') for e in member_xml(read, rootfile).iter()
            if local_name(e.tag) == 'item' and e.get('href')}


FONT_TYPES = {'font/ttf', 'font/otf', 'font/woff', 'font/woff2', 'font/sfnt', 'font/collection', 'application/font-sfnt',
              'application/vnd.ms-opentype', 'application/font-woff', 'application/font-woff2', 'application/x-font-ttf',
              'application/x-font-truetype', 'application/x-font-otf', 'application/x-font-opentype'}


def media_type(value):
    """A declared media type as media types are compared: its case left aside and its parameters dropped."""
    return (value or '').split(';', 1)[0].strip().lower()


def font_type(media):
    """Whether a manifest media type names a font, its parameters left aside."""
    return media_type(media) in FONT_TYPES


def check_epub_drm(names, read, where):
    """Refuse an EPUB with a rights file or encryption beyond font obfuscation of fonts: each encrypted entry must name
    font obfuscation itself and a font file the archive holds: one the manifest declares a font, whatever its name, or,
    where the manifest does not list it, one named as a font.
    Returns the obfuscated members, which a reader never reads as content. read(name) returns a member's bytes."""
    obfuscated = set()
    if 'META-INF/rights.xml' in names:
        raise DRMError(f'{where}: carries a DRM rights file; only DRM-free EPUBs can be read')
    if 'META-INF/encryption.xml' in names:
        media = package_media(names, read)
        tree = member_xml(read, 'META-INF/encryption.xml')
        checked = set()   # every CipherReference must sit in an entry checked here, one under an EncryptedKey included
        for data in tree.iter():
            if local_name(data.tag) != 'EncryptedData':
                continue
            method = next((m for m in data if local_name(m.tag) == 'EncryptionMethod'), None)
            references = [r for r in data.iter() if local_name(r.tag) == 'CipherReference']
            if method is None or method.get('Algorithm') not in FONT_OBFUSCATION or not references:
                raise DRMError(f'{where}: content is encrypted ({references[0].get("URI") if references else "an entry"}); '
                               'only DRM-free EPUBs can be read')
            for reference in references:   # each target, however many one entry names
                target = reference.get('URI') or ''
                member = posixpath.normpath(unquote(target))
                declared = media.get(member)
                font = font_type(declared) if declared is not None else None   # the manifest's word, where it lists the member
                if not font and not target.lower().endswith(FONT_EXTENSIONS):   # one it does not list goes by its name
                    raise DRMError(f'{where}: content is encrypted ({target or "an entry"}); only DRM-free EPUBs can be read')
                if member not in names:
                    raise DRMError(f'{where}: {target} is obfuscated as a font but missing from the archive; only DRM-free EPUBs can be read')
                if declared is not None and not font:
                    raise DRMError(f'{where}: {target} is obfuscated as a font but declared {declared or "with no media type"}; '
                                   'only DRM-free EPUBs can be read')
                obfuscated.add(member)
                checked.add(id(reference))
        stray = [r for r in tree.iter() if local_name(r.tag) == 'CipherReference' and id(r) not in checked]
        if stray:
            raise DRMError(f'{where}: content is encrypted ({stray[0].get("URI") or "an entry"}); only DRM-free EPUBs can be read')
    return obfuscated


def unsafe_member(name):
    """Why an archive member name is unsafe to resolve, or None."""
    if not name or '\x00' in name or '\\' in name:
        return 'an empty name, a NUL or a backslash'
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        return 'an absolute path'
    if any(part == '..' for part in name.split('/')):
        return 'a parent-folder step'
    return None


class Archive:
    """A ZIP container read once into memory within the import limits, with every member checked before use."""

    def __init__(self, path, limits=None):
        limits = limits or IMPORT_LIMITS
        path = Path(path)
        if not path.is_file():
            raise ValueError(f'{path}: not a regular file')
        cap = limits['source_mb'] * 2**20
        with open(path, 'rb') as source:
            data = source.read(cap + 1)
        if len(data) > cap:
            raise LimitError(f'{path}: over the {limits["source_mb"]} MiB an import reads')
        self.path, self.data, self.limits = path, data, limits
        self.sha256 = hashlib.sha256(data).hexdigest()
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as error:
            raise ValueError(f'{path}: not a readable ZIP container ({error})') from None
        infos = self.zip.infolist()
        if len(infos) > limits['members']:
            raise LimitError(f'{path}: {len(infos)} archive members, over the {limits["members"]:,} an import reads')
        total = 0
        self.infos = {}
        for info in infos:
            problem = unsafe_member(info.filename)
            if problem:
                raise LimitError(f'{path}: member {info.filename!r} has {problem}')
            if info.filename in self.infos:   # which of the two a reader takes cannot be told
                raise LimitError(f'{path}: member {info.filename!r} appears twice; which copy a reader takes cannot be told')
            if info.flag_bits & 0x1:
                raise DRMError(f'{path}: {info.filename} is encrypted; only DRM-free files can be imported')
            if info.file_size > limits['member_mb'] * 2**20:
                raise LimitError(f'{path}: {info.filename} expands to {info.file_size / 2**20:.0f} MiB, over the {limits["member_mb"]} MiB per member')
            if info.compress_size and info.file_size / info.compress_size > limits['ratio'] and info.file_size > 2**20:
                raise LimitError(f'{path}: {info.filename} expands {info.file_size / info.compress_size:.0f} times, over the {limits["ratio"]}:1 an import accepts')
            total += info.file_size
            self.infos[info.filename] = info
        if total > limits['expanded_mb'] * 2**20:
            raise LimitError(f'{path}: expands to {total / 2**20:.0f} MiB in all, over the {limits["expanded_mb"]} MiB an import reads')
        self.names = set(self.infos)
        self.expanded = total
        self.encrypted = set()   # obfuscated members, which the import never reads as content

    def has(self, name):
        return name in self.infos

    def read(self, name):
        info = self.infos.get(name)
        if info is None:
            raise KeyError(f'{self.path}: no member {name}')
        if name in self.encrypted:
            raise DRMError(f'{self.path}: {name} is encrypted, and the book uses it as content; only DRM-free EPUBs can be read')
        with self.zip.open(info) as member:
            content = member.read(info.file_size + 1)
        if len(content) != info.file_size:
            raise ValueError(f'{self.path}: {name} does not hold the {info.file_size} bytes its entry declares')
        return content


def resolve(base, href):
    """An archive path for href relative to the folder base, without a fragment; None for an external reference."""
    parts = urlsplit(href or '')
    if parts.scheme or parts.netloc or (href or '').startswith('/'):
        return None
    return posixpath.normpath(posixpath.join(base, unquote(parts.path))) if parts.path else None


def external(href):
    """Whether href points outside the archive (a scheme or a host): never fetched."""
    parts = urlsplit(href or '')
    return bool(parts.scheme or parts.netloc)


def text_of(element):
    return re.sub(r'\s+', ' ', ''.join(element.itertext())).strip()


# ---- EPUB --------------------------------------------------------------------------------------------------------

def epub_package(archive):
    """Metadata, manifest, spine, navigation and landmarks of an EPUB, after the DRM check."""
    archive.encrypted = check_epub_drm(archive.names, archive.read, archive.path)   # obfuscated fonts, never read as content
    if not archive.has('META-INF/container.xml'):
        raise ValueError(f'{archive.path}: no META-INF/container.xml; not an EPUB')
    rootfile = package_path(member_xml(archive.read, 'META-INF/container.xml'))
    if not rootfile or not archive.has(rootfile):
        raise ValueError(f'{archive.path}: container.xml names no readable package file')
    opf = member_xml(archive.read, rootfile)
    base = posixpath.dirname(rootfile)
    meta = {'title': [], 'creator': [], 'language': [], 'identifier': [], 'publisher': [], 'date': [], 'subject': [],
            'description': [], 'rights': []}
    for e in opf.iter():
        name = local_name(e.tag)
        if name in meta and (e.text or '').strip():
            meta[name].append(re.sub(r'\s+', ' ', e.text).strip())
    manifest = {}
    for e in opf.iter():
        if local_name(e.tag) == 'item' and e.get('id'):
            href = e.get('href', '')
            manifest[e.get('id')] = {'href': resolve(base, href), 'raw': href, 'media': e.get('media-type', ''),
                                     'props': set((e.get('properties') or '').split())}
    spine, toc_id = [], None
    for e in opf.iter():
        if local_name(e.tag) == 'spine':
            toc_id = e.get('toc')
        if local_name(e.tag) == 'itemref':
            spine.append({'idref': e.get('idref'), 'linear': (e.get('linear') or 'yes').lower() != 'no'})
    nav_href = next((m['href'] for m in manifest.values() if 'nav' in m['props']), None)
    toc, landmarks = [], []
    if nav_href and archive.has(nav_href):
        nav = member_xml(archive.read, nav_href)
        folder = posixpath.dirname(nav_href)
        for element in nav.iter():
            if local_name(element.tag) != 'nav':
                continue
            kind = element.get(OPS + 'type') or ''
            target = toc if 'toc' in kind.split() else landmarks if 'landmarks' in kind.split() else None
            if target is None:
                continue
            for a in element.iter():
                if local_name(a.tag) == 'a':
                    href = a.get('href', '')
                    entry = {'label': text_of(a), 'path': resolve(folder, href), 'fragment': unquote(urlsplit(href).fragment)}
                    if target is landmarks:
                        entry['type'] = a.get(OPS + 'type') or ''
                    target.append(entry)
    elif toc_id and toc_id in manifest and manifest[toc_id]['href'] and archive.has(manifest[toc_id]['href']):
        ncx = member_xml(archive.read, manifest[toc_id]['href'])
        folder = posixpath.dirname(manifest[toc_id]['href'])
        for point in ncx.iter():
            if local_name(point.tag) == 'navPoint':
                label = next((text_of(t) for t in point.iter() if local_name(t.tag) == 'text'), '')
                src = next((c.get('src', '') for c in point if local_name(c.tag) == 'content'), '')
                toc.append({'label': label, 'path': resolve(folder, src), 'fragment': unquote(urlsplit(src).fragment)})
    for e in opf.iter():   # EPUB 2 guide entries name landmarks too
        if local_name(e.tag) == 'reference':
            href = e.get('href', '')
            landmarks.append({'label': e.get('title', ''), 'path': resolve(base, href),
                              'fragment': unquote(urlsplit(href).fragment), 'type': e.get('type', '')})
    return {'rootfile': rootfile, 'base': base, 'meta': meta, 'manifest': manifest, 'spine': spine, 'nav': nav_href,
            'toc': toc, 'landmarks': landmarks}


# ---- DOCX --------------------------------------------------------------------------------------------------------

def relationships(archive, part):
    """id -> (type, target path or URL, external) for a part's relationships. Only TargetMode="External" is external; an
    internal target beginning with / is a path from the package root, as OPC allows, any other one is relative to the
    part's folder."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, '_rels', name + '.rels')
    found = {}
    if not archive.has(rels_name):
        return found
    for rel in member_xml(archive.read, rels_name).iter():
        if local_name(rel.tag) != 'Relationship':
            continue
        mode, target = rel.get('TargetMode', ''), rel.get('Target', '')
        is_external = mode == 'External'
        if is_external:
            path = target
        elif target.startswith('/') and not target.startswith('//'):
            path = resolve('', target[1:])
        else:
            path = resolve(folder, target)
        found[rel.get('Id')] = (rel.get('Type', '').rsplit('/', 1)[-1], path, is_external)
    return found


def docx_package(archive):
    """The main document and the parts an import reads beside it."""
    if archive.has('META-INF/rights.xml'):
        raise DRMError(f'{archive.path}: carries a rights file')
    if archive.has('EncryptedPackage') or archive.has('EncryptionInfo'):
        raise DRMError(f'{archive.path}: an encrypted Office package')
    main, core = None, None
    for rel_id, (kind, target, is_external) in relationships(archive, '').items():
        if kind == 'officeDocument' and not is_external:
            main = target
        elif kind == 'core-properties' and not is_external:   # wherever the package keeps its core properties
            core = target
    main = main or 'word/document.xml'
    if not archive.has(main):
        raise ValueError(f'{archive.path}: no main document part; not a DOCX')
    rels = relationships(archive, main)
    parts = {kind: target for kind, target, is_external in rels.values() if not is_external and kind in
             ('styles', 'numbering', 'footnotes', 'endnotes', 'comments', 'settings')}
    meta = {'title': [], 'creator': [], 'language': [], 'subject': [], 'description': [], 'keywords': []}
    overrides, defaults = {}, {}   # what [Content_Types].xml declares: a type per part (lower case), and per extension
    if archive.has('[Content_Types].xml'):
        for e in member_xml(archive.read, '[Content_Types].xml').iter():
            if local_name(e.tag) == 'Override' and e.get('PartName'):
                overrides[unquote(e.get('PartName')).lstrip('/').lower()] = e.get('ContentType', '')
            elif local_name(e.tag) == 'Default' and e.get('Extension'):
                defaults[e.get('Extension').lower()] = e.get('ContentType', '')
    core = core if core and archive.has(core) else 'docProps/core.xml'   # the usual place, where no relationship names one
    if archive.has(core):
        for e in member_xml(archive.read, core).iter():
            name = local_name(e.tag)
            if name in meta and (e.text or '').strip():
                meta[name].append(re.sub(r'\s+', ' ', e.text).strip())
    return {'main': main, 'rels': rels, 'parts': parts, 'meta': meta, 'types': (overrides, defaults)}

"""Bounded offline bundles. No browser engine, network client or executable content."""
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import unicodedata
from urllib.parse import unquote, urlsplit, quote
import zipfile

# MAX_ARCHIVE bounds the stored .zip so a single import cannot exhaust memory.
# MAX_TOTAL bounds the decompressed content and is the real size contract; it is
# deliberately below MAX_ARCHIVE so any legal bundle can also be stored again by
# pack() without tripping the archive limit.
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
MAX_FILES = 2000
HTML = {'.html', '.htm'}
SUPPORTED = HTML | {'.css', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.js', '.txt', '.ico', '.webp', '.woff', '.woff2', '.ttf', '.json', '.xml', '.md', '.map'}
# Elements whose content is dropped: active content (security) and layout that Qt
# cannot represent. A tag left open at EOF silently hides the rest of the page.
DROP_TAGS = {'script','iframe','object','embed','form','button','textarea','select','svg','math'}
# inspect() caps the reference list; the cap is reported as its own issue so a
# caller never mistakes a clipped report for a complete one.
MAX_ISSUES = 5000
TRUNCATED = 'Too many reference issues; the list below is incomplete.'


def safe_path(name):
    if not isinstance(name, str) or not name or len(name) > 500 or '\\' in name or name.startswith('/'):
        raise ValueError('Unsafe bundle path.')
    for part in name.split('/'):
        if (part in ('', '.', '..') or part.rstrip(' .') != part or ':' in part
                or any(ord(c) < 32 for c in part) or unicodedata.normalize('NFC', part) != part
                or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', part, re.I)):
            raise ValueError('Unsafe bundle path: ' + name)
    return name


def resolve(current, reference):
    """Decode once, reject remote/absolute URLs, resolve only within bundle root."""
    url = urlsplit(reference)
    if url.scheme or url.netloc or url.path.startswith(('/', '\\')):
        raise ValueError('External or absolute resource blocked.')
    path = unquote(url.path)
    if '\\' in path or path.startswith('/'):
        raise ValueError('Unsafe resource URL.')
    target = posixpath.normpath(posixpath.join(posixpath.dirname(current), path)) if path else current
    return safe_path(target), unquote(url.fragment)


def decode(content):
    # HTML encodings found in older offline manuals; no charset network discovery.
    match = re.search(br'charset\s*=\s*["\']?([\w-]+)', content[:4096], re.I)
    encoding = match[1].decode('ascii') if match else 'utf-8-sig'
    if encoding.lower() not in ('utf-8', 'utf-8-sig', 'windows-1252', 'iso-8859-1', 'shift_jis'):
        encoding = 'utf-8-sig'
    return content.decode(encoding, errors='replace')


def read_zip(content, cancelled=lambda: False):
    if len(content) > MAX_ARCHIVE:
        raise ValueError('Archive exceeds the stored-size limit.')
    files, names, total, spellings = {}, set(), 0, {}
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError('Archive exceeds 2000 entries.')
            for info in entries:
                if cancelled():
                    raise InterruptedError('Import cancelled.')
                name = safe_path(info.filename.rstrip('/') if info.is_dir() else info.filename)
                if info.orig_filename != info.filename:
                    raise ValueError('Archive filename was normalized; original path is unsafe.')
                for parent in [PurePosixPath(name), *PurePosixPath(name).parents]:
                    spelling = str(parent)
                    previous = spellings.setdefault(spelling.casefold(),spelling)
                    if previous != spelling: raise ValueError('Case-ambiguous archive paths.')
                folded = name.casefold()
                mode = info.external_attr >> 16
                if (folded in names or info.flag_bits & 1 or stat.S_ISLNK(mode)
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('Duplicate, encrypted or unsafe archive entry.')
                names.add(folded)
                # The declared size is the budget; a mismatch against the bytes
                # actually read below catches a lying header. Legitimate manuals
                # compress far past 200:1, so no compression-ratio heuristic is
                # applied -- it rejected real generated torque tables and folders.
                total += info.file_size
                if info.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError('Archive expansion limit exceeded.')
                if not info.is_dir():
                    if PurePosixPath(name).suffix.lower() not in SUPPORTED:
                        raise ValueError('Unsupported bundle file: ' + name)
                    with archive.open(info) as stream:
                        data = stream.read(MAX_FILE+1)
                    if len(data) != info.file_size or len(data) > MAX_FILE:
                        raise ValueError('Invalid archive size.')
                    files[name] = data
            # A file may not also be used as a directory by another entry.
            # The casefold set is built once so this stays linear in entry count.
            existing = {n.casefold() for n in files}
            for name in files:
                if any(str(parent).casefold() in existing for parent in PurePosixPath(name).parents if str(parent) != '.'):
                    raise ValueError('Conflicting archive paths.')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError('Invalid or unsupported ZIP archive.') from error
    if not any(PurePosixPath(n).suffix.lower() in HTML for n in files):
        raise ValueError('Bundle contains no HTML documents.')
    return files


def pack(files):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED)
    result = output.getvalue()
    read_zip(result)
    return result


def css_references(value):
    return re.findall(r'url\(\s*["\']?([^"\')]+)', value, re.I) + re.findall(r'@import\s+["\']([^"\']+)', value, re.I)


class References(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.links, self.anchors = [], set()
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.anchors.update(v for k,v in attrs if k in ('id','name') and v)
        self.links.extend(v for k,v in attrs if k in ('href','src','poster','data') and v)
        self.links.extend(css_references(values.get('style', '')))
    def handle_data(self, value):
        self.links.extend(css_references(value))


def import_source(source, cancelled=lambda: False):
    path = Path(source)
    if path.is_symlink():
        raise ValueError('Symbolic link sources are not supported.')
    if path.suffix.lower() == '.zip':
        with path.open('rb') as stream:
            return read_zip(stream.read(MAX_ARCHIVE+1), cancelled)
    if path.suffix.lower() not in HTML:
        raise ValueError('Choose HTML, HTM or ZIP.')
    # Only the selected page's reachable resources below its parent are collected.
    # 'pending' doubles as a set so a page with many distinct references is linear.
    root, files, total = path.parent.resolve(), {}, 0
    queue, pending = [safe_path(path.name)], {safe_path(path.name)}
    while queue:
        if cancelled():
            raise InterruptedError('Import cancelled.')
        name = queue.pop()
        pending.discard(name)
        if name in files:
            continue
        target = root / name
        if any(p.is_symlink() for p in [target, *target.parents] if p != root and root in p.parents):
            raise ValueError('Symbolic links in HTML resources are not supported.')
        if not target.is_file():
            continue  # Report missing references during inspection.
        if len(files) >= MAX_FILES or PurePosixPath(name).suffix.lower() not in SUPPORTED:
            raise ValueError('Unsupported resource or too many files.')
        with target.open('rb') as stream:
            content = stream.read(MAX_FILE+1)
        total += len(content)
        if len(content) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError('HTML bundle size limit exceeded.')
        files[name] = content
        suffix = target.suffix.lower()
        refs = References(decode(content)).links if suffix in HTML else css_references(decode(content)) if suffix == '.css' else []
        for reference in refs:
            try:
                linked, _ = resolve(name, reference)
                if linked not in files and linked not in pending:
                    queue.append(linked); pending.add(linked)
            except ValueError:
                pass
    return files


def read_bundle_dir(root):
    """Load an already-materialized bundle directory without re-inflating the ZIP.

    materialize_html() has already validated and atomically written the entries.
    Re-reading them costs one filesystem walk instead of a full read_zip() plus
    SHA-256, which is what kept large manuals on the GUI thread for seconds.
    The same path/suffix/size/symlink rules still apply so the result matches
    read_zip() exactly.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Bundle directory is missing or unsafe.')
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Bundle directory contains a symbolic link.')
        if not path.is_file():
            continue
        name = safe_path(path.relative_to(root).as_posix())
        if PurePosixPath(name).suffix.lower() not in SUPPORTED:
            raise ValueError('Unsupported bundle file: ' + name)
        content = path.read_bytes()
        total += len(content)
        if len(content) > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError('Bundle directory exceeds the size limit.')
        files[name] = content
    if not any(PurePosixPath(n).suffix.lower() in HTML for n in files):
        raise ValueError('Bundle contains no HTML documents.')
    return files


class _DropScanner(HTMLParser):
    """Tracks only whether a drop/style element is still open at end of input."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.style = [], False
    def handle_starttag(self, tag, attrs):
        if tag == 'style':
            self.style = True
        elif tag in DROP_TAGS and tag != 'embed':
            self.stack.append(tag)
    def handle_endtag(self, tag):
        if tag == 'style':
            self.style = False
        elif self.stack and tag == self.stack[-1]:
            self.stack.pop()


def unclosed_drop_tag(content):
    """Name of a drop/style element left open, which hides all following content."""
    scanner = _DropScanner()
    scanner.feed(decode(content))
    if scanner.stack:
        return scanner.stack[-1]
    return 'style' if scanner.style else None


def inspect(files):
    """Report missing/blocked references and pages whose trailing content was dropped."""
    parsed = {n: References(decode(v)) for n,v in files.items() if PurePosixPath(n).suffix.lower() in HTML}
    issues = []
    for name, content in files.items():
        if name.lower().endswith('.svg'):
            try: safe_svg(content)
            except Exception:
                issues.append({'page':name,'reference':name,'reason':'Unsupported or malformed SVG'})
        refs = parsed[name].links if name in parsed else css_references(decode(content)) if name.lower().endswith('.css') else []
        for ref in refs:
            try:
                target, anchor = resolve(name, ref)
                if target not in files:
                    reason = 'Missing resource'
                elif anchor and target in parsed and anchor not in parsed[target].anchors:
                    reason = 'Missing anchor'
                else:
                    continue
            except ValueError:
                reason = 'Blocked external or unsafe URL'
            issues.append({'page': name, 'reference': ref[:1000], 'reason': reason})
            if len(issues) >= MAX_ISSUES:
                # Explicit sentinel so callers can tell a complete report from a
                # clipped one instead of assuming every issue was listed.
                issues.append({'page': '', 'reference': '', 'reason': TRUNCATED})
                return issues
    for name, content in files.items():
        if name not in parsed:
            continue
        dropped = unclosed_drop_tag(content)
        if dropped:
            issues.append({'page': name, 'reference': '<'+dropped+'>',
                           'reason': 'Unclosed '+dropped+' tag; content after it is not shown or indexed'})
    return issues


# CSS deliberately excludes URLs, imports, escapes and browser extensions. Basic
# typography/table formatting survives; Qt does not implement browser layout CSS.
def clean_style(value):
    allowed = {'color','background-color','font-family','font-size','font-weight','font-style',
               'text-align','text-decoration','white-space','vertical-align','margin','padding',
               'border','border-color','border-width','border-style','width','height'}
    result = []
    for declaration in value.split(';'):
        key, sep, val = declaration.partition(':')
        if sep and key.strip().lower() in allowed and re.fullmatch(r'[\w\s#.,%()"\'-]{1,200}', val) and not re.search(r'url|expression', val, re.I):
            result.append(key.strip()+':'+val)
    return ';'.join(result)


def clean_css(value):
    value = re.sub(r'/\*.*?\*/', '', value, flags=re.S)
    return '\n'.join(selector+'{'+clean_style(body)+'}' for selector,body in re.findall(r'([^{}]+)\{([^{}]*)\}', value)
                     if re.fullmatch(r'[\w\s.#,:>+*-]{1,200}', selector))


class StaticHTML(HTMLParser):
    TAGS = set('html head body title p div span br hr h1 h2 h3 h4 h5 h6 a b strong i em u s sub sup pre code blockquote ul ol li dl dt dd table thead tbody tfoot tr td th caption img center font'.split())
    DROP = DROP_TAGS
    def __init__(self, name, files):
        super().__init__(convert_charrefs=True)
        self.name, self.files = name, files
        self.output, self.sections, self.words = [], [], []
        self.blocked = []
        self.heading = 0
        self.style = None
        self.known_anchors = References(decode(files[name])).anchors
        self.new_section('')
        self.feed(decode(files[name]))
        self.sections[-1]['text'] = ' '.join(self.words)
        # A drop tag or <style> still open at EOF means the parser swallowed every
        # later tag and its text. Report it so the page is not silently truncated.
        if self.blocked:
            self.unclosed = self.blocked[-1]
        elif self.style is not None:
            self.unclosed = 'style'
        else:
            self.unclosed = None
    def new_section(self, anchor):
        if self.sections:
            self.sections[-1]['text'] = ' '.join(self.words)
        self.words = []
        self.sections.append(dict(path=self.name, anchor=anchor, text=''))
    def handle_starttag(self, tag, attrs):
        if tag == 'style' and not self.blocked:
            self.style = [];return
        if self.blocked:
            if tag in self.DROP: self.blocked.append(tag)
            return
        if tag in self.DROP:
            if tag not in ('embed',): self.blocked.append(tag)
            return
        values = dict(attrs)
        if tag == 'link' and values.get('rel','').lower() == 'stylesheet':
            try:
                path,_ = resolve(self.name, values.get('href',''))
                if path in self.files and path.lower().endswith('.css'):
                    self.output.append('<style>'+escape(clean_css(decode(self.files[path])))+'</style>')
            except ValueError: pass
            return
        if tag not in self.TAGS: return
        anchor = values.get('id') or values.get('name')
        if re.fullmatch('h[1-6]', tag) and not anchor:
            self.heading += 1
            anchor = 'openwrench-section-'+str(self.heading)
            while anchor in self.known_anchors:
                self.heading += 1;anchor = 'openwrench-section-'+str(self.heading)
        if anchor:
            self.new_section(anchor)
            self.output.append('<a name="'+escape(anchor,quote=True)+'"></a>')
        clean = []
        for key, value in attrs:
            if not value: continue
            if key in ('id','name'):
                clean.append(('name',value))
            elif key == 'style': clean.append((key,clean_style(value)))
            elif key in ('class','title','alt','align','valign','colspan','rowspan','width','height','border','cellpadding','cellspacing'):
                clean.append((key,value[:500]))
            elif (tag,key) in (('a','href'),('img','src')):
                try:
                    target,anchor = resolve(self.name,value)
                    clean.append((key,'bundle:/'+quote(target,safe='/')+('#'+quote(anchor,safe='') if anchor else '')))
                except ValueError: pass
        self.output.append('<'+tag+''.join(' '+k+'="'+escape(v,quote=True)+'"' for k,v in clean)+'>')
    def handle_endtag(self, tag):
        if tag == 'style' and self.style is not None:
            self.output.append('<style>'+clean_css(''.join(self.style))+'</style>');self.style=None;return
        if self.blocked:
            if tag == self.blocked[-1]: self.blocked.pop()
        elif tag in self.TAGS:
            self.output.append('</'+tag+'>')
    def handle_data(self, value):
        if self.style is not None:
            self.style.append(value);return
        if not self.blocked:
            self.words.append(value.strip())
            self.output.append(escape(value))


def index(files):
    sections = []
    names = sorted(n for n in files if PurePosixPath(n).suffix.lower() in HTML)
    names.sort(key=lambda n: (PurePosixPath(n).name.lower() not in ('index.html','index.htm'), n.count('/'), n))
    for name in names:
        sections.extend(StaticHTML(name, files).sections)
    if any(len(s['anchor'])>500 for s in sections):
        raise ValueError('HTML anchor exceeds 500 characters.')
    if not sections or len(sections) > 5000 or sum(len(s['text'].encode('utf-8')) for s in sections) > 20*1024*1024:
        raise ValueError('HTML indexing limit exceeded.')
    return sections


def safe_svg(content):
    """Whitelist original static geometry. No entities, URLs, CSS or animation."""
    from xml.etree import ElementTree as ET
    if len(content)>1024*1024:
        raise ValueError('SVG exceeds the static renderer limit.')
    value = content.decode('utf-8-sig')
    if '<!' in value:
        raise ValueError('SVG declarations are blocked.')
    root = ET.fromstring(value)
    tags = {'svg','g','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','defs','title','desc'}
    attrs = {'width','height','viewBox','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','d','points','transform',
             'fill','stroke','stroke-width','opacity','font-size','font-family','text-anchor'}
    for element in root.iter():
        if element.tag.split('}')[-1] not in tags:
            raise ValueError('Unsupported active or linked SVG element.')
        for key,value in list(element.attrib.items()):
            if key not in attrs or re.search(r'url|[\\<>]',value,re.I):
                del element.attrib[key]
    return ET.tostring(root)

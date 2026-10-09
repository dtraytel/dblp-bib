"""BibTeX generation from dblp records, and the optional substitutions.

An entry is a dict {'type', 'key', 'fields': [(name, value)], 'plain': bool}. Entries generated from
dblp have plain (Unicode) values, which are escaped for LaTeX at the end; entries parsed from an
existing .bib file have LaTeX values. All substitutions work on both kinds.
"""

import re
import unicodedata

DEFAULT_SERIES_MAP = '''Lecture Notes in Computer Science = LNCS
Lecture Notes in Artificial Intelligence = LNAI
Lecture Notes in Business Information Processing = LNBIP
Lecture Notes in Networks and Systems = LNNS
Communications in Computer and Information Science = CCIS
Leibniz International Proceedings in Informatics = LIPIcs
Leibniz International Proceedings in Informatics (LIPIcs) = LIPIcs
Electronic Proceedings in Theoretical Computer Science = EPTCS
Electronic Notes in Theoretical Computer Science = ENTCS
CEUR Workshop Proceedings = CEUR-WS
IFIP Advances in Information and Communication Technology = IFIP AICT
Kalpa Publications in Computing = Kalpa
EPiC Series in Computing = EPiC'''

DEFAULT_OPTIONS = {
    'series_abbrev': True,          # Lecture Notes in Computer Science -> LNCS (series_map)
    'series_map': DEFAULT_SERIES_MAP,
    'booktitle': 'clean',           # keep | clean | acronym
    'strip_words': 'International',
    'full_years': True,             # POPL '20, MFCS'91, RTA-87 -> POPL 2020, MFCS 1991, RTA 1987 in conference names
    'url_doi': 'dedupe',            # keep | dedupe (drop the url if it is the doi link) | prefer_doi (drop the url if there is a doi)
    'drop_dblp_meta': True,         # timestamp, biburl, bibsource
    'drop_fields': '',              # comma-separated, e.g. "editor, isbn"
    'latex': True,                  # non-ASCII characters as LaTeX commands
    'protect_caps': True,           # {HOL}, {LaTeX}
    'abbrev_names': False,          # J. C. Blanchette
    'key_style': 'dblp',            # dblp | short | authoryear
    'keep_keys': True,              # keep the keys of entries of a loaded .bib file when updating them from dblp
    'keep_name_spellings': True,    # names in a loaded .bib file that dblp writes without accents keep their spelling
    'uniform_layout': False,        # write entries from a loaded .bib file in the same layout as the generated ones
    'normalize_foreign': False,     # apply the substitutions also to entries that do not come from dblp
    'custom_rules': '',             # lines "field: regex => replacement"; field * = all
}

FIELD_ORDER = ('author', 'editor', 'title', 'booktitle', 'journal', 'series', 'volume', 'number', 'pages',
               'school', 'publisher', 'year', 'url', 'doi', 'eprinttype', 'eprint', 'isbn', 'timestamp', 'biburl', 'bibsource')
PROTECTED = {'title', 'booktitle'}       # the fields bibliography styles may change the case of
BIBTYPE = {'article': 'article', 'inproceedings': 'inproceedings', 'proceedings': 'proceedings', 'book': 'book',
           'incollection': 'incollection', 'phdthesis': 'phdthesis', 'mastersthesis': 'mastersthesis', 'data': 'misc'}

SUB, SUP, END = '', '', ''      # markers for <sub>/<sup> in titles


def opts_with_defaults(o):
    d = dict(DEFAULT_OPTIONS)
    d.update({k: v for k, v in (o or {}).items() if k in DEFAULT_OPTIONS})
    return d


# --------------------------------------------------------------------------- from dblp

def strip_number(name):
    return re.sub(r'\s+\d{4}$', '', name)


def title_of(rec):
    xml = rec['extra'].get('title_xml')
    if xml:
        import html
        s = re.sub(r'<sub>(.*?)</sub>', SUB + r'\1' + END, xml)
        s = re.sub(r'<sup>(.*?)</sup>', SUP + r'\1' + END, s)
        s = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s))).strip()
    else:
        s = rec['title'] or ''
    if s.endswith('.') and not s.endswith('..'):
        s = s[:-1]
    return s


def venue_acronym(rec):
    v = rec.get('venue') or ''
    return re.sub(r'\s*\(\d+\)$', '', v).strip() or None


def from_dblp(rec, xref=None):
    """The dblp-style BibTeX entry of a record (xref: its crossref proceedings/book, if any)."""
    t, ex = rec['type'], rec['extra']
    xex = xref['extra'] if xref else {}
    f = []
    if rec['authors']:
        f.append(('author', [strip_number(a) for a in rec['authors']]))
    editors = rec['editors'] or (xref['editors'] if xref and t in ('inproceedings', 'incollection') else [])
    if editors:
        f.append(('editor', [strip_number(a) for a in editors]))
    f.append(('title', title_of(rec)))
    if t == 'article':
        f.append(('journal', rec['venue']))
        f += [('volume', rec['volume']), ('number', rec['number']), ('pages', rec['pages'])]
    elif t in ('inproceedings', 'incollection'):
        f.append(('booktitle', title_of(xref) if xref else rec['venue']))
        f.append(('series', ex.get('series') or xex.get('series')))
        f.append(('volume', rec['volume'] or (xref or {}).get('volume')))
        f.append(('pages', rec['pages']))
        f.append(('publisher', ex.get('publisher') or xex.get('publisher')))
    elif t in ('proceedings', 'book'):
        f += [('series', ex.get('series')), ('volume', rec['volume']), ('publisher', ex.get('publisher'))]
    elif t in ('phdthesis', 'mastersthesis'):
        f += [('school', ex.get('school')), ('publisher', ex.get('publisher'))]
    elif t == 'data':
        f.append(('publisher', ex.get('publisher') or rec['venue']))
    f.append(('year', str(rec['year']) if rec['year'] else None))
    ees = ex.get('ee') or []
    f.append(('url', ees[0] if ees else None))
    f.append(('doi', rec['doi']))
    if rec['venue'] == 'CoRR' and (rec['volume'] or '').startswith('abs/'):
        f += [('eprinttype', 'arXiv'), ('eprint', rec['volume'][4:])]
    if t in ('proceedings', 'book'):
        f.append(('isbn', ex.get('isbn')))
    if rec.get('mdate'):
        f.append(('timestamp', rec['mdate']))
    f += [('biburl', f"https://dblp.org/rec/{rec['key']}.bib"),
          ('bibsource', 'dblp computer science bibliography, https://dblp.org')]
    return {'type': BIBTYPE.get(t, 'misc'), 'key': 'DBLP:' + rec['key'], 'plain': True,
            'fields': [(k, v) for k, v in f if v], 'acronym': venue_acronym(xref or rec) if t != 'article' else None,
            'year': rec['year'], 'dblp': rec['key']}


# --------------------------------------------------------------------------- substitutions

MONTHS = (r'(?:January|February|March|April|May|June|July|August|September|October|November|December|'
          r'Jan\.|Feb\.|Mar\.|Apr\.|Jun\.|Jul\.|Aug\.|Sep\.|Sept\.|Oct\.|Nov\.|Dec\.)')
_units = 'First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth'
ORDINAL = (r'(?:\d+(?:st|nd|rd|th)|(?:(?:Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Eighty|Ninety)[- ]?(?:%s))|'
           r'(?:%s|Tenth|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|Sixteenth|Seventeenth|Eighteenth|'
           r'Nineteenth|Twentieth|Thirtieth|Fortieth|Fiftieth|Sixtieth|Seventieth|Eightieth|Ninetieth|Hundredth))') % (_units, _units)
SEP_RE = re.compile(r'(,\s+|\s+--?\s+|\s+–\s+)')
BARE_RE = re.compile(r'^(?:Annual\s+)?(?:Joint\s+)?(?:Conference|Workshops?|Symposium|Colloquium|Congress|Meeting|'
                     r'Proceedings|Conference and Workshops?)$', re.I)


def unbrace(s):
    return re.sub(r'[{}]', '', s).strip()


def _acronym_index(parts, acr):
    for i, t in enumerate(parts):
        u = unbrace(t)
        words = u.split()
        if not words or len(words) > 4:
            continue
        if acr and re.match(r'%s(?![\w])' % re.escape(acr), u) and re.search(r'\d', u):
            return i
    if acr and acr in [unbrace(t) for t in parts]:
        return [unbrace(t) for t in parts].index(acr)
    for i, t in enumerate(parts):
        u = unbrace(t)
        words = u.split()
        if (words and len(words) <= 4 and re.search(r'\d', u) and sum(c.isupper() for c in words[0]) >= 2
                and not re.search(MONTHS, u) and not re.match(r'^(?:19|20)\d\d$', u)):
            return i
    return None


def _location_like(t):
    u = unbrace(t)
    words = u.split()
    return (0 < len(words) <= 4 and not re.search(r'\d', u) and not BARE_RE.search(u)
            and all(w[:1].isupper() or w in ('&', 'and') for w in words))


def _clean_part(t, strip_words):
    t = re.sub(r'^(?:Proceedings|Proc\.)\s+(?:of\s+)?(?:the\s+)?', '', t.strip(), flags=re.I)
    t = re.sub(r'^(?:19|20)\d\d\s+', '', t)
    t = re.sub(r'^%s\s+' % ORDINAL, '', t, flags=re.I)
    t = re.sub(r'^(?:19|20)\d\d\s+', '', t)
    for w in strip_words:
        t = re.sub(r'(?<![\w-])%s(?![\w-])\s*' % re.escape(w), '', t)
    return re.sub(r'\s+', ' ', t).strip(' ,')


def clean_booktitle(s, mode='clean', acr=None, year=None, strip_words=('International',)):
    """Shorten a proceedings title.

    clean:   "10th International Conference on Interactive Theorem Proving, ITP 2019, Portland, OR, USA, ..."
             -> "Conference on Interactive Theorem Proving, ITP 2019"
    acronym: -> "ITP 2019"
    """
    if mode == 'keep' or not s:
        return s
    m = re.match(r'^([^:,]{2,40}?):\s+(.+)$', s)      # ACM style: "HAI '21: International Conference on ..."
    if m and _acronym_index([m.group(1)], acr) == 0 and _acronym_index(SEP_RE.split(m.group(2))[0::2], acr) is None:
        if mode == 'acronym':
            return m.group(1).strip()
        rest = clean_booktitle(m.group(2), 'clean', acr, year, strip_words)
        return f'{rest}, {m.group(1).strip()}' if rest else m.group(1).strip()
    pieces = SEP_RE.split(s)
    parts, seps = pieces[0::2], [''] + pieces[1::2]
    idx = _acronym_index(parts, acr)
    if mode == 'acronym':
        if idx is not None:
            return parts[idx].strip()
        if acr and year:
            return f'{acr} {year}'
    if idx == 0 and len(parts) > 1 and mode == 'clean':     # "KR 2000, Principles of ..."
        rest = clean_booktitle(''.join(pieces[2:]), 'clean', acr, year, strip_words)
        return f'{rest}, {parts[0].strip()}' if rest else parts[0].strip()
    if idx is not None:
        keep = range(idx + 1)
    else:
        cut = len(parts)
        for i, t in enumerate(parts):
            if i and (re.search(MONTHS, t) or re.fullmatch(r'(?:Proceedings|Part [IVX]+|Vol(?:ume|\.) ?\d+)', unbrace(t), re.I)):
                cut = i
                break
        while cut > 1 and _location_like(parts[cut - 1]):
            if re.match(r'(?:and|&)\s', unbrace(parts[cut - 1])):    # "X, Y, and Z": still the name
                break
            cut -= 1
        keep = range(cut)
    out = []
    for i in keep:
        t = _clean_part(parts[i], strip_words)
        if not t or BARE_RE.match(unbrace(t)):
            continue
        if out:
            out.append(seps[i] if i else ', ')
        out.append(t)
    return ''.join(out) or s


def parse_map(text):
    m = {}
    for line in (text or '').splitlines():
        if '=' in line:
            a, b = line.split('=', 1)
            if a.strip():
                m[a.strip().lower()] = b.strip()
    return m


def parse_rules(text):
    rules = []
    for line in (text or '').splitlines():
        m = re.match(r'^\s*([\w*]+)\s*:\s*(.*?)\s*=>\s?(.*)$', line)
        if m:
            try:
                rules.append((m.group(1).lower(), re.compile(m.group(2)), m.group(3)))
            except re.error:
                pass
    return rules


def abbreviate_name(name):
    words = name.split()
    if len(words) < 2:
        return name
    particles = {'van', 'von', 'de', 'der', 'den', 'da', 'del', 'della', 'di', 'du', 'dos', 'das', 'le', 'la', 'ten', 'ter', 'zu'}
    suffix = []
    if words[-1] in ('Jr.', 'Sr.', 'II', 'III', 'IV'):
        suffix = [words.pop()]
    i = len(words) - 1
    while i > 1 and words[i - 1] in particles:
        i -= 1
    first = []
    for w in words[:i]:
        if w.endswith('.') and len(w) <= 3:
            first.append(w)
        else:
            first.append('-'.join(p[0] + '.' for p in w.split('-') if p))
    return ' '.join(first + words[i:] + suffix)


def _year_int(year):
    m = re.search(r'\d{4}', str(year or ''))
    return int(m.group(0)) if m else None


def full_years(s, year=None):
    """Two-digit years in a conference name as four digits: POPL '20, MFCS'91 -> POPL 2020, MFCS 1991.

    ACR-yy and ACR-yyyy become "ACR yyyy" only if they match the year of the entry
    (CADE-28 is the 28th CADE, not 2028)."""
    y = _year_int(year)

    def century(yy):
        if y:
            c = y - y % 100 + yy
            return min((c - 100, c, c + 100), key=lambda v: abs(v - y))
        import datetime
        return 2000 + yy if 2000 + yy <= datetime.date.today().year + 1 else 1900 + yy

    s = re.sub(r"([\w}])\s*['\u2019](\d{2})(?![\w'\u2019])", lambda m: f'{m.group(1)} {century(int(m.group(2)))}', s)
    if y:
        s = re.sub(r'([A-Za-z}])-(\d{2}|(?:19|20)\d{2})(?![\w-])',
                   lambda m: f'{m.group(1)} {y}' if int(m.group(2)) in (y, y % 100) else m.group(0), s)
    return s


def _doi_of(value):
    m = re.search(r'(10\.\d{4,}/\S+)', unbrace(value or ''))
    return m.group(1) if m else None


def transform(entry, o):
    """Apply the substitutions selected in the options o (a full options dict)."""
    fields = list(entry['fields'])
    get = lambda n: next((v for k, v in fields if k == n), None)
    smap = parse_map(o['series_map']) if o['series_abbrev'] else {}
    strip_words = [w.strip() for w in re.split(r'[,\n]', o['strip_words'] or '') if w.strip()]
    out = []
    for k, v in fields:
        if smap and k in ('series', 'journal', 'booktitle') and isinstance(v, str):
            v = smap.get(unbrace(v).lower(), v)
        if (k == 'booktitle' or (k == 'title' and entry['type'] == 'proceedings')) and isinstance(v, str) \
                and not (smap and v in smap.values()):
            if o['full_years']:
                v = full_years(v, entry.get('year'))
            v = clean_booktitle(v, o['booktitle'], entry.get('acronym'), entry.get('year'), strip_words)
        if o['full_years'] and k == 'year' and isinstance(v, str) and re.fullmatch(r"\s*['\u2019]?\d{2}\s*", v):
            v = str(full_years("x '" + v.strip().lstrip("'\u2019"))[2:])
        if o['abbrev_names'] and entry['plain'] and k in ('author', 'editor'):
            v = [abbreviate_name(a) for a in v]
        out.append((k, v))
    fields = out
    doi, url = get('doi'), get('url')
    if doi and url and o['url_doi'] != 'keep':
        same = re.match(r'^\{?https?://(?:dx\.)?doi\.org/', url, re.I) and (_doi_of(url) or '').lower() == (_doi_of(doi) or '').lower()
        if same or o['url_doi'] == 'prefer_doi':
            fields = [(k, v) for k, v in fields if k != 'url']
    drop = {f.strip().lower() for f in (o['drop_fields'] or '').split(',') if f.strip()}
    if o['drop_dblp_meta']:
        drop |= {'timestamp', 'biburl', 'bibsource'}
    fields = [(k, v) for k, v in fields if k not in drop]
    return dict(entry, fields=fields)


# --------------------------------------------------------------------------- LaTeX

ACCENTS = {'̀': '`', '́': "'", '̂': '^', '̃': '~', '̄': '=', '̆': 'u', '̇': '.',
           '̈': '"', '̊': 'r', '̋': 'H', '̌': 'v', '̣': 'd', '̧': 'c', '̨': 'k',
           '̱': 'b'}
CHARS = {'ø': r'{\o}', 'Ø': r'{\O}', 'ß': r'{\ss}', 'ł': r'{\l}', 'Ł': r'{\L}', 'æ': r'{\ae}', 'Æ': r'{\AE}',
         'œ': r'{\oe}', 'Œ': r'{\OE}', 'å': r'{\aa}', 'Å': r'{\AA}', 'ı': r'{\i}', 'đ': r'{\dj}', 'Đ': r'{\DJ}',
         'þ': r'{\th}', 'Þ': r'{\TH}', 'ð': r'{\dh}', 'Ð': r'{\DH}', '–': '--', '—': '---', '“': '``',
         '”': "''", '‘': '`', '’': "'", '…': r'{\ldots}', ' ': '~', '´': "'",
         '¡': '!`', '¿': '?`', '§': r'{\S}', '©': r'{\copyright}', '°': r'{\textdegree}', '·': r'{\textperiodcentered}',
         '×': r'{\(\times\)}', '±': r'{\(\pm\)}', '→': r'{\(\rightarrow\)}', '←': r'{\(\leftarrow\)}',
         '↔': r'{\(\leftrightarrow\)}', '⇒': r'{\(\Rightarrow\)}', '∀': r'{\(\forall\)}', '∃': r'{\(\exists\)}',
         '∈': r'{\(\in\)}', '⊆': r'{\(\subseteq\)}', '⊂': r'{\(\subset\)}', '∧': r'{\(\wedge\)}', '∨': r'{\(\vee\)}',
         '¬': r'{\(\neg\)}', '≤': r'{\(\leq\)}', '≥': r'{\(\geq\)}', '≠': r'{\(\neq\)}', '∞': r'{\(\infty\)}',
         '√': r'{\(\surd\)}', '∑': r'{\(\sum\)}', '∘': r'{\(\circ\)}', '⋅': r'{\(\cdot\)}', '′': r"{\('\)}",
         '∅': r'{\(\emptyset\)}', '⊢': r'{\(\vdash\)}', '⊨': r'{\(\models\)}', '∪': r'{\(\cup\)}', '∩': r'{\(\cap\)}',
         '≡': r'{\(\equiv\)}', '≈': r'{\(\approx\)}', 'ℕ': r'{\(\mathbb{N}\)}', 'ℝ': r'{\(\mathbb{R}\)}',
         'ℤ': r'{\(\mathbb{Z}\)}', 'ℚ': r'{\(\mathbb{Q}\)}', 'µ': r'{\(\mu\)}'}
GREEK_CAPS = {'Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma', 'Upsilon', 'Phi', 'Psi', 'Omega'}
ESCAPES = {'&': r'\&', '%': r'\%', '#': r'\#', '_': r'\_', '$': r'\$', '{': r'\{', '}': r'\}',
           '~': r'{\textasciitilde}', '^': r'{\textasciicircum}', '\\': r'{\textbackslash}'}


def _char(c, latex):
    if c in ESCAPES:
        return ESCAPES[c]
    if ord(c) < 128 or not latex:
        return c
    if c in CHARS:
        return CHARS[c]
    name = unicodedata.name(c, '')
    if name.startswith('GREEK'):
        letter = name.split()[-1].capitalize().replace('Lamda', 'Lambda')
        if 'SMALL' in name:
            return r'{\(\%s\)}' % letter.lower().replace('final', 'varsigma')
        if letter in GREEK_CAPS:
            return r'{\(\%s\)}' % letter
    d = unicodedata.normalize('NFD', c)
    if len(d) > 1 and all(m in ACCENTS for m in d[1:]):
        s = r'\i' if d[0] == 'i' else (r'\j' if d[0] == 'j' else d[0])
        for m in d[1:]:
            s = '\\%s{%s}' % (ACCENTS[m], s)
        return '{' + s + '}'
    return c


def latex_text(s, latex=True, protect=False):
    def esc(t):
        out = []
        math = False
        for c in t:
            if c in (SUB, SUP):
                out.append('{\\(' + ('_' if c == SUB else '^') + '{')
                math = True
            elif c == END:
                out.append('}\\)}')
                math = False
            else:
                out.append(_char(c, latex) if not (math and c.isalnum()) else c)
        return ''.join(out)
    if not protect:
        return esc(s)
    out = []
    for tok in re.split(r'(\s+)', s):
        m = re.match(r'^([(\["\'“]*)(.*?)([)\]"\'”.,:;!?]*)$', tok, re.S)
        lead, core, trail = m.groups()
        if SUB in core or SUP in core or any(re.search(r'\w.*?[A-Z]', part) for part in core.split('-')):
            out.append(esc(lead) + '{' + esc(core) + '}' + esc(trail))
        else:
            out.append(esc(tok))
    return ''.join(out)


def to_latex(entry, o):
    """Turn plain values into LaTeX (no-op for entries parsed from a .bib file)."""
    if not entry['plain']:
        return entry
    fields = []
    for k, v in entry['fields']:
        if isinstance(v, list):
            v = ' and '.join(latex_text(a, o['latex']) for a in v)
        elif k in ('url', 'doi', 'biburl', 'eprint', 'isbn'):
            pass
        elif k == 'pages':
            v = re.sub(r'\s*-+\s*', '--', v)
        else:
            v = latex_text(v, o['latex'], o['protect_caps'] and k in PROTECTED)
        fields.append((k, v))
    return dict(entry, fields=fields, plain=False)


def apply_rules(entry, o):
    rules = parse_rules(o['custom_rules'])
    if not rules:
        return entry
    fields = []
    for k, v in entry['fields']:
        for f, rx, rep in rules:
            if f in ('*', k) and isinstance(v, str):
                try:
                    v = rx.sub(rep, v)
                except (re.error, IndexError):
                    pass
        if v != '' or k not in [f for f, _, _ in rules]:
            fields.append((k, v))
    return dict(entry, fields=fields)


def render(entry):
    exprs = entry.get('exprs') or {}            # macros and # concatenations from a .bib file: written as they are
    lines = [f"@{entry['type']}{{{entry['key']},"]
    for k, v in entry['fields']:
        lines.append(f'  {k.ljust(12)} = {v},' if k in exprs else f'  {k.ljust(12)} = {{{v}}},')
    if len(lines) > 1:
        lines[-1] = lines[-1][:-1]
    lines.append('}')
    return '\n'.join(lines)


VERBATIM_FIELDS = {'url', 'doi', 'file', 'pdf', 'eprint', 'abstract', 'verbatim'}


def relayout(entry):
    """An entry parsed from a .bib file in the layout of the generated ones: two spaces of indentation, aligned
    "=", values in braces, runs of white space in values as one space. Values, field order and macros stay."""
    fields = [(k, v if k in VERBATIM_FIELDS or not isinstance(v, str) else re.sub(r'\s+', ' ', v).strip())
              for k, v in entry['fields']]
    return render(dict(entry, fields=fields))


def make_key(rec, style):
    if style == 'short':
        return rec['key'].rsplit('/', 1)[-1]
    if style == 'authoryear':
        people = rec['authors'] or rec['editors']
        last = strip_number(people[0]).split()[-1] if people else 'anon'
        if last in ('Jr.', 'Sr.', 'II', 'III') and len(strip_number(people[0]).split()) > 1:
            last = strip_number(people[0]).split()[-2]
        stop = {'a', 'an', 'the', 'on', 'of', 'for', 'in', 'to', 'and', 'with', 'towards', 'toward', 'from', 'by', 'at'}
        word = next((w for w in re.findall(r'[^\W\d_]+', rec['title'] or '') if len(w) > 2 and w.lower() not in stop), '')
        ascii_ = lambda s: unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
        return re.sub(r'[^A-Za-z0-9]', '', ascii_(last)).lower() + str(rec['year'] or '') + ascii_(word).lower()
    return 'DBLP:' + rec['key']


def dblp_bibtex(rec, xref, o, key=None, spellings=None):
    """Full pipeline for a dblp record: generated entry, substitutions, LaTeX, custom rules.

    spellings: {fold_name(name): name}, preferred spellings of names (see name_spellings)."""
    e = from_dblp(rec, xref)
    e['key'] = key or make_key(rec, o['key_style'])
    if spellings:
        e['fields'] = [(k, [spellings.get(fold_name(n), n) for n in v] if k in ('author', 'editor') else v)
                       for k, v in e['fields']]
    e = apply_rules(to_latex(transform(e, o), o), o)
    return e


def normalize_foreign(entry, o):
    """Substitutions on an entry parsed from a .bib file (values are LaTeX)."""
    e = dict(entry, plain=False, acronym=None,
             year=next((v for k, v in entry['fields'] if k == 'year'), None))
    return apply_rules(transform(e, o), o)


# --------------------------------------------------------------------------- names from .bib files

LATEX_SYMBOLS = {'o': 'ø', 'O': 'Ø', 'ss': 'ß', 'l': 'ł', 'L': 'Ł', 'ae': 'æ', 'AE': 'Æ', 'oe': 'œ', 'OE': 'Œ',
                 'aa': 'å', 'AA': 'Å', 'i': 'ı', 'j': 'ȷ', 'dj': 'đ', 'DJ': 'Đ', 'th': 'þ', 'TH': 'Þ', 'dh': 'ð', 'DH': 'Ð'}
LATEX_ACCENTS = {cmd: mark for mark, cmd in ACCENTS.items()}


def latex_to_unicode(s):
    """Sr{\\dj}an Krsti{\\'c}, Sr\\dj{}an Krsti\\'{c} -> Srđan Krstić (for the usual accent commands)."""
    s = re.sub(r'\\(%s)(?![A-Za-z])\s*(?:\{\})?' % '|'.join(sorted(LATEX_SYMBOLS, key=len, reverse=True)),
               lambda m: LATEX_SYMBOLS[m.group(1)], s)
    accent = lambda m: (m.group(2) or m.group(3)).replace('ı', 'i').replace('ȷ', 'j') + LATEX_ACCENTS[m.group(1)]
    for _ in range(3):                                   # nested accents
        s = re.sub(r"""\\([`'^"~=.])\s*(?:\{\s*([^{}\\])\s*\}|([^\s{}\\]))""", accent, s)
        s = re.sub(r'\\([uvHcdkrb])(?:\s*\{\s*([^{}\\])\s*\}|\s+([^\s{}\\]))', accent, s)
    s = re.sub(r'(?<!\\)~', ' ', s.replace('{', '').replace('}', ''))
    return unicodedata.normalize('NFC', re.sub(r'\s+', ' ', s)).strip()


def fold_name(name):
    """A name without accents, case and punctuation, for comparing spellings: Srđan Krstić -> srdankrstic."""
    s = unicodedata.normalize('NFKD', strip_number(name))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    for a, b in (('đ', 'd'), ('Đ', 'd'), ('ð', 'd'), ('ø', 'o'), ('Ø', 'o'), ('ł', 'l'), ('Ł', 'l'), ('æ', 'ae'),
                 ('œ', 'oe'), ('ß', 'ss'), ('ı', 'i'), ('þ', 'th')):
        s = s.replace(a, b)
    return re.sub(r'[^a-z]', '', s.lower())


def split_names(value):
    """The names of a BibTeX author/editor field (split at 'and' outside braces)."""
    names, depth, start = [], 0, 0
    for m in re.finditer(r'[{}]|\s+and\s+', value):
        if m.group(0) == '{':
            depth += 1
        elif m.group(0) == '}':
            depth -= 1
        elif depth == 0:
            names.append(value[start:m.start()])
            start = m.end()
    names.append(value[start:])
    return [n.strip() for n in names if n.strip() and n.strip().lower() != 'others']


def plain_name(bibname):
    """A BibTeX name as "First Last" in Unicode: Krsti{\\'c}, Sr{\\dj}an -> Srđan Krstić."""
    parts = [p.strip() for p in latex_to_unicode(bibname).split(',')]
    if len(parts) == 2:
        return f'{parts[1]} {parts[0]}'.strip()
    if len(parts) == 3:
        return f'{parts[2]} {parts[0]} {parts[1]}'.strip()
    return parts[0]


def name_spellings(entries):
    """{fold_name(name): name} for the names with accents in parsed .bib entries."""
    out = {}
    for e in entries:
        for k, v in e['fields']:
            if k in ('author', 'editor') and isinstance(v, str):
                for n in split_names(v):
                    p = plain_name(n)
                    if any(ord(c) > 127 for c in p) and fold_name(p):
                        out.setdefault(fold_name(p), p)
    return out

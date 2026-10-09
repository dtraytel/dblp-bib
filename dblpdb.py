"""The local DBLP database: import of the XML dump into SQLite (with an FTS5 index) and queries.

The dump (https://dblp.org/xml/dblp.xml.gz) is ISO-8859-1 with HTML entities; it is read line by
line, like the dblp tools do, which is much faster than a full XML parser and needs no DTD.
"""

import calendar
import gzip
from contextlib import closing
import html
import io
import json
import os
import re
import sqlite3
import time
import urllib.request

DUMP_URL = 'https://dblp.org/xml/dblp.xml.gz'
TYPES = ('article', 'inproceedings', 'proceedings', 'book', 'incollection', 'phdthesis', 'mastersthesis', 'data')
# Fields kept in the JSON column (the others have columns of their own).
EXTRA_FIELDS = ('series', 'publisher', 'isbn', 'school', 'note', 'month', 'address', 'chapter', 'publnr', 'url')

SCHEMA = '''
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pubs(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, type TEXT NOT NULL, publtype TEXT, title TEXT,
  authors TEXT, editors TEXT, venue TEXT, year INTEGER, volume TEXT, number TEXT, pages TEXT,
  crossref TEXT, doi TEXT, mdate TEXT, extra TEXT);
'''
INDEXES = '''
CREATE UNIQUE INDEX pubs_key ON pubs(key);
CREATE INDEX pubs_crossref ON pubs(crossref) WHERE crossref IS NOT NULL;
CREATE INDEX pubs_doi ON pubs(doi COLLATE NOCASE) WHERE doi IS NOT NULL;
CREATE INDEX pubs_venue ON pubs(venue, volume);
CREATE VIRTUAL TABLE fts USING fts5(title, authors, editors, venue, year, content='pubs', content_rowid='id',
                                    tokenize='unicode61 remove_diacritics 2');
INSERT INTO fts(fts) VALUES('rebuild');
'''
COLUMNS = 'id, key, type, publtype, title, authors, editors, venue, year, volume, number, pages, crossref, doi, mdate, extra'

_open_re = re.compile(r'^<(%s)\s([^>]*)>' % '|'.join(TYPES))
_close_re = re.compile(r'(</(?:%s|www)>)' % '|'.join(TYPES))
_field_re = re.compile(r'^<(\w+)(\s[^>]*)?>(.*)</\1>\s*$', re.S)
_attr_re = re.compile(r'(\w+)="([^"]*)"')
_tag_re = re.compile(r'<[^>]+>')
_doi_re = re.compile(r'^https?://(?:dx\.)?doi\.org/(10\..+)$', re.I)


def _text(raw):
    return re.sub(r'\s+', ' ', html.unescape(_tag_re.sub('', raw))).strip()


def _finish(rec):
    """Turn the collected fields of one XML record into a database row."""
    f = rec['f']
    title_raw = f.get('title', [''])[0]
    extra = {k: html.unescape(f[k][0]).strip() for k in EXTRA_FIELDS if k in f}
    if '<' in title_raw:                    # <sub>, <sup>, <i>, <tt>: kept for the BibTeX
        extra['title_xml'] = title_raw
    ees = [html.unescape(e) for e in f.get('ee', [])]
    if ees:
        extra['ee'] = ees
    doi = next((m.group(1) for e in ees if (m := _doi_re.match(e))), None)
    year = f.get('year', [''])[0]
    venue = f.get('journal') or f.get('booktitle')
    if rec['type'] == 'data' and not venue:
        venue = f.get('publisher')
    return (rec['key'], rec['type'], rec['attrs'].get('publtype'), _text(title_raw),
            '\n'.join(_text(a) for a in f.get('author', [])) or None,
            '\n'.join(_text(a) for a in f.get('editor', [])) or None,
            _text(venue[0]) if venue else None,
            int(year) if year.isdigit() else None,
            *(_text(f[k][0]) if k in f else None for k in ('volume', 'number', 'pages', 'crossref')),
            doi, rec['attrs'].get('mdate'), json.dumps(extra, ensure_ascii=False) if extra else None)


def iter_records(path, progress=None):
    """Yield database rows for the publications in the dump (www/person records are skipped)."""
    raw = open(path, 'rb')
    size = os.fstat(raw.fileno()).st_size or 1
    stream = gzip.GzipFile(fileobj=raw) if path.endswith('.gz') else raw
    rec, pending, n = None, None, 0
    with raw, io.TextIOWrapper(stream, encoding='latin-1', newline='\n') as text:
        for line in text:
            if '</' in line and '><' in line:
                pieces = _close_re.sub('\\1\n', line).split('\n')
            else:
                pieces = (line,)
            for s in pieces:
                if pending is not None:     # a field spanning several lines
                    pending += ' ' + s
                    if '</%s>' % pending_name not in s:
                        continue
                    s, pending = pending, None
                if not s.startswith('<'):
                    continue
                if s.startswith('</'):
                    if rec is not None and s.startswith('</%s>' % rec['type']) and 'title' in rec['f']:
                        yield _finish(rec)
                        n += 1
                        if progress and n % 100000 == 0:
                            progress(n, raw.tell() / size)
                    rec = None
                    continue
                m = _open_re.match(s)
                if m:
                    rec = {'type': m.group(1), 'attrs': dict(_attr_re.findall(m.group(2))), 'f': {}}
                    rec['key'] = rec['attrs'].get('key', '')
                    continue
                if rec is None:
                    continue
                m = _field_re.match(s)
                if m:
                    rec['f'].setdefault(m.group(1), []).append(m.group(3))
                else:
                    mo = re.match(r'^<(\w+)[\s>]', s)
                    if mo and mo.group(1) not in TYPES and mo.group(1) != 'www' and '</%s>' % mo.group(1) not in s:
                        pending, pending_name = s.rstrip('\n'), mo.group(1)
    if progress:
        progress(n, 1.0)


def build(dump, db_path, progress=None):
    """Build a fresh database from the dump; it replaces db_path only when complete."""
    tmp = db_path + '.building'
    for f in (tmp, tmp + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    say = progress or (lambda phase, frac, msg: None)
    con = sqlite3.connect(tmp)
    try:
        con.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-400000;' + SCHEMA)
        t0 = time.time()
        batch, total = [], 0
        sql = 'INSERT INTO pubs(key, type, publtype, title, authors, editors, venue, year, volume, number, pages, crossref, doi, mdate, extra) VALUES (%s)' % ','.join('?' * 15)
        for row in iter_records(dump, lambda n, frac: say('import', frac, f'{n:,} records read')):
            batch.append(row)
            if len(batch) >= 20000:
                con.executemany(sql, batch)
                total += len(batch)
                batch = []
        con.executemany(sql, batch)
        total += len(batch)
        con.commit()
        say('index', 0.0, f'{total:,} records; building the search index')
        con.executescript(INDEXES)
        st = os.stat(dump)
        meta = {'source': os.path.basename(dump), 'source_mtime': str(int(st.st_mtime)), 'source_size': str(st.st_size),
                'built': str(int(time.time())), 'records': str(total), 'build_seconds': str(int(time.time() - t0))}
        con.executemany('INSERT INTO meta VALUES (?, ?)', meta.items())
        con.commit()
        con.execute('PRAGMA journal_mode=DELETE')
        con.close()
        os.replace(tmp, db_path)
        say('done', 1.0, f'{total:,} records indexed')
        return total
    except BaseException:
        con.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def download(dest, progress=None):
    """Download the current dump to dest (via a temporary file)."""
    tmp = dest + '.part'
    req = urllib.request.Request(DUMP_URL, headers={'User-Agent': 'dblp-bib-tool'})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as out:
        total = int(r.headers.get('Content-Length') or 0)
        got = 0
        while chunk := r.read(1 << 20):
            out.write(chunk)
            got += len(chunk)
            if progress:
                progress('download', got / total if total else 0.0, f'{got / 2**20:,.0f} of {total / 2**20:,.0f} MB')
        lm = r.headers.get('Last-Modified')
    os.replace(tmp, dest)
    t = _http_time(lm)
    if t:
        os.utime(dest, (t, t))
    return dest


def _http_time(value):
    """Seconds since the epoch for an HTTP date (always GMT)."""
    try:
        return calendar.timegm(time.strptime(value, '%a, %d %b %Y %H:%M:%S GMT')) if value else None
    except ValueError:
        return None


def remote_info():
    """Last-Modified and size of the dump on dblp.org."""
    req = urllib.request.Request(DUMP_URL, method='HEAD', headers={'User-Agent': 'dblp-bib-tool'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return {'modified': _http_time(r.headers.get('Last-Modified')), 'size': int(r.headers.get('Content-Length') or 0)}


def is_current(mtime, size, remote):
    """Whether a dump with this modification time and size is the one on dblp.org (or a newer one).

    An hour of slack: earlier versions of this tool stored the time off by the daylight-saving offset."""
    if not mtime or not remote.get('modified'):
        return False
    mtime = int(mtime)
    if mtime > remote['modified'] + 3600:
        return True
    return abs(mtime - remote['modified']) <= 3600 and int(size or 0) == remote.get('size')


# --------------------------------------------------------------------------- queries

class DB:
    def __init__(self, path):
        self.path = path

    def exists(self):
        return os.path.exists(self.path)

    def connect(self):
        con = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def meta(self):
        if not self.exists():
            return {}
        with closing(self.connect()) as con:
            return dict(con.execute('SELECT k, v FROM meta').fetchall())

    @staticmethod
    def row(r):
        if r is None:
            return None
        d = dict(r)
        d['authors'] = d['authors'].split('\n') if d['authors'] else []
        d['editors'] = d['editors'].split('\n') if d['editors'] else []
        d['extra'] = json.loads(d['extra']) if d['extra'] else {}
        return d

    def get(self, key, con=None):
        own = con is None
        con = con or self.connect()
        try:
            return self.row(con.execute(f'SELECT {COLUMNS} FROM pubs WHERE key = ?', (key,)).fetchone())
        finally:
            if own:
                con.close()

    def get_many(self, keys):
        with closing(self.connect()) as con:
            return {k: self.get(k, con) for k in keys}

    def by_doi(self, doi, con):
        return [self.row(r) for r in con.execute(f'SELECT {COLUMNS} FROM pubs WHERE doi = ? COLLATE NOCASE', (doi,))]

    def by_arxiv(self, arxiv_id, con):
        return [self.row(r) for r in con.execute(f"SELECT {COLUMNS} FROM pubs WHERE venue = 'CoRR' AND volume = ?",
                                                 ('abs/' + arxiv_id,))]

    def search(self, q, offset=0, limit=50, types=None, year_from=None, year_to=None, sort='relevance'):
        """Full-text search, dblp style: all words must occur (as prefixes), in any field."""
        match = fts_query(q)
        if not match:
            return {'results': [], 'more': False}
        where, args = ['fts MATCH ?'], [match]
        conds = [CATEGORIES[t] for t in (types or []) if t in CATEGORIES]
        if conds:
            where.append('(%s)' % ' OR '.join(conds))
        if year_from:
            where.append('p.year >= ?')
            args.append(int(year_from))
        if year_to:
            where.append('p.year <= ?')
            args.append(int(year_to))
        order = 'p.year DESC, p.id DESC' if sort == 'year' else 'bm25(fts, 8.0, 6.0, 2.0, 3.0, 2.0), p.year DESC'
        sql = (f'SELECT {", ".join("p." + c for c in COLUMNS.split(", "))} FROM fts JOIN pubs p ON p.id = fts.rowid '
               f'WHERE {" AND ".join(where)} ORDER BY {order} LIMIT ? OFFSET ?')
        with closing(self.connect()) as con:
            try:
                rows = con.execute(sql, args + [limit + 1, offset]).fetchall()
            except sqlite3.OperationalError as e:
                return {'results': [], 'more': False, 'error': str(e)}
        res = [self.row(r) for r in rows[:limit]]
        return {'results': res, 'more': len(rows) > limit}

    def author(self, name):
        """All publications of one author (exact dblp name, including a disambiguation number)."""
        words = re.findall(r'\w+', name)
        if not words:
            return []
        match = '{authors editors} : "%s"' % ' '.join(words)
        with closing(self.connect()) as con:
            rows = con.execute(f'SELECT {", ".join("p." + c for c in COLUMNS.split(", "))} FROM fts JOIN pubs p ON p.id = fts.rowid '
                               'WHERE fts MATCH ? ORDER BY p.year DESC, p.id DESC', (match,)).fetchall()
        out = []
        for r in rows:
            d = self.row(r)
            if name in d['authors'] or name in d['editors']:
                out.append(d)
        return out

    def toc(self, key):
        """Table of contents: the papers of a proceedings volume, or of a journal volume."""
        with closing(self.connect()) as con:
            rec = self.get(key, con)
            if rec is None:
                return None, []
            if rec['type'] in ('proceedings', 'book'):
                rows = con.execute(f'SELECT {COLUMNS} FROM pubs WHERE crossref = ? ORDER BY id', (key,)).fetchall()
                return rec, [self.row(r) for r in rows]
            if rec['crossref']:
                return self.toc(rec['crossref'])
            if rec['type'] == 'article' and rec['venue']:
                rows = con.execute(f'SELECT {COLUMNS} FROM pubs WHERE venue = ? AND volume IS ? AND type = ? ORDER BY id',
                                   (rec['venue'], rec['volume'], 'article')).fetchall()
                return {'key': None, 'type': 'volume', 'title': f"{rec['venue']}, Volume {rec['volume']}" if rec['volume'] else rec['venue'],
                        'year': rec['year']}, [self.row(r) for r in rows]
            return rec, [rec]

    def title_candidates(self, title, con, limit=30):
        """Records whose title contains the (significant) words of title."""
        words = [w for w in re.findall(r'\w+', title.lower()) if len(w) > 2][:12]
        if not words:
            return []
        match = 'title : (%s)' % ' AND '.join('"%s"' % w for w in words)
        try:
            rows = con.execute(f'SELECT {", ".join("p." + c for c in COLUMNS.split(", "))} FROM fts JOIN pubs p ON p.id = fts.rowid '
                               'WHERE fts MATCH ? LIMIT ?', (match, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self.row(r) for r in rows]

    def same_title(self, title, con):
        """Records with the same normalised title (e.g. the published version of a CoRR paper)."""
        n = norm_title(title)
        return [r for r in self.title_candidates(title, con, 60) if norm_title(r['title']) == n]


INFORMAL = "IFNULL(p.publtype, '') LIKE '%informal%'"
CATEGORIES = {
    'journal': f"(p.type = 'article' AND NOT {INFORMAL})",
    'conference': f"(p.type = 'inproceedings' AND NOT {INFORMAL})",
    'informal': INFORMAL,
    'editorship': "p.type = 'proceedings'",
    'book': "p.type = 'book' AND NOT " + INFORMAL,
    'part': "p.type = 'incollection'",
    'thesis': "p.type IN ('phdthesis', 'mastersthesis')",
    'data': "p.type = 'data'",
}

FIELD_ALIASES = {'author': 'authors', 'authors': 'authors', 'a': 'authors', 'editor': 'editors', 'title': 'title',
                 't': 'title', 'venue': 'venue', 'v': 'venue', 'year': 'year', 'y': 'year'}


def fts_query(q):
    """dblp-like query syntax: words (prefix match), "phrases", field:word, -word (exclusion)."""
    parts, neg = [], []
    for m in re.finditer(r'(-)?(?:(\w+):)?(?:"([^"]*)"|(\S+))', q):
        sign, field, phrase, word = m.groups()
        col = FIELD_ALIASES.get((field or '').lower())
        if field and not col:               # not a field name: "a:b" is a word
            word = (field + ':' + (word or phrase or ''))
        if phrase is not None:
            toks = re.findall(r'\w+', phrase)
            term = '"%s"' % ' '.join(toks) if toks else ''
        else:
            toks = re.findall(r'\w+', word or '')
            if not toks:
                continue
            # "Isabelle/HOL" becomes the phrase "isabelle hol"; the last word is a prefix
            term = '"%s"' % ' '.join(toks) + ('*' if len(toks[-1]) >= 2 or len(toks) > 1 else '')
        if not term:
            continue
        if col:
            term = f'{col} : {term}'
        (neg if sign else parts).append(term)
    if not parts:
        return ''
    s = ' AND '.join(parts)
    for t in neg:
        s += ' NOT ' + t
    return s


def strip_latex(s):
    s = re.sub(r'\\[a-zA-Z]+\s*', '', s or '')
    return re.sub(r'[{}\\"\'`^~]', '', s)


def norm_title(t):
    import unicodedata
    t = unicodedata.normalize('NFKD', strip_latex(t)).lower()
    return ' '.join(re.findall(r'[a-z0-9]+', t))

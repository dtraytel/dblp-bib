#!/usr/bin/env python3
"""dblp-bib: a dblp-like web interface to a local dblp dump for clicking together .bib files.

  ./dblp-bib.py                         start the web interface (http://127.0.0.1:8737)
  ./dblp-bib.py update                  download the dump from dblp.org into the data directory, if it changed, and build the database
  ./dblp-bib.py build                   rebuild the database from the dump in the data directory
  ./dblp-bib.py build --dump FILE       build the database from another copy of the dump (dblp.xml or dblp.xml.gz)
"""

import argparse
from contextlib import closing
import difflib
import json
import mimetypes
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bibgen
import bibparse
import dblpdb

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, 'static')


class App:
    def __init__(self, data_dir):
        self.data = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.db = dblpdb.DB(os.path.join(data_dir, 'dblp.sqlite'))
        self.state_path = os.path.join(data_dir, 'state.json')
        self.lock = threading.Lock()
        self.job = {'running': False}

    # ------------------------------------------------------------------ state (options + working bib)

    def load_state(self):
        try:
            with open(self.state_path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_state(self, st):
        with self.lock:
            tmp = self.state_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, self.state_path)

    # ------------------------------------------------------------------ dump update job

    def local_dump(self):
        """The dump kept in the data directory (as downloaded), if any."""
        for f in ('dblp.xml.gz', 'dblp.xml'):
            p = os.path.join(self.data, f)
            if os.path.exists(p):
                return p
        return None

    def dump_info(self):
        p = self.local_dump()
        if not p:
            return None
        st = os.stat(p)
        return {'name': os.path.basename(p), 'mtime': int(st.st_mtime), 'size': st.st_size}

    def update(self, progress, force=False):
        """Download the dump if dblp.org has a newer one than the database's, and rebuild the database.

        Returns 'current' if the database is already built from the current dump, else 'built'."""
        try:
            remote = dblpdb.remote_info()
            meta = self.db.meta() if self.db.exists() else {}
            if not force and dblpdb.is_current(meta.get('source_mtime'), meta.get('source_size'), remote):
                return 'current'
            local = self.dump_info()
            if force or not (local and dblpdb.is_current(local['mtime'], local['size'], remote)):
                dblpdb.download(os.path.join(self.data, 'dblp.xml.gz'), progress)
        except urllib.error.URLError as e:
            raise ConnectionError(f'cannot reach dblp.org ({getattr(e, "reason", e)}); check the internet connection') from None
        dblpdb.build(self.local_dump(), self.db.path, progress)
        return 'built'

    def start_job(self, mode, force=False):
        with self.lock:
            if self.job.get('running'):
                return False
            self.job = {'running': True, 'phase': 'start', 'frac': 0.0, 'msg': 'starting', 'started': time.time(), 'mode': mode}
        threading.Thread(target=self._run_job, args=(mode, force), daemon=True).start()
        return True

    def _progress(self, phase, frac, msg):
        self.job.update(phase=phase, frac=frac, msg=msg)

    def _run_job(self, mode, force=False):
        try:
            if mode == 'download':
                self._progress('check', 0.0, 'asking dblp.org for the date of the current dump')
                if self.update(self._progress, force) == 'current':
                    self.job.update(running=False, phase='current', frac=1.0, finished=time.time(),
                                    msg='The database is built from the current dump on dblp.org; nothing was downloaded.')
                    return
            else:
                path = self.local_dump()
                if not path:
                    raise FileNotFoundError('no dump in the data directory; download one first')
                dblpdb.build(path, self.db.path, self._progress)
            self.job.update(running=False, phase='done', frac=1.0, finished=time.time())
        except ConnectionError as e:                # no traceback for network trouble
            self.job.update(running=False, phase='error', msg=f'Download failed: {e}')
        except FileNotFoundError as e:
            self.job.update(running=False, phase='error', msg=str(e))
        except Exception as e:
            traceback.print_exc()
            self.job.update(running=False, phase='error', msg=f'{type(e).__name__}: {e}')

    # ------------------------------------------------------------------ rendering

    def record_with_xref(self, key, con):
        rec = self.db.get(key, con)
        xref = self.db.get(rec['crossref'], con) if rec and rec['crossref'] else None
        return rec, xref

    def published_versions(self, rec, con):
        """Non-CoRR records with the same title as a CoRR record."""
        if not is_informal(rec):
            return []
        return [summary(r) for r in self.db.same_title(rec['title'], con)
                if r['key'] != rec['key'] and not is_informal(r)
                and r['type'] not in ('proceedings', 'data') and overlap(r['authors'], rec['authors']) > 0.4]

    def render(self, items, opts):
        o = bibgen.opts_with_defaults(opts)
        out, used = [], {}
        spellings = {}
        if o['keep_name_spellings']:                # names dblp writes without accents: as in the loaded .bib file
            texts = [it['raw'] for it in items if it.get('kind') == 'raw'] + [it['orig'] for it in items if it.get('orig')]
            spellings = bibgen.name_spellings(p for t in texts for p in bibparse.parse(t) if p['kind'] == 'entry')
        with closing(self.db.connect()) as con:
            for it in items:
                r = {'id': it.get('id'), 'kind': it.get('kind')}
                try:
                    if it['kind'] == 'dblp':
                        rec, xref = self.record_with_xref(it['dblp'], con)
                        if rec is None:
                            r.update(text=f"% dblp record {it['dblp']} not found in the database", error='not found')
                        else:
                            e = bibgen.dblp_bibtex(rec, xref, o, it.get('key') or None, spellings)
                            if not it.get('key'):
                                e['key'] = unique_key(e['key'], used)
                            used[e['key']] = True
                            r.update(text=bibgen.render(e), key=e['key'], type=e['type'], fields=e['fields'],
                                     record=summary(rec), upgrade=self.published_versions(rec, con))
                    elif it['kind'] == 'raw':
                        parsed = bibparse.parse(it['raw'])
                        e = next((p for p in parsed if p['kind'] == 'entry'), None)
                        if e is None:
                            r.update(text=it['raw'])
                        else:
                            used[e['key']] = True
                            text = it['raw']
                            # what the substitutions would change; written out only if they apply to all entries
                            ne = bibgen.normalize_foreign(e, o)
                            if ne['fields'] != e['fields']:
                                r['subst'] = {'text': bibgen.render(ne), 'key': e['key'], 'type': e['type'], 'fields': ne['fields']}
                                if o['normalize_foreign']:
                                    text = r['subst']['text']
                            if o['uniform_layout']:
                                text = bibgen.relayout(ne if o['normalize_foreign'] else e)
                            # fields: the entry as in the file, which is what is compared with dblp
                            r.update(text=text, key=e['key'], type=e['type'], fields=e['fields'])
                            if it.get('match'):
                                rec, xref = self.record_with_xref(it['match'], con)
                                if rec:
                                    alt = bibgen.dblp_bibtex(rec, xref, o, e['key'] if o['keep_keys'] else None, spellings)
                                    r['alt'] = {'text': bibgen.render(alt), 'key': alt['key'], 'type': alt['type'],
                                                'fields': alt['fields'], 'record': summary(rec),
                                                'same': same_entry(e, alt)}
                    else:
                        r.update(text=it.get('raw', ''))
                except Exception as ex:
                    traceback.print_exc()
                    r.update(text=it.get('raw') or '', error=str(ex))
                out.append(r)
        bib = '\n\n'.join(x['text'].strip() for x in out if x.get('text', '').strip()) + '\n'
        return {'items': out, 'bib': bib}

    # ------------------------------------------------------------------ matching .bib entries against dblp

    def match(self, raw):
        parsed = bibparse.parse(raw)
        e = next((p for p in parsed if p['kind'] == 'entry'), None)
        if e is None:
            return {'candidates': []}
        f = lambda n: bibparse.field(e, n) or ''
        found = {}

        def add(rec, how, base):
            if rec and rec['type'] != 'data':
                prev = found.get(rec['key'])
                if not prev or prev[2] < base:
                    found[rec['key']] = (rec, how, base)

        with closing(self.db.connect()) as con:
            if e['key'].startswith('DBLP:'):
                add(self.db.get(e['key'][5:], con), 'dblp key', 100)
            m = re.search(r'dblp\.org/rec/(.+?)(?:\.bib|\.html)?$', f('biburl'))
            if m:
                add(self.db.get(m.group(1), con), 'dblp key', 100)
            doi = bibgen._doi_of(f('doi')) or (bibgen._doi_of(f('url')) if 'doi.org' in f('url') else None)
            if doi:
                for rec in self.db.by_doi(doi, con):
                    add(rec, 'doi', 90)
            ax = f('eprint') if f('archiveprefix').lower() == 'arxiv' or f('eprinttype').lower() == 'arxiv' else ''
            ax = ax or (re.search(r'arxiv\.org/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$', f('url')) or [None, ''])[1]
            ax = ax or (re.search(r'(?:abs/|arXiv:)(\d{4}\.\d{4,5})', f('volume') + ' ' + f('journal') + ' ' + f('note')) or [None, ''])[1]
            if ax:
                for rec in self.db.by_arxiv(re.sub(r'v\d+$', '', ax), con):
                    add(rec, 'arXiv id', 80)
            title = f('title')
            if title:
                nt = dblpdb.norm_title(title)
                for rec in self.db.title_candidates(dblpdb.strip_latex(title), con, 60):
                    rt = dblpdb.norm_title(rec['title'])
                    if rt == nt:
                        add(rec, 'title', 60)
                    elif difflib.SequenceMatcher(None, rt, nt).ratio() > 0.9:
                        add(rec, 'similar title', 40)
            bib_last = bib_lastnames(f('author') or f('editor'))
            try:
                year = int(re.search(r'\d{4}', f('year')).group(0))
            except AttributeError:
                year = None
            cands = []
            for rec, how, base in found.values():
                score = base + 30 * overlap_names(bib_last, rec['authors'] or rec['editors'])
                if year and rec['year']:
                    score += 10 if rec['year'] == year else (4 if abs(rec['year'] - year) <= 1 else 0)
                if rec['type'] == 'proceedings' and e['type'] != 'proceedings':
                    score -= 30
                cands.append(dict(summary(rec), how=how, score=round(score, 1)))
            cands.sort(key=lambda c: -c['score'])
            # an arXiv/CoRR entry: offer the published version first
            if cands and is_informal(cands[0]):
                best = self.db.get(cands[0]['key'], con)
                for p in self.published_versions(best, con):
                    if p['key'] not in found:
                        cands.insert(0, dict(p, how='published version of ' + cands[0]['key'], score=cands[0]['score']))
                    else:
                        c = next(c for c in cands if c['key'] == p['key'])
                        cands.remove(c)
                        cands.insert(0, dict(c, how=c['how'] + ', published version'))
        best = cands[0]['key'] if cands and cands[0]['score'] >= 70 else None
        return {'candidates': cands[:8], 'best': best}


# ---------------------------------------------------------------------- helpers

def summary(rec):
    return {k: rec.get(k) for k in ('key', 'type', 'publtype', 'title', 'authors', 'editors', 'venue', 'year',
                                    'volume', 'number', 'pages', 'crossref', 'doi')} | {
        'ee': (rec.get('extra') or {}).get('ee', [])[:3], 'series': (rec.get('extra') or {}).get('series')}


def is_informal(rec):
    return rec.get('venue') == 'CoRR' or 'informal' in (rec.get('publtype') or '')


def ascii_lower(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()


def lastname(name):
    w = bibgen.strip_number(name).split()
    if len(w) > 1 and w[-1] in ('Jr.', 'Sr.', 'II', 'III'):
        w = w[:-1]
    return re.sub(r'[^a-z]', '', ascii_lower(w[-1])) if w else ''


def bib_lastnames(s):
    out = []
    for a in re.split(r'\s+and\s+', dblpdb.strip_latex(s)):
        a = a.strip()
        if not a or a.lower() == 'others':
            continue
        last = a.split(',')[0] if ',' in a else a.split()[-1]
        out.append(re.sub(r'[^a-z]', '', ascii_lower(last.split()[-1] if last.split() else last)))
    return out


def overlap_names(bib_last, dblp_names):
    if not bib_last or not dblp_names:
        return 0.0
    d = {lastname(n) for n in dblp_names}
    return sum(1 for b in bib_last if b in d) / max(len(bib_last), len(dblp_names))


def overlap(a, b):
    return overlap_names([lastname(x) for x in a], b) if a and b else 1.0


def unique_key(key, used):
    if key not in used:
        return key
    for c in 'bcdefghijklmnopqrstuvwxyz':
        if key + c not in used:
            return key + c
    return key + '_'


def same_entry(raw_entry, gen_entry):
    norm = lambda v: re.sub(r'\s+', ' ', str(v)).strip()
    a = {k: norm(v) for k, v in raw_entry['fields']}
    b = {k: norm(v) for k, v in gen_entry['fields']}
    return a == b and raw_entry['type'] == gen_entry['type'] and raw_entry['key'] == gen_entry['key']


def choose_bib_file(save=False, name='references.bib'):
    """Ask for a .bib file with the desktop's open or save-as dialog.

    Returns its path, '' if cancelled, None if there is no dialog to show."""
    name = os.path.basename(name or '') or 'references.bib'
    if sys.platform == 'darwin' and shutil.which('osascript'):
        ask = ('choose file name with prompt "Save the .bib file" default name (item 1 of argv)' if save
               else 'choose file with prompt "Open a .bib file" of type {"bib"}')
        cmd = ['osascript', '-e', 'on run argv', '-e', 'tell me to activate', '-e', f'return POSIX path of ({ask})',
               '-e', 'end run', name]
    elif shutil.which('zenity'):
        cmd = ['zenity', '--file-selection', '--file-filter=*.bib'] + (
            ['--save', '--confirm-overwrite', '--title=Save the .bib file', f'--filename={name}'] if save else ['--title=Open a .bib file'])
    elif shutil.which('kdialog'):
        cmd = (['kdialog', '--getsavefilename', os.path.join(os.path.expanduser('~'), name), '*.bib'] if save
               else ['kdialog', '--getopenfilename', os.path.expanduser('~'), '*.bib'])
    else:
        return None
    r = subprocess.run(cmd, capture_output=True, text=True)
    path = r.stdout.strip() if r.returncode == 0 else ''
    if save and path and not path.endswith('.bib'):
        path += '.bib'
    return path


# ---------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    app: App = None
    server_version = 'dblp-bib'

    def log_message(self, fmt, *args):
        if os.environ.get('DBLPBIB_LOG'):
            super().log_message(fmt, *args)

    def _host_ok(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost', '[::1]')

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {'error': 'forbidden host'})
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        app = self.app
        try:
            if u.path in ('/', '/index.html'):
                return self._static('index.html')
            if u.path.startswith('/static/'):
                return self._static(u.path[len('/static/'):])
            if not u.path.startswith('/api/'):
                return self._send(404, {'error': 'not found'})
            ep = u.path[5:]
            if ep == 'status':
                return self._send(200, {'db': app.db.meta() if app.db.exists() else None, 'job': app.job,
                                        'dump': app.dump_info(),
                                        'defaults': bibgen.DEFAULT_OPTIONS})
            if ep == 'state':
                return self._send(200, app.load_state())
            if not app.db.exists() and ep in ('search', 'author', 'toc', 'record'):
                return self._send(503, {'error': 'no database yet: import a dump on the Data page'})
            if ep == 'search':
                types = [t for t in q.get('types', '').split(',') if t]
                return self._send(200, app.db.search(q.get('q', ''), int(q.get('offset', 0)), min(int(q.get('limit', 50)), 500),
                                                     types, q.get('from') or None, q.get('to') or None, q.get('sort', 'relevance')))
            if ep == 'author':
                return self._send(200, {'name': q.get('name'), 'results': app.db.author(q.get('name', ''))})
            if ep == 'toc':
                head, recs = app.db.toc(q.get('key', ''))
                return self._send(200, {'head': head and summary(head) if head and head.get('key') else head, 'results': recs})
            if ep == 'record':
                rec = app.db.get(q.get('key', ''))
                return self._send(200 if rec else 404, rec or {'error': 'not found'})
            if ep == 'remote':
                try:
                    return self._send(200, dblpdb.remote_info())
                except Exception as e:
                    return self._send(502, {'error': str(e)})
            return self._send(404, {'error': 'unknown endpoint'})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': str(e)})

    def do_POST(self):
        # JSON only: browsers cannot send that cross-origin without a (never answered) preflight
        if not self._host_ok() or not (self.headers.get('Content-Type') or '').startswith('application/json'):
            return self._send(403, {'error': 'forbidden'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, {'error': 'bad json'})
        app = self.app
        ep = urllib.parse.urlparse(self.path).path[5:]
        try:
            if ep == 'state':
                app.save_state(body)
                return self._send(200, {'ok': True})
            if ep == 'parse':
                return self._send(200, {'items': bibparse.parse(body.get('text', ''))})
            if not app.db.exists() and ep in ('render', 'match'):
                return self._send(503, {'error': 'no database yet: import a dump on the Data page'})
            if ep == 'render':
                return self._send(200, app.render(body.get('items', []), body.get('options')))
            if ep == 'match':
                return self._send(200, {'matches': {it['id']: app.match(it['raw']) for it in body.get('items', [])}})
            if ep == 'file/choose':
                path = choose_bib_file(bool(body.get('save')), body.get('name'))
                return self._send(200, {'unsupported': True} if path is None else {'path': path})
            if ep == 'file/load':
                path = os.path.abspath(os.path.expanduser(body.get('path', '')))
                if not path.endswith('.bib'):
                    return self._send(400, {'error': 'only .bib files'})
                with open(path, encoding='utf-8', errors='replace') as f:
                    return self._send(200, {'path': path, 'text': f.read()})
            if ep == 'file/save':
                path = os.path.abspath(os.path.expanduser(body.get('path', '')))
                if not path.endswith('.bib'):
                    return self._send(400, {'error': 'only .bib files'})
                backup = None
                if os.path.exists(path) and body.get('backup', True):
                    backup = path + '.bak'
                    with open(path, 'rb') as src, open(backup, 'wb') as dst:
                        dst.write(src.read())
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(body.get('text', ''))
                os.replace(tmp, path)
                return self._send(200, {'path': path, 'backup': backup})
            if ep == 'update':
                mode = body.get('mode')
                if mode not in ('download', 'rebuild'):
                    return self._send(400, {'error': 'mode must be download or rebuild'})
                if mode == 'rebuild' and not app.local_dump():
                    return self._send(400, {'error': 'no dump in the data directory; download one first'})
                ok = app.start_job(mode, bool(body.get('force')))
                return self._send(200 if ok else 409, {'ok': ok, 'job': app.job})
            return self._send(404, {'error': 'unknown endpoint'})
        except FileNotFoundError as e:
            return self._send(404, {'error': str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': str(e)})

    def _static(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC + os.sep) or not os.path.isfile(path):
            return self._send(404, {'error': 'not found'})
        with open(path, 'rb') as f:
            data = f.read()
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'):
            ctype += '; charset=utf-8'
        return self._send(200, data, ctype)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind looks up the host name (getfqdn), which can hang without DNS
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', nargs='?', default='serve', choices=['serve', 'build', 'update'])
    ap.add_argument('--data', default=os.environ.get('DBLPBIB_DATA', os.path.join(HERE, 'data')),
                    help='directory for the database and state (default: ./data)')
    ap.add_argument('--dump', metavar='FILE', help='build: use this dump instead of the one in the data directory')
    ap.add_argument('--force', action='store_true', help='update: download the dump even if it has not changed')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT') or 8737), help='default: $PORT or 8737')
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    app = App(args.data)
    if args.command in ('build', 'update'):
        last = [0.0]

        def progress(phase, frac, msg):
            if time.time() - last[0] > 2 or phase != 'import':
                last[0] = time.time()
                print(f'\r{phase}: {frac * 100:5.1f}%  {msg}'.ljust(70), end='' if phase in ('import', 'download') else '\n',
                      file=sys.stderr, flush=True)
        if args.command == 'update':
            try:
                if app.update(progress, args.force) == 'current':
                    print('dblp-bib: the database is built from the current dump on dblp.org; nothing to do '
                          '(--force downloads it anyway)', file=sys.stderr)
            except ConnectionError as e:
                sys.exit(f'dblp-bib: {e}')
            return
        dump = args.dump or app.local_dump()
        if not dump:
            sys.exit('no dump in the data directory: use "update" to download one, or "build --dump FILE"')
        dblpdb.build(dump, app.db.path, progress)
        return
    Handler.app = app
    srv = Server(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}/'
    print(f'dblp-bib: serving {url}{"" if app.db.exists() else " (no database yet)"}', file=sys.stderr)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

"""Tests: python3 -m unittest discover tests"""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import bibgen  # noqa: E402
import bibparse  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location('dblpbib', os.path.join(os.path.dirname(HERE), 'dblp-bib.py'))
dblpbib = importlib.util.module_from_spec(_spec)      # the main script; its name is not a module name
_spec.loader.exec_module(dblpbib)
import dblpdb  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixture.xml')


class Booktitles(unittest.TestCase):
    CASES = [
        ('10th International Conference on Interactive Theorem Proving, ITP 2019, Portland, OR, USA, September 9-12, 2019', 'ITP',
         'Conference on Interactive Theorem Proving, ITP 2019', 'ITP 2019'),
        ('Automated Deduction - CADE 28 - 28th International Conference on Automated Deduction, Virtual Event, July 12-15, 2021, Proceedings', 'CADE',
         'Automated Deduction - CADE 28', 'CADE 28'),
        ('Tools and Algorithms for the Construction and Analysis of Systems - 25th International Conference, TACAS 2019, Held as Part of '
         'the European Joint Conferences on Theory and Practice of Software, ETAPS 2019, Prague, Czech Republic, April 6-11, 2019, Proceedings, Part I', 'TACAS',
         'Tools and Algorithms for the Construction and Analysis of Systems, TACAS 2019', 'TACAS 2019'),
        ('Proceedings of the 2019 ACM SIGSAC Conference on Computer and Communications Security, CCS 2019, London, UK, November 11-15, 2019', 'CCS',
         'ACM SIGSAC Conference on Computer and Communications Security, CCS 2019', 'CCS 2019'),
        ('Proceedings of the 8th ACM SIGPLAN International Conference on Certified Programs and Proofs, CPP 2019, Cascais, Portugal, January 14-15, 2019', 'CPP',
         'ACM SIGPLAN Conference on Certified Programs and Proofs, CPP 2019', 'CPP 2019'),
        ('Twenty-Third International Workshop on First-Order Theorem Proving, FTP 2023, Prague', None,
         'Workshop on First-Order Theorem Proving, FTP 2023', 'FTP 2023'),
        ('Proceedings of the Workshop on Foo Bar, Paris, France, May 3, 2019', None, 'Workshop on Foo Bar', 'Workshop on Foo Bar'),
        ('10th International Conference on Interactive Theorem Proving, {ITP} 2019, September 9-12, 2019, Portland, OR, {USA}', None,
         'Conference on Interactive Theorem Proving, {ITP} 2019', '{ITP} 2019'),
    ]

    def test_modes(self):
        for s, acr, clean, short in self.CASES:
            self.assertEqual(bibgen.clean_booktitle(s, 'clean', acr, 2019), clean, s)
            self.assertEqual(bibgen.clean_booktitle(s, 'acronym', acr, 2019), short, s)
            self.assertEqual(bibgen.clean_booktitle(s, 'keep', acr, 2019), s)

    def test_acm_prefix(self):
        for s, short, clean in [
            ("HAI '21: International Conference on Human-Agent Interaction, Virtual Event, Japan, November 9 - 11, 2021",
             'HAI 2021', 'Conference on Human-Agent Interaction, HAI 2021'),
            ("5G-MeMU '21: Proceedings of the 1st Workshop on 5G Measurements, Modeling, and Use Cases, Virtual Event, 23 August 2021",
             '5G-MeMU 2021', 'Workshop on 5G Measurements, Modeling, and Use Cases, 5G-MeMU 2021'),
            ("MobileHCI '21: 23rd International Conference on Mobile Human-Computer Interaction, Toulouse & Virtual Event, France, "
             "27 September 2021 - 1 October 2021", 'MobileHCI 2021', 'Conference on Mobile Human-Computer Interaction, MobileHCI 2021')]:
            s = bibgen.full_years(s, 2021)
            self.assertEqual(bibgen.clean_booktitle(s, 'acronym', None, 2021), short)
            self.assertEqual(bibgen.clean_booktitle(s, 'clean', None, 2021), clean)

    def test_full_years(self):
        for s, y, out in [("MFCS'91, Kazimierz Dolny", 1991, 'MFCS 1991, Kazimierz Dolny'),
                          ("CHI PLAY '20: The Annual Symposium", 2020, 'CHI PLAY 2020: The Annual Symposium'),
                          ('RTA-87, Bordeaux', 1987, 'RTA 1987, Bordeaux'),
                          ('ICAIDS-2023, Hyderabad', 2023, 'ICAIDS 2023, Hyderabad'),
                          ('Automated Deduction - CADE-28', 2021, 'Automated Deduction - CADE-28'),   # edition, not year
                          ("{POPL}'20 and the '20s, ESOP\u201919", 2020, '{POPL} 2020 and the \'20s, ESOP 2019'),
                          ("WMCSA '99", None, 'WMCSA 1999'), ("POPL '20", None, 'POPL 2020')]:
            self.assertEqual(bibgen.full_years(s, y), out)

    def test_strip_words(self):
        s = '36th Annual ACM/IEEE Symposium on Logic in Computer Science, LICS 2021, Rome, Italy, June 29 - July 2, 2021'
        self.assertEqual(bibgen.clean_booktitle(s, 'clean', 'LICS', 2021, ['International', 'Annual']),
                         'ACM/IEEE Symposium on Logic in Computer Science, LICS 2021')


class Latex(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(bibgen.latex_text('Gödel & Łukasiewicz: 100% λ', True), r'G{\"{o}}del \& {\L}ukasiewicz: 100\% {\(\lambda\)}')
        self.assertEqual(bibgen.latex_text('Gödel', False), 'Gödel')
        self.assertEqual(bibgen.latex_text('í', True), r"{\'{\i}}")

    def test_protect(self):
        self.assertEqual(bibgen.latex_text('A Proof in Isabelle/HOL (SAT) of Lower-Bound', True, True),
                         'A Proof in {Isabelle/HOL} ({SAT}) of Lower-Bound')

    def test_names(self):
        self.assertEqual(bibgen.abbreviate_name('Jasmin Christian Blanchette'), 'J. C. Blanchette')
        self.assertEqual(bibgen.abbreviate_name('Jan van den Brügge'), 'J. van den Brügge')
        self.assertEqual(bibgen.abbreviate_name('Jean-Pierre Jouannaud'), 'J.-P. Jouannaud')


class Parser(unittest.TestCase):
    TEXT = '''% comment
@string{lncs = "Lecture Notes in Computer Science"}
@InProceedings{a1,
  author = {F{\\"u}rer, Basil and Traytel, Dmitriy},
  title = "Quotients of {B}ounded Functors",
  series = lncs # { Vol.},
  year = 2020,
}
@article(b2, title={x}, journal = {J})
@broken{c3, title = {unbalanced
@misc{d4, note = {ok}}
'''

    def test_parse(self):
        items = bibparse.parse(self.TEXT)
        kinds = [(i['kind'], i.get('key')) for i in items]
        self.assertEqual(kinds, [('other', None), ('other', None), ('entry', 'a1'), ('entry', 'b2'), ('other', None), ('entry', 'd4')])
        a1 = items[2]
        self.assertEqual(a1['type'], 'inproceedings')
        self.assertEqual(bibparse.field(a1, 'title'), 'Quotients of {B}ounded Functors')
        self.assertEqual(bibparse.field(a1, 'series'), 'lncs # { Vol.}')
        self.assertEqual(bibparse.field(a1, 'year'), '2020')
        self.assertTrue(items[4].get('error'))
        self.assertEqual(bibparse.field(items[3], 'journal'), 'J')


class FtsQuery(unittest.TestCase):
    def test_query(self):
        self.assertEqual(dblpdb.fts_query('Isabelle/HOL author:traytel "bounded natural" -foo'),
                         '"Isabelle HOL"* AND authors : "traytel"* AND "bounded natural" NOT "foo"*')
        self.assertEqual(dblpdb.fts_query('a'), '"a"')
        self.assertEqual(dblpdb.fts_query('  '), '')


class Database(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = dblpbib.App(cls.tmp)
        n = dblpdb.build(FIXTURE, cls.app.db.path)
        assert n == 7, n

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_records(self):
        r = self.app.db.get('journals/test/Erdos99')
        self.assertEqual(r['authors'], ['Paul Erdős', 'Jan van den Brügge'])
        self.assertEqual(r['title'], 'On L1-Distances & 100% of the Isabelle/HOL Theories.')
        self.assertIsNone(self.app.db.get('homepages/00/1'))
        self.assertEqual(self.app.db.get('conf/cade/FurerLST20')['doi'], '10.1007/978-3-030-51054-1_4')

    def test_search(self):
        keys = lambda q, **kw: [r['key'] for r in self.app.db.search(q, **kw)['results']]
        self.assertEqual(set(keys('quotients functors')), {'conf/cade/FurerLST20', 'journals/corr/abs-2104-05348', 'journals/lmcs/FurerLST22'})
        self.assertEqual(keys('quotients', types=['informal']), ['journals/corr/abs-2104-05348'])
        self.assertEqual(keys('erdos'), ['journals/test/Erdos99'])             # diacritics folded
        self.assertEqual(keys('author:traytel year:2019'), ['conf/itp/BrunT19'])
        self.assertEqual(keys('quotients -corr', sort='year'), ['journals/lmcs/FurerLST22', 'conf/cade/FurerLST20'])
        self.assertEqual([r['key'] for r in self.app.db.author('Joshua Schneider 0001')][0], 'journals/lmcs/FurerLST22')
        head, toc = self.app.db.toc('conf/itp/BrunT19')
        self.assertEqual((head['key'], [r['key'] for r in toc]), ('conf/itp/2019', ['conf/itp/BrunT19']))

    def render(self, items, **opts):
        return self.app.render(items, opts)

    def test_render_defaults(self):
        res = self.render([{'id': 1, 'kind': 'dblp', 'dblp': 'conf/cade/FurerLST20'}])
        self.assertEqual(res['items'][0]['text'], '''@inproceedings{DBLP:conf/cade/FurerLST20,
  author       = {Basil F{\\"{u}}rer and Andreas Lochbihler and Joshua Schneider and Dmitriy Traytel},
  editor       = {Nicolas Peltier and Viorica Sofronie-Stokkermans},
  title        = {Quotients of Bounded Natural Functors},
  booktitle    = {Automated Reasoning, {IJCAR} 2020},
  series       = {LNCS},
  volume       = {12167},
  pages        = {58--78},
  publisher    = {Springer},
  year         = {2020},
  doi          = {10.1007/978-3-030-51054-1_4}
}''')

    def test_render_dblp_style(self):
        res = self.render([{'id': 1, 'kind': 'dblp', 'dblp': 'conf/itp/BrunT19'}], series_abbrev=False, booktitle='keep',
                          url_doi='keep', drop_dblp_meta=False, key_style='short')
        text = res['items'][0]['text']
        self.assertIn('@inproceedings{BrunT19,', text)
        self.assertIn('booktitle    = {10th International Conference on Interactive Theorem Proving, {ITP} 2019, Portland, {OR}, {USA}, September 9-12, 2019}', text)
        self.assertIn('url          = {https://doi.org/10.4230/LIPIcs.ITP.2019.10}', text)
        self.assertIn('biburl       = {https://dblp.org/rec/conf/itp/BrunT19.bib}', text)
        self.assertIn('editor       = {John Harrison and John O\'Leary and Andrew Tolmach}', text)

    def test_render_options(self):
        res = self.render([{'id': 1, 'kind': 'dblp', 'dblp': 'journals/test/Erdos99'},
                           {'id': 2, 'kind': 'dblp', 'dblp': 'conf/itp/BrunT19'},
                           {'id': 3, 'kind': 'dblp', 'dblp': 'conf/itp/BrunT19', 'key': 'mykey'}],
                          key_style='authoryear', abbrev_names=True, latex=False, booktitle='acronym', url_doi='prefer_doi',
                          drop_fields='editor, publisher', custom_rules='pages: -- => -\njournal: ^J\\. Test$ => Journal of Tests')
        e, b, c = [x['text'] for x in res['items']]
        self.assertIn('@article{erdos1999distances,', e)
        self.assertIn('author       = {P. Erdős and J. van den Brügge}', e)
        self.assertIn('title        = {On {L{\\(_{1}\\)}-Distances} \\& 100\\% of the {Isabelle/HOL} Theories}', e)
        self.assertIn('pages        = {1-10}', e)
        self.assertIn('journal      = {Journal of Tests}', e)
        self.assertIn('url          = {https://example.org/erdos99}', e)      # no doi: url stays
        self.assertIn('booktitle    = {{ITP} 2019}', b)
        self.assertNotIn('editor', b)
        self.assertNotIn('publisher', b)
        self.assertNotIn('url', b)
        self.assertIn('@inproceedings{mykey,', c)

    def test_match_and_upgrade(self):
        raw = '''@article{arxiv-bnf,
  author = {Basil F\\"urer and others},
  title = "Quotients of {B}ounded {N}atural {F}unctors",
  journal = {arXiv preprint}, eprint = {2104.05348}, archivePrefix = {arXiv}, year = {2021}
}'''
        m = self.app.match(raw)
        self.assertEqual(m['candidates'][0]['key'], 'journals/lmcs/FurerLST22')   # published version first
        self.assertIn('journals/corr/abs-2104-05348', [c['key'] for c in m['candidates']])
        res = self.render([{'id': 1, 'kind': 'raw', 'raw': raw, 'match': m['best']}])
        alt = res['items'][0]['alt']
        self.assertEqual(alt['key'], 'arxiv-bnf')                                 # citation key kept
        self.assertFalse(alt['same'])
        res = self.render([{'id': 1, 'kind': 'dblp', 'dblp': 'journals/corr/abs-2104-05348'}])
        self.assertEqual({u['key'] for u in res['items'][0]['upgrade']}, {'conf/cade/FurerLST20', 'journals/lmcs/FurerLST22'})

    def test_match_by_key_and_doi(self):
        self.assertEqual(self.app.match('@inproceedings{DBLP:conf/itp/BrunT19, title={x}}')['best'], 'conf/itp/BrunT19')
        m = self.app.match('@inproceedings{k, author={Brun, M. and Traytel, D.}, title={Generic ADS}, doi={10.4230/lipics.itp.2019.10}, year=2019}')
        self.assertEqual(m['best'], 'conf/itp/BrunT19')
        self.assertIsNone(self.app.match('@misc{w, title={Isabelle}, howpublished={web}}')['best'])

    def test_same_entry(self):
        gen = self.render([{'id': 1, 'kind': 'dblp', 'dblp': 'conf/itp/BrunT19', 'key': 'k'}])['items'][0]['text']
        res = self.render([{'id': 1, 'kind': 'raw', 'raw': gen, 'match': 'conf/itp/BrunT19'}])
        self.assertTrue(res['items'][0]['alt']['same'])

    def test_normalize_foreign(self):
        raw = '''@inproceedings{x,
  booktitle = {Proceedings of the 8th ACM SIGPLAN International Conference on Certified Programs and Proofs, {CPP} 2019, Cascais, Portugal, January 14-15, 2019},
  series = {Lecture Notes in Computer Science},
  url = {https://doi.org/10.1145/1},
  doi = {10.1145/1},
  bibsource = {dblp}
}'''
        item = {'id': 1, 'kind': 'raw', 'raw': raw}
        self.assertEqual(self.render([item])['items'][0]['text'], raw)            # off by default
        f = dict(self.render([item], normalize_foreign=True)['items'][0]['fields'])
        self.assertEqual(f, {'booktitle': 'ACM SIGPLAN Conference on Certified Programs and Proofs, {CPP} 2019',
                             'series': 'LNCS', 'doi': '10.1145/1'})


class UpdateJob(unittest.TestCase):
    """The download-and-rebuild job, against a local web server instead of dblp.org."""

    def test_download_and_rebuild(self):
        tmp = tempfile.mkdtemp()
        www = os.path.join(tmp, 'www')
        os.makedirs(www)
        with open(FIXTURE, 'rb') as src, gzip.open(os.path.join(www, 'dblp.xml.gz'), 'wb') as dst:
            dst.write(src.read())
        gets = []

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=www, **kw)

            def do_GET(self):
                gets.append(self.path)
                super().do_GET()

            def log_message(self, *a):
                pass
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old = dblpdb.DUMP_URL
        dblpdb.DUMP_URL = f'http://127.0.0.1:{srv.server_address[1]}/dblp.xml.gz'
        try:
            app = dblpbib.App(os.path.join(tmp, 'data'))
            self.assertIsNone(app.dump_info())

            def run(mode):
                self.assertTrue(app.start_job(mode))
                for _ in range(100):
                    if not app.job['running']:
                        break
                    time.sleep(0.1)
                return app.job

            self.assertEqual(run('rebuild')['phase'], 'error')                  # nothing downloaded yet
            self.assertTrue(app.start_job('download'))
            self.assertFalse(app.start_job('download'))                         # one job at a time
            for _ in range(100):
                if not app.job['running']:
                    break
                time.sleep(0.1)
            self.assertEqual(app.job['phase'], 'done', app.job)
            self.assertEqual(app.db.meta()['records'], '7')
            self.assertEqual(app.db.meta()['source'], 'dblp.xml.gz')            # no absolute paths
            self.assertEqual(app.dump_info()['name'], 'dblp.xml.gz')
            self.assertEqual(run('rebuild')['phase'], 'done')                   # from the downloaded dump
            self.assertEqual(dblpdb.remote_info()['size'], os.path.getsize(os.path.join(www, 'dblp.xml.gz')))
            # the file's date is the server's Last-Modified, in UTC
            self.assertEqual(app.dump_info()['mtime'], int(os.path.getmtime(os.path.join(www, 'dblp.xml.gz'))))
            self.assertEqual(len(gets), 1)

            # unchanged on the server: nothing is downloaded or rebuilt
            built = app.db.meta()['built']
            self.assertEqual(run('download')['phase'], 'current', app.job)
            self.assertEqual((len(gets), app.db.meta()['built']), (1, built))
            # ... also with a date stored off by an hour by earlier versions
            self.assertTrue(dblpdb.is_current(int(app.db.meta()['source_mtime']) - 3600, app.db.meta()['source_size'],
                                              dblpdb.remote_info()))
            # ... but the database is rebuilt from the dump already there if it is missing
            os.remove(app.db.path)
            self.assertEqual(run('download')['phase'], 'done', app.job)
            self.assertEqual(len(gets), 1)
            self.assertEqual(app.db.meta()['records'], '7')
            # force downloads anyway
            self.assertTrue(app.start_job('download', force=True))
            for _ in range(100):
                if not app.job['running']:
                    break
                time.sleep(0.1)
            self.assertEqual((app.job['phase'], len(gets)), ('done', 2))
            # a newer dump on the server is downloaded
            later = time.time() + 86400
            os.utime(os.path.join(www, 'dblp.xml.gz'), (later, later))
            self.assertEqual(run('download')['phase'], 'done', app.job)
            self.assertEqual(len(gets), 3)

            # no connection: a readable error, not a traceback
            dblpdb.DUMP_URL = 'http://nonexistent.invalid/dblp.xml.gz'
            job = run('download')
            self.assertEqual(job['phase'], 'error')
            self.assertIn('cannot reach dblp.org', job['msg'])
        finally:
            dblpdb.DUMP_URL = old
            srv.shutdown()
            shutil.rmtree(tmp)


class Http(unittest.TestCase):
    """The HTTP layer: host check, JSON-only POSTs, .bib-only file access."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        app = dblpbib.App(cls.tmp)
        dblpdb.build(FIXTURE, app.db.path)
        dblpbib.Handler.app = app
        cls.srv = dblpbib.Server(('127.0.0.1', 0), dblpbib.Handler)
        cls.base = f'http://127.0.0.1:{cls.srv.server_address[1]}'
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp)

    def req(self, path, body=None, ctype='application/json', host=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, headers={'Content-Type': ctype})
        if host:
            r.add_header('Host', host)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_api(self):
        self.assertEqual(self.req('/api/search?q=quotients')[0], 200)
        self.assertEqual(self.req('/api/search?q=x', host='evil.example')[0], 403)
        self.assertEqual(self.req('/api/state', {'a': 1}, ctype='text/plain')[0], 403)
        path = os.path.join(self.tmp, 'out.bib')
        self.assertEqual(self.req('/api/file/save', {'path': path, 'text': 'one'})[0], 200)
        code, res = self.req('/api/file/save', {'path': path, 'text': 'two'})
        with open(res['backup']) as f:
            self.assertEqual(f.read(), 'one')
        self.assertEqual(self.req('/api/file/load', {'path': path})[1]['text'], 'two')
        self.assertEqual(self.req('/api/file/load', {'path': '/etc/passwd'})[0], 400)
        self.assertEqual(self.req('/static/../dblp-bib.py')[0], 404)

    def test_choose_file(self):
        old = dblpbib.choose_bib_file
        try:
            for ret, out in [('/x/refs.bib', {'path': '/x/refs.bib'}), ('', {'path': ''}), (None, {'unsupported': True})]:
                dblpbib.choose_bib_file = lambda save=False, name=None: ret
                self.assertEqual(self.req('/api/file/choose', {}), (200, out))
            dblpbib.choose_bib_file = lambda save=False, name=None: f'{save} {name}'
            self.assertEqual(self.req('/api/file/choose', {'save': True, 'name': 'x.bib'})[1], {'path': 'True x.bib'})
        finally:
            dblpbib.choose_bib_file = old


if __name__ == '__main__':
    unittest.main()

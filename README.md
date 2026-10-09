# dblp-bib

A dblp-like web interface to a local copy of the [dblp](https://dblp.org) dump, for clicking together the
`.bib` file of a paper — and for bringing an existing `.bib` file up to date with dblp.

- **Search** like on dblp.org: keyword search over titles, authors, venues and years; author pages
  (with disambiguated names such as *Joshua Schneider 0001*); tables of contents of proceedings and
  journal volumes; filters by publication type and year.
- **Bibliography**: `+` next to a publication adds it; entries are rendered as BibTeX with your options.
  Copy, download, or save the `.bib` directly to a path on your machine (the previous version is kept as `.bak`).
- **Existing `.bib` files**: open one (by path — with an empty path, *Open* and *Save* show the system's file dialogs — upload, drag & drop or paste). Every entry is matched against
  dblp (dblp key, DOI, arXiv id, title + authors) and shown as *up to date*, *differs from dblp* (with a
  field-by-field diff), *uncertain* (pick a candidate) or *not in dblp*. One click replaces an entry by
  the dblp version — keeping its citation key, so `\cite` commands keep working; *Revert* restores the
  original text. Comments, `@string` and `@preamble` are kept as they are. arXiv/CoRR entries are
  matched to their **published version** when dblp has one.
- **Options** (all optional, with a live before/after preview):
  - series and journal abbreviations (*Lecture Notes in Computer Science* → *LNCS*, editable list)
  - conference names: dblp's full title, or *name + acronym* without the ordinal, *International*
    (configurable word list), location, date and "Proceedings", or *acronym + year* only:
    `10th International Conference on Interactive Theorem Proving, ITP 2019, Portland, OR, USA, September 9-12, 2019`
    → `Conference on Interactive Theorem Proving, {ITP} 2019` → `{ITP} 2019`
  - years in full in conference names: `POPL '20`, `MFCS'91`, `RTA-87` → `POPL 2020`, `MFCS 1991`,
    `RTA 1987` (a number after a hyphen only when it matches the entry's year, so `CADE-28` stays)
  - drop the `url` when it only duplicates the `doi` (or whenever there is a `doi`)
  - drop dblp's `timestamp`/`biburl`/`bibsource` and any other fields
  - LaTeX commands for accents (or plain UTF-8 for biber), brace-protected capitals in titles,
    abbreviated first names, citation key style (dblp, short dblp, `author2019word`)
  - optionally apply the substitutions to entries that do not come from dblp, too
  - optionally write the entries of a loaded `.bib` file in the same uniform layout as the generated ones
    (only white space and delimiters change)
  - custom regular-expression rules per field
- **Data**: shows the date of the dump the index was built from, checks dblp.org for a newer dump,
  downloads it only if there is one, and rebuilds the index in the background (search keeps working on the old index meanwhile).
  
## Background

DBLP is a luxury to have for anyone writing a computer science publication.
This app grew out of my annoyance with the deployment of Anubis to protect dblp from crawlers
combined with the general observation that the DBLP entries are almost perfect as they are, but there
are always the same substitutions that I end up performing (Lecture Notes in Computer Science -> LNCS,
short conference names). The app itself is vibe-coded with a few shots. It is likely neither sound
nor complete, but possibly useful (at least useful for myself).

## Requirements

Python 3.10 or later; no third-party packages. The tool downloads the dblp dump
([dblp.xml.gz](https://dblp.org/xml/dblp.xml.gz), about 1 GB) into its `data/` directory and keeps
everything there: the dump, the index (about 5.5 GB, twice that while it is being rebuilt), and your
settings. It does not look for files anywhere else and stores no paths to them.

## Usage

```bash
./dblp-bib.py
```

opens http://127.0.0.1:8737/ in the browser. Without an index, the *Data* page offers to download
the dump and build one. From the command line:

```bash
./dblp-bib.py update
```

downloads the current dump and builds the index (about 4 minutes after the download) — but only if
dblp.org has a newer dump than the one the index is built from (`--force` downloads it anyway);
`./dblp-bib.py build` rebuilds it from the dump already in `data/`. To use a copy of the dump you
already have instead of downloading one, pass it once with `./dblp-bib.py build --dump FILE`
(the path is not stored), or copy it to `data/dblp.xml.gz`.
Options: `--port` (or `$PORT`), `--data DIR` (default `./data`, or `$DBLPBIB_DATA`), `--no-browser`.

Search syntax: all words must occur (as word prefixes) somewhere; `"exact phrase"`, `author:name`,
`title:word`, `venue:ITP`, `year:2019`, `-excluded`. Press `/` to jump to the search box.

The options and the current bibliography are saved in `data/state.json` whenever you change them,
so they survive restarts and browser changes.

## Notes

- The server only listens on 127.0.0.1, rejects requests for other host names, and only accepts JSON
  POST requests (which other web sites cannot send to it). It reads and writes only `.bib` files.
- Entries are generated in dblp's BibTeX format from the XML dump (with the crossref'd proceedings
  for editors, booktitle, series, volume and publisher). dblp's `timestamp` is approximated by the
  record's modification date.
- Tests: `python3 -m unittest discover tests`

## Files

| File | |
|---|---|
| `dblp-bib.py` | web server, command line, matching of `.bib` entries against dblp |
| `dblpdb.py` | import of the XML dump into SQLite with a full-text index; queries |
| `bibgen.py` | BibTeX generation and the substitutions |
| `bibparse.py` | tolerant BibTeX parser that keeps what it does not understand |
| `static/` | the web interface (plain HTML/CSS/JS) |

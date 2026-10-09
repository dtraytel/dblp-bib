"""A tolerant BibTeX parser that keeps everything it does not understand verbatim.

parse(text) returns a list of items:
  {'kind': 'entry', 'type', 'key', 'fields': [(name, value)], 'raw'}   value: braces/quotes removed
  {'kind': 'other', 'raw'}                                             comments, @string, @preamble, text
Field values that are not a single {...}/"..."/number (macros, # concatenation) keep their expression
in 'exprs' so that an unchanged entry can be written back as it was.
"""

import re


def _balanced(text, i, open_ch, close_ch):
    """Index after the delimiter closing the one at text[i]."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unbalanced')


def _quoted(text, i):
    """Index after the closing quote of the "..." starting at text[i] (braces protect quotes)."""
    depth, i, n = 0, i + 1, len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == '"' and depth == 0:
            return i + 1
        i += 1
    raise ValueError('unterminated string')


def _value(text, i, close):
    """Parse a field value at text[i:]; returns (value or None, expression, end index)."""
    pieces, start, n = [], i, len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            raise ValueError('unexpected end')
        c = text[i]
        if c == '{':
            j = _balanced(text, i, '{', '}')
            pieces.append(('s', text[i + 1:j - 1]))
        elif c == '"':
            j = _quoted(text, i)
            pieces.append(('s', text[i + 1:j - 1]))
        else:
            m = re.match(r'[^\s,#%s]+' % re.escape(close), text[i:])
            if not m:
                raise ValueError('bad value')
            j = i + m.end()
            w = m.group(0)
            pieces.append(('s', w) if w.isdigit() else ('m', w))
        i = j
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == '#':
            i += 1
            continue
        break
    expr = text[start:i].strip()
    value = pieces[0][1] if len(pieces) == 1 and pieces[0][0] == 's' else None
    return value, expr, i


def _entry(text, j, m):
    typ = m.group(1)
    open_ch = m.group(2)
    close = '}' if open_ch == '{' else ')'
    i = j + m.end()
    if typ.lower() in ('comment', 'preamble', 'string'):
        end = _balanced(text, i - 1, open_ch, close)
        return {'kind': 'other', 'raw': text[j:end]}, end
    km = re.match(r'\s*([^,\s%s]*)\s*,' % re.escape(close), text[i:])
    if not km:
        raise ValueError('no key')
    key = km.group(1)
    i += km.end()
    fields, exprs, n = [], {}, len(text)
    while True:
        while i < n and (text[i].isspace() or text[i] == ','):
            i += 1
        if i >= n:
            raise ValueError('unexpected end')
        if text[i] == close:
            i += 1
            break
        fm = re.match(r'([^\s=,{}"#()]+)\s*=\s*', text[i:])
        if not fm:
            raise ValueError('bad field at %r' % text[i:i + 30])
        name = fm.group(1).lower()
        value, expr, i = _value(text, i + fm.end(), close)
        fields.append((name, value if value is not None else expr))
        if value is None:
            exprs[name] = expr
    return {'kind': 'entry', 'type': typ.lower(), 'key': key, 'fields': fields, 'exprs': exprs, 'raw': text[j:i]}, i


def parse(text):
    items, i, n, pending = [], 0, len(text), 0
    while i < n:
        j = text.find('@', i)
        if j < 0:
            break
        m = re.match(r'@\s*([A-Za-z]+)\s*([{(])', text[j:])
        if not m:
            i = j + 1
            continue
        try:
            item, end = _entry(text, j, m)
        except ValueError as e:
            nxt = re.search(r'\n\s*@', text[j + 1:])
            end = j + 1 + nxt.start() + 1 if nxt else n
            item = {'kind': 'other', 'raw': text[j:end].rstrip(), 'error': str(e)}
        if text[pending:j].strip():
            items.append({'kind': 'other', 'raw': text[pending:j].strip()})
        items.append(item)
        i = pending = end
    if text[pending:].strip():
        items.append({'kind': 'other', 'raw': text[pending:].strip()})
    return items


def field(entry, name):
    return next((v for k, v in entry['fields'] if k == name), None)

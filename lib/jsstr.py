"""Decode and encode JavaScript string literals.

Escape handling has to be a single left-to-right pass. Replacing sequences one
after another is wrong in a way that only shows up on real data: `\\\\r` in the
source means *backslash followed by r*, but a pass that first turns `\\r` into a
carriage return sees the second backslash-r and eats it. Kimi's Edit tool
description talks about carriage returns and hits exactly that case.
"""

import re

ESCAPE = re.compile(r'\\(u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\s\S])')

SIMPLE = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v',
          '0': '\0', '\\': '\\', "'": "'", '"': '"', '`': '`', '$': '$'}


def decode(body: str) -> str:
    """Turn a raw literal body into the text the model actually sees."""
    def sub(m: re.Match) -> str:
        s = m.group(1)
        if s.startswith('u{'):
            return chr(int(s[2:-1], 16))
        if s[0] == 'u' and len(s) == 5:
            return chr(int(s[1:], 16))
        if s[0] == 'x' and len(s) == 3:
            return chr(int(s[1:], 16))
        if s == '\n':
            return ''            # line continuation
        return SIMPLE.get(s, s)
    return ESCAPE.sub(sub, body)


def encode(text: str, quote: str) -> str:
    """Inverse of decode, for the given quote character.

    `${` is deliberately left alone in template literals: escaping it would
    turn a live interpolation into literal text.
    """
    out = []
    for ch in text:
        if ch == '\\':
            out.append('\\\\')
        elif ch == quote:
            out.append('\\' + ch)
        elif ch in '\n\r\t':
            if quote == '`' and ch == '\n':
                out.append(ch)          # legal, and keeps the bundle readable
            else:
                out.append({'\n': '\\n', '\r': '\\r', '\t': '\\t'}[ch])
        elif ch < ' ' or ch == '\x7f':
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    return ''.join(out)


def _selfcheck():
    cases = [
        (r'plain text', '"'),
        (r'shows carriage returns as \\r; include actual \\r escapes', '"'),
        (r'line\nbreak\ttab', '"'),
        (r'quote \" and backslash \\\\ together', '"'),
        (r'unicode \u00e9 and \u{1F600}', '"'),
        ('template ${VAR} hole', '`'),
        (r'a\\\\b\\nc', '`'),
    ]
    for body, q in cases:
        text = decode(body)
        again = decode(encode(text, q))
        assert again == text, f'round-trip broke for {body!r}: {text!r} -> {again!r}'
    # the case that motivated the rewrite
    assert decode(r'as \\r;') == 'as \\r;', decode(r'as \\r;')
    assert decode(r'as \r;') == 'as \r;'
    print('jsstr selfcheck: ok')


if __name__ == '__main__':
    _selfcheck()

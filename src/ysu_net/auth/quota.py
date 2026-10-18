"""Conservative quota evidence from raw accountInfo, not display summaries.

Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
The caller verifies HTTP success and current online ownership before using this result.
"""
import re
import unicodedata

_MAX_DEPTH = 6
_MAX_ITEMS = 256
_MAX_TEXT_BYTES = 4096
_MAX_DIGITS = 128
_UNITS = frozenset(('B', 'KB', 'MB', 'GB', 'TB', 'KiB', 'MiB', 'GiB', 'TiB'))
_MESSAGES = {
    'unknown': '剩余流量证据未知',
    'available': '门户报告剩余流量为正值',
    'zero_reported': '门户报告剩余流量为零',
    'unlimited': '门户报告不限量（合成规则，非生产样本）',
}
_HIDDEN = tuple(re.compile(
    rf'<{"".join(f"[{ch}{ch.upper()}]" for ch in tag)}(?:[ \t\r\n\f][^<>]*)?>'
    rf'.*?</{"".join(f"[{ch}{ch.upper()}]" for ch in tag)}[ \t\r\n\f]*>', re.S
) for tag in ('script', 'style', 'noscript'))
_TAG = re.compile(r'</?([A-Za-z][A-Za-z0-9]*)(?:[ \t\r\n\f]+[^<>]*)?[ \t\r\n\f]*/?>')
_ENTITY = re.compile(r'&(?:#x[0-9A-Fa-f]+|#[0-9]+|amp|lt|gt|quot|apos|nbsp);')
_TITLE = re.compile(r'剩余流量(?: ?\( ?([^()]*) ?\)| ?（ ?([^（）]*) ?）)?')
_DECIMAL = re.compile(r'([0-9]+(?:\.[0-9]+)?)(?: ?([A-Za-z]+))?')
_SPACES = frozenset(chr(code) for code in (
    *range(0x09, 0x0e), 0x20, 0x85, 0xa0, 0x1680, *range(0x2000, 0x200b),
    0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
))


def successful_envelope(value):
    return isinstance(value, dict) and not (
        ('result' in value and value['result'] != 'success')
        or ('code' in value and (type(value['code']) is not int or value['code'] not in (0, 200)))
        or ('success' in value and value['success'] is not True)
        or ('online' in value and value['online'] is not True))


def _account_items(raw):
    current = raw
    found = None
    for _ in range(_MAX_DEPTH):
        if not isinstance(current, dict):
            return None
        if not successful_envelope(current):
            return None
        items = current.get('accountInfo')
        if items is not None:
            if not isinstance(items, list) or len(items) > _MAX_ITEMS or found is not None:
                return None
            found = items
        current = current.get('data')
        if current is None:
            return found
    return None


def _plain_text(value):
    if isinstance(value, str):
        source = value
    elif type(value) is int and -(2**63) <= value < 2**63:
        source = str(value)
    else:
        return None
    try:
        if len(source) > _MAX_TEXT_BYTES or len(source.encode('utf-8')) > _MAX_TEXT_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    # The same limited fragment grammar as Rust: malformed hidden blocks fail closed.
    for hidden in _HIDDEN:
        source = hidden.sub('', source)
    visible = []
    while '<' in source:
        start = source.index('<')
        visible.append(source[:start])
        end = source.find('>', start)
        if end < 0 or not (capture := _TAG.fullmatch(source[start:end + 1])):
            return None
        tag = capture[1].lower()
        if tag in ('script', 'style', 'noscript'):
            return None
        if tag in ('br', 'p', 'div', 'li'):
            visible.append(' ')
        source = source[end + 1:]
    visible.append(source)

    def decode(match):
        token = match[0][1:-1]
        named = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': '\u00a0'}
        if token in named:
            return named[token]
        code = int(token[2:], 16) if token.startswith('#x') else int(token[1:])
        if code > 0x10ffff or 0xd800 <= code <= 0xdfff:
            raise ValueError('invalid HTML code point')
        return chr(code)

    try:
        decoded = _ENTITY.sub(decode, ''.join(visible))
    except ValueError:
        return None
    cleaned = []
    for char in decoded:
        if char in _SPACES:
            if cleaned and cleaned[-1] != ' ':
                cleaned.append(' ')
        elif unicodedata.category(char).startswith('C'):
            return None
        else:
            cleaned.append(char)
    return ''.join(cleaned).rstrip(' ')


def _evidence(raw):
    items = _account_items(raw)
    if items is None:
        return 'unknown'
    candidate = None
    for item in items:
        if not isinstance(item, dict) or (title := _plain_text(item.get('title'))) is None:
            return 'unknown'
        title_match = _TITLE.fullmatch(title)
        if title_match is None:
            continue
        if candidate is not None:
            return 'unknown'
        title_unit = title_match[1] if title_match[1] is not None else title_match[2]
        if title_unit is not None:
            title_unit = title_unit.strip(' ')
            if title_unit not in _UNITS:
                return 'unknown'
        content = _plain_text(item.get('content'))
        if content in ('不限量', '无限量'):
            # Synthetic literal rule; no production unlimited sample has been observed.
            if title_unit is not None:
                return 'unknown'
            candidate = 'unlimited'
            continue
        if content is None or (number := _DECIMAL.fullmatch(content)) is None:
            return 'unknown'
        digits, content_unit = number.groups()
        if sum(char in '0123456789' for char in digits) > _MAX_DIGITS:
            return 'unknown'
        if ((content_unit is not None and content_unit not in _UNITS)
                or (title_unit is None and content_unit is None)
                or (title_unit is not None and content_unit is not None
                    and title_unit != content_unit)):
            return 'unknown'
        # Inspect digits, not a binary float: tiny positive decimals stay positive.
        candidate = 'available' if any(char in '123456789' for char in digits) else 'zero_reported'
    return candidate or 'unknown'


def classify_quota(raw_account):
    """Return state/message without inferring bytes, multipliers, or account ownership."""
    state = _evidence(raw_account)
    return {'state': state, 'message': _MESSAGES[state]}

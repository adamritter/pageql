import re
from html import escape


SQL_KEYWORDS = {
    "from",
    "where",
    "set",
    "values",
    "delete",
    "insert",
    "update",
    "create",
    "table",
    "if",
    "not",
    "exists",
    "check",
    "in",
    "default",
    "primary",
    "key",
    "autoincrement",
    "into",
    "order",
    "by",
}

FUNC_NAMES = {"COUNT", "IIF"}

HTTP_VERBS = {"post", "patch", "delete", "get", "put"}


_DIRECTIVE_COLOR = "#569cd6; font-weight: bold;"
_SQL_COLOR = "#c586c0; font-weight: bold;"
_FUNC_COLOR = "#4fc1ff; font-weight: bold;"
_VAR_COLOR = "#9cdcfe;"
_STRING_COLOR = "#ce9178;"
_TYPENAME_COLOR = "#4ec9b0;"
_HTTPVERB_COLOR = "#dcdcaa;"
_COMMENT_COLOR = "#6a9955; font-style: italic;"
_HTML_BRACKET = "#808080;"
_HTML_ATTR = "#92c5f8;"
_HTML_TAG = "#569cd6; font-weight: bold;"

_TOKEN_SPLIT_RE = re.compile(
    r"({{!--.*?--}}|{{{.*?}}}|{{.*?}}|<[^>]*>)",
    re.DOTALL,
)


def _span(content: str, color: str) -> str:
    return f"<span style=\"color: {color}\">{content}</span>"


def _highlight_pageql_expr(text: str) -> str:
    i = 0
    out: list[str] = []
    after_let = False
    after_param = False
    after_param_attr = False
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            out.append(ch)
            i += 1
            continue
        if ch in ('\"', "'"):
            quote = ch
            j = i + 1
            while j < len(text) and text[j] != quote:
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                else:
                    j += 1
            j = min(j + 1, len(text))
            out.append(_span(escape(text[i:j]), _STRING_COLOR))
            i = j
            continue
        if ch.isdigit():
            j = i + 1
            while j < len(text) and text[j].isdigit():
                j += 1
            out.append(_span(text[i:j], _STRING_COLOR))
            i = j
            continue
        if ch == ':' and i + 1 < len(text):
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] in '._'):
                j += 1
            out.append(_span(escape(text[i:j]), _VAR_COLOR))
            i = j
            continue
        if ch.isalpha() or ch in '#/':
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] in '._/'):
                j += 1
            word = text[i:j]
            word_lower = word.lower()
            word_upper = word.upper()
            if after_param:
                color = _VAR_COLOR
                after_param = False
                after_param_attr = True
            elif after_param_attr:
                color = _HTTPVERB_COLOR
            elif after_let:
                color = _VAR_COLOR
                after_let = False
            elif word_lower == '#param':
                color = _SQL_COLOR
                after_param = True
            elif word_lower == '#let':
                color = _DIRECTIVE_COLOR
                after_let = True
            elif word.startswith('#') or word.startswith('/'):
                color = _DIRECTIVE_COLOR
            elif word_lower in HTTP_VERBS:
                color = _HTTPVERB_COLOR
            elif word_upper in FUNC_NAMES:
                color = _FUNC_COLOR
            elif word_lower in SQL_KEYWORDS:
                color = _SQL_COLOR
            else:
                color = _TYPENAME_COLOR
            out.append(_span(escape(word), color))
            i = j
            continue
        out.append(escape(ch))
        i += 1
    return ''.join(out)


def _highlight_pageql(token: str) -> str:
    if token.startswith('{{!--'):
        content = escape(token[5:-4])
        return f"&#123;&#123;{_span('!--' + content + '--', _COMMENT_COLOR)}&#125;&#125;"
    if token.startswith('{{{'):
        inner = token[3:-3]
        return f"&#123;&#123;&#123;{_highlight_pageql_expr(inner)}&#125;&#125;&#125;"
    inner = token[2:-2]
    return f"&#123;&#123;{_highlight_pageql_expr(inner)}&#125;&#125;"


def _highlight_html_tag(tag: str) -> str:
    if tag.lower().startswith('<!doctype'):
        return _span(escape(tag), f'{_HTML_BRACKET} font-style: italic;')
    out = [f'<span style="color: {_HTML_BRACKET}">&lt;']
    i = 1
    if tag.startswith('</'):
        out.append('</span><span style="color: {_HTML_BRACKET}">/</span>')
        i = 2
    m = re.match(r'([a-zA-Z0-9_-]+)', tag[i:])
    if m:
        name = m.group(1)
        out.append(f'</span><span style="color: {_HTML_TAG}">{name}</span>')
        i += len(name)
    while i < len(tag) and tag[i] != '>':
        ch = tag[i]
        if ch.isspace():
            out.append(ch)
            i += 1
            continue
        if ch == '/':
            out.append(f'<span style="color: {_HTML_BRACKET}">/</span>')
            i += 1
            continue
        j = i
        while j < len(tag) and tag[j] not in '= />':
            j += 1
        attr = tag[i:j]
        out.append(f'<span style="color: {_HTML_ATTR}">{attr}</span>')
        i = j
        while i < len(tag) and tag[i].isspace():
            out.append(tag[i])
            i += 1
        if i < len(tag) and tag[i] == '=':
            out.append(f'<span style="color: {_HTML_BRACKET}">=</span>')
            i += 1
            while i < len(tag) and tag[i].isspace():
                out.append(tag[i])
                i += 1
            if i < len(tag) and tag[i] in ('"', "'"):
                quote = tag[i]
                i += 1
                j = i
                while j < len(tag) and tag[j] != quote:
                    j += 1
                value = escape(tag[i:j])
                out.append(f'<span style="color: {_STRING_COLOR}">{quote}{value}{quote}</span>')
                i = j + 1
            else:
                j = i
                while j < len(tag) and tag[j] not in ' >':
                    j += 1
                value = escape(tag[i:j])
                out.append(f'<span style="color: {_STRING_COLOR}">{value}</span>')
                i = j
    out.append(f'<span style="color: {_HTML_BRACKET}">&gt;</span>')
    return ''.join(out)


def _highlight_text(text: str) -> str:
    return escape(text)


def highlight(source: str) -> str:
    result: list[str] = ["<span></span>"]
    pos = 0
    for m in _TOKEN_SPLIT_RE.finditer(source):
        if m.start() > pos:
            result.append(_highlight_text(source[pos:m.start()]))
        token = m.group(0)
        if token.startswith('{{'):
            result.append(_highlight_pageql(token))
        elif token.startswith('<'):
            result.append(_highlight_html_tag(token))
        pos = m.end()
    if pos < len(source):
        result.append(_highlight_text(source[pos:]))
    return ''.join(result)


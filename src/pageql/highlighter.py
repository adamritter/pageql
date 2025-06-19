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

PARAM_ATTRS = {"maxlength", "default", "pattern"}


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
    next_as_var = False
    skip_next_type = False
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
            if next_as_var:
                color = _VAR_COLOR
                next_as_var = False
            elif word.startswith('#') or word.startswith('/'):
                color = _DIRECTIVE_COLOR
                if word_lower in ('#param', '#let'):
                    next_as_var = True
            elif word_lower in HTTP_VERBS or word_lower in PARAM_ATTRS:
                color = _HTTPVERB_COLOR
            elif word_upper in FUNC_NAMES:
                color = _FUNC_COLOR
            elif word_lower in SQL_KEYWORDS:
                color = _SQL_COLOR
            else:
                color = _TYPENAME_COLOR
            if color is _TYPENAME_COLOR and skip_next_type:
                out.append(escape(word))
                skip_next_type = False
            else:
                out.append(_span(escape(word), color))
            if color is _SQL_COLOR and word_lower in {
                "from",
                "into",
                "update",
                "delete",
                "table",
            }:
                skip_next_type = True
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
        out.append(f'</span><span style="color: {_HTML_BRACKET}">/</span>')
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


def highlight_block(source: str) -> str:
    """Return HTML for a highlighted code block with copy button."""
    highlighted = highlight(source)
    button_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">'
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>'
        '</svg>'
    )
    button = (
        '<button onclick="copySourceCode(this)" '
        'style="position: absolute; top: 8px; right: 8px; z-index: 10; '
        'background: rgba(255,255,255,0.15); border: 1px solid '
        'rgba(255,255,255,0.3); border-radius: 4px; padding: 8px; '
        'cursor: pointer; color: #d4d4d4; transition: all 0.2s;">'
        f'{button_svg}</button>'
    )
    pre_start = (
        '<div class="code-column">'
        '<div class="highlight" '
        'style="background:rgb(24, 28, 29); border-radius: 8px; '
        'padding: 1rem; overflow-x: auto;"><pre '
        'style="line-height: 125%; color: #d4d4d4; margin: 0;">'
    )
    pre_end = '</pre></div></div>'
    return (
        '<div style="position: relative;">'
        f'{button}'
        f'{pre_start}{highlighted}{pre_end}'
        '</div>'
    )


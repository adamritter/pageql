import re
import sqlglot
from .reactive import get_dependencies, _convert_dot_sql


def quote_state(text: str, start_state: str | None = None) -> str | None:
    """Return quoting state after scanning ``text``.

    Only single and double quotes are tracked. ``start_state`` specifies the
    quoting state at the beginning.
    """
    quote = start_state
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
    return quote


def parsefirstword(s):
    s = s.strip()
    if not s:
        return "", None
    parts = s.split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1].strip()


def _shorten_error_token(value: str) -> str:
    """Return a short token snippet for error messages."""
    value = value.split("{{")[0]
    value = value.split("\n")[0]
    return value.strip()


def tokenize(source):
    """
    Parses a PageQL template into a list of ``(token_type, content)`` tuples.

    Token types are:
        * ``text`` - literal text from the template
        * ``render_param`` - simple parameter substitution such as ``{{name}}``
        * ``render_expression`` - expression evaluation within ``{{expr}}``
        * ``render_raw`` - raw output of an expression like ``{{{expr}}}``
        * directive tokens (strings beginning with ``#`` or ``/``), e.g.
          ``#if``/``/if``, ``#from``/``/from`` and ``#partial``/``/partial``

    Args:
        source: The PageQL template source code as a string

    Returns:
        A list of node tuples representing the parsed template
        
    Example:
        >>> tokenize("Hello {{name}}")
        [('text', 'Hello '), ('render_param', 'name')]
        >>> tokenize("Count: {{{1+1}}}")
        [('text', 'Count: '), ('render_raw', '1+1')]
        >>> tokenize("{{#if x > 5}}Big{{/if}}")
        [('#if', 'x > 5'), ('text', 'Big'), ('/if', None)]
        >>> tokenize("{{!-- Comment --}}Visible")
        [('text', 'Visible')]
    """
    nodes = []
    parts = re.split(r'({{!--.*?--}}|{{.*?}}}?)', source, flags=re.DOTALL)
    for part in parts:
        if not part:  # Skip empty strings from split
            continue
        if part.startswith('{{{') and part.endswith('}}}'):
            inner = part[3:-3]
            if '{{' in inner or '}}' in inner:
                snippet = _shorten_error_token(inner)
                raise SyntaxError(f"mismatched {{{{ in token: {snippet!r}")
            nodes.append(('render_raw', inner.strip()))
        elif part.startswith('{{') and part.endswith('}}'):
            inner = part[2:-2]
            inner = inner.strip()
            if inner.startswith('!'):
                pass  # Skip comment nodes
            elif '{{' in inner or '}}' in inner:
                snippet = _shorten_error_token(inner)
                raise SyntaxError(f"mismatched {{{{ in token: {snippet!r}")
            elif inner.startswith('#') or inner.startswith('/'):
                first, rest = parsefirstword(inner)
                if first == '#param' and rest:
                    pn, attrs = parsefirstword(rest)
                    pn = pn.replace('.', '__')
                    rest = pn if not attrs else f"{pn} {attrs}"
                nodes.append((first, rest))
            else:
                if re.match(r'^:?[a-zA-Z._$][a-zA-Z0-9._$]*$', inner):
                    if inner[0] == ':':
                        inner = inner[1:]
                    inner = inner.replace('.', '__')
                    nodes.append(('render_param', inner))
                else:
                    nodes.append(('render_expression', inner))
        else:
            if '{{' in part or '}}' in part:
                snippet = _shorten_error_token(part)
                raise SyntaxError(f"mismatched {{{{ in text: {snippet!r}")
            nodes.append(('text', part))
    return nodes


def _read_block(node_list, i, stop, partials, dialect, tests=None):
    """Return (body, new_index) while filling *partials* dict in‑place."""
    body = []
    while i < len(node_list):
        ntype, ncontent = node_list[i]
        if ntype in stop:
            break

        # ------------------------------------------------------------- #if ...
        if ntype == "#if" or ntype == "#ifdef" or ntype == "#ifndef":
            if_terms = {"#elif", "#else", "/if", "/ifdef", "/ifndef"}  # inline terminators for this IF
            if ntype == "#if":
                try:
                    cond_expr = sqlglot.parse_one(
                        _convert_dot_sql("SELECT " + ncontent), read=dialect
                    )
                except Exception as e:  # pragma: no cover - invalid SQL
                    raise SyntaxError(f"bad SQL in #if: {e}")
            i += 1
            then_body, i = _read_block(node_list, i, if_terms, partials, dialect, tests)
            else_body = None
            r = [ntype, (ncontent, cond_expr), then_body] if ntype == "#if" else [ntype, ncontent, then_body]
            while i < len(node_list):
                k, c = node_list[i]
                if k == "#elif":
                    if ntype != "#if":
                        raise SyntaxError("{{#elif}} must be used with {{#if}}")
                    i += 1
                    elif_body, i = _read_block(node_list, i, if_terms, partials, dialect, tests)
                    try:
                        expr = sqlglot.parse_one(
                            _convert_dot_sql("SELECT " + c), read=dialect
                        )
                    except Exception as e:  # pragma: no cover - invalid SQL
                        raise SyntaxError(f"bad SQL in #elif: {e}")
                    r.append((c, expr))
                    r.append(elif_body)
                    continue
                if k == "#else":
                    i += 1
                    else_body, i = _read_block(node_list, i, if_terms, partials, dialect, tests)
                    r.append(else_body)
                    break
                if k == "/if" or k == "/ifdef" or k == "/ifndef":
                    break
            if node_list[i][0] != "/if" and node_list[i][0] != "/ifdef" and node_list[i][0] != "/ifndef":
                raise SyntaxError("missing {{/if}}")
            i += 1
            body.append(r)
            continue

        # ----------------------------------------------------------- #from ...
        if ntype == "#from":
            from_terms = {"/from"}
            query = ncontent
            try:
                expr = sqlglot.parse_one(
                    _convert_dot_sql("SELECT * FROM " + query), read=dialect
                )
            except Exception as e:  # pragma: no cover - invalid SQL
                raise SyntaxError(f"bad SQL in #from: {e}")
            i += 1
            loop_body, i = _read_block(node_list, i, from_terms, partials, dialect, tests)
            if node_list[i][0] != "/from":
                raise SyntaxError("missing {{/from}}")
            i += 1
            deps = ast_param_dependencies(loop_body)
            deps.discard("__first_row")
            body.append(["#from", (query, expr), deps, loop_body])
            continue

        if ntype == "#each":
            each_terms = {"/each"}
            param_name = ncontent.strip()
            i += 1
            loop_body, i = _read_block(node_list, i, each_terms, partials, dialect, tests)
            if node_list[i][0] != "/each":
                raise SyntaxError("missing {{/each}}")
            i += 1
            body.append(["#each", param_name, loop_body])
            continue

        if ntype == "#let":
            var, rest = parsefirstword(ncontent)
            sql = rest or ""
            if sql.lstrip().startswith("="):
                sql = sql.lstrip()[1:].lstrip()
            sql_strip = sql.lstrip().lower()
            if sql_strip.startswith("select") or sql_strip.startswith("(select"):
                parse_sql = sql
            else:
                parse_sql = "SELECT " + sql
            try:
                expr = sqlglot.parse_one(_convert_dot_sql(parse_sql), read=dialect)
            except Exception as e:  # pragma: no cover - invalid SQL
                raise SyntaxError(f"bad SQL in #let: {e}")
            i += 1
            body.append(("#let", (var, sql, expr)))
            continue

        if ntype == "#fetch":
            first, rest = parsefirstword(ncontent)
            is_async = False
            if first.lower() == "async":
                is_async = True
                if rest is None:
                    raise SyntaxError("#fetch requires a variable and expression")
                var, rest = parsefirstword(rest)
            else:
                var = first
            if rest is None:
                raise SyntaxError("#fetch requires a variable and expression")
            kw, expr = parsefirstword(rest)
            if kw.lower() != "from" or expr is None:
                raise SyntaxError(
                    "#fetch syntax is '[async] <var> from <expr> [header=<expr>] [method=<expr>] [body=<expr>]'")
            expr, more = parsefirstword(expr)
            header_exprs: list[str] = []
            method_expr = None
            body_expr = None
            while more is not None:
                part, more = parsefirstword(more)
                if part.startswith("header="):
                    header_exprs.append(part[len("header=") :].strip())
                elif part.startswith("method="):
                    if method_expr is not None:
                        raise SyntaxError("duplicate method argument in #fetch")
                    method_expr = part[len("method=") :].strip()
                elif part.startswith("body="):
                    if body_expr is not None:
                        raise SyntaxError("duplicate body argument in #fetch")
                    body_expr = part[len("body=") :].strip()
                else:
                    raise SyntaxError(
                        "#fetch syntax is '[async] <var> from <expr> [header=<expr>] [method=<expr>] [body=<expr>]'")
            i += 1
            body.append(("#fetch", (var, expr, is_async, header_exprs, method_expr, body_expr)))
            continue

        if ntype == "#respond":
            status_expr = "200"
            body_expr = None
            content = (ncontent or "").strip()
            if content:
                first, rest = parsefirstword(content)
                if first.startswith("body="):
                    body_expr = first[len("body="):].strip()
                else:
                    status_expr = first
                    if rest and rest.startswith("body="):
                        body_expr = rest[len("body="):].strip()
                    elif rest:
                        raise SyntaxError("#respond syntax is '[status_code] [body=<expr>]'")
            i += 1
            body.append(("#respond", (status_expr, body_expr)))
            continue

        if ntype == "#header":
            name, value_expr = parsefirstword(ncontent)
            if value_expr is None:
                raise SyntaxError("#header requires a name and expression")
            i += 1
            body.append(("#header", (name, value_expr)))
            continue

        # -------------------------------------------------------- #partial ...
        if ntype == "#partial":
            part_terms = {"/partial"}
            first, rest = parsefirstword(ncontent)

            # Check if first token is a verb or 'public' (case-insensitive)
            first_lower = first.lower()
            if first_lower in ["public", "get", "post", "put", "delete", "patch"]:
                partial_type = first_lower.upper() if first_lower != "public" else "PUBLIC"
                name = rest
            else:
                partial_type = None
                name = first
                
            i += 1
            partial_partials = {}
            part_body, i = _read_block(node_list, i, part_terms, partial_partials, dialect, tests)
            if node_list[i][0] != "/partial":
                raise SyntaxError("missing {{/partial}}")
            i += 1
            split_name = name.split('/')
            dest_partials = partials
            while len(split_name) > 1:
                name0 = split_name[0]
                if name0[0] == ':':
                    if (':', None) not in dest_partials:
                        dest_partials[(':', None)] = [name0, [], {}]
                    if dest_partials[(':', None)][0] != name0:
                        raise ValueError(f"Partial name mismatch: {name0} != {dest_partials[(':', None)][0]}")
                    dest_partials = dest_partials[(':', None)][2]
                else:
                    if (name0, None) not in dest_partials:
                        dest_partials[(name0, None)] = [[], {}]
                    dest_partials = dest_partials[(name0, None)][1]
                split_name = split_name[1:]
            name1 = split_name[-1]
            if name1[0] == ':':
                if partial_type and partial_type != 'PUBLIC':
                    dest_partials[(':', partial_type)] = [name1, part_body, partial_partials]
                else:
                    if (':', None) in dest_partials:
                        raise ValueError(f"Cannot have two private partials with the same name: '{dest_partials[(':', None)][0]}' and '{name1}', partial_type: {partial_type}")
                    dest_partials[(':', None)] = [name1, part_body, partial_partials]
            else:
                dest_partials[(name1, partial_type)] = [part_body, partial_partials]
            continue

        if ntype == "#test":
            test_terms = {"/test"}
            test_name = ncontent.strip()
            i += 1
            dummy_partials = {}
            test_body, i = _read_block(node_list, i, test_terms, dummy_partials, dialect, tests)
            if node_list[i][0] != "/test":
                raise SyntaxError("missing {{/test}}")
            i += 1
            if tests is not None:
                tests[test_name] = test_body
            continue

        # -------------------------------------------------------------- leaf --
        body.append((ntype, ncontent))
        i += 1
    return body, i

def build_ast(node_list, dialect="sqlite", tests=None):
    """
    Builds an abstract syntax tree from a list of nodes.
    
    Args:
        node_list: List of (type, content) tuples from tokenize()
        
    Returns:
        Tuple of (body, partials) where body is the AST and partials is a dict of partial definitions
        
    >>> nodes = [('text', 'hello'), ('#partial', 'test'), ('text', 'world'), ('/partial', '')]
    >>> build_ast(nodes)
    ([('text', 'hello')], {('test', None): [[('text', 'world')], {}]})
    >>> nodes = [('#partial', 'a/b'), ('text', 'world'), ('/partial', '')]
    >>> build_ast(nodes)
    ([], {('a', None): [[], {('b', None): [[('text', 'world')], {}]}]})
    >>> nodes = [('#partial', ':a/b'), ('text', 'world'), ('/partial', '')]
    >>> build_ast(nodes)
    ([], {(':', None): [':a', [], {('b', None): [[('text', 'world')], {}]}]})
    >>> nodes = [('#partial', ':a'), ('text', 'world'), ('/partial', '')]
    >>> build_ast(nodes)
    ([], {(':', None): [':a', [('text', 'world')], {}]})
    """
    partials = {}
    body, idx = _read_block(node_list, 0, set(), partials, dialect, tests)
    if idx != len(node_list):
        raise SyntaxError("extra tokens after top‑level parse")
    return body, partials


def contains_dynamic_elements(seq: list[object]) -> bool:
    """Return ``True`` if *seq* contains any dynamic elements."""

    return any(x[0] != "text" for x in seq)


def _apply_add_reactive(n):
    """Traverse *n* and apply :func:`add_reactive_elements` where needed."""

    if isinstance(n, list):
        name = n[0]
        if name == "#if":
            res = [name, n[1], add_reactive_elements(n[2])]
            i = 3
            while i < len(n):
                if i == len(n) - 1:
                    res.append(add_reactive_elements(n[i]))
                    break
                res.append(n[i])
                if i + 1 < len(n):
                    res.append(add_reactive_elements(n[i + 1]))
                i += 2
            return res
        if name in {"#ifdef", "#ifndef"}:
            res = [name, n[1], add_reactive_elements(n[2])]
            if len(n) > 3:
                res.append(add_reactive_elements(n[3]))
            return res
        if name == "#from":
            if len(n) == 4:
                return [name, n[1], n[2], add_reactive_elements(n[3])]
            return [name, n[1], add_reactive_elements(n[2])]
        if name == "#each":
            return [name, n[1], add_reactive_elements(n[2])]
    return n


def find_last_unclosed_lt(text: str) -> int | None:
    """Return the index of the last ``<`` that isn't followed by ``>``."""

    pos = text.rfind("<")
    return pos if pos != -1 and text.rfind(">") < pos else None


def add_reactive_elements(nodes):
    """Return a modified AST with ``#reactiveelement`` wrappers."""

    output_nodes: list[object] = []
    tag_buffer: list[object] = []
    capturing = False
    for node in map(_apply_add_reactive, nodes):
        if node[0] == "text":
            text = node[1]
            if capturing:
                closing_pos = text.find(">")
                if closing_pos != -1:
                    tag_buffer.append(("text", text[: closing_pos + 1]))
                    after_tag = text[closing_pos + 1 :]
                    if contains_dynamic_elements(tag_buffer):
                        output_nodes.append(["#reactiveelement", tag_buffer])
                        tag_buffer, capturing = [], False
                        if after_tag:
                            lt_index = find_last_unclosed_lt(after_tag)
                            if lt_index is None:
                                output_nodes.append(("text", after_tag))
                            else:
                                if lt_index:
                                    output_nodes.append(("text", after_tag[:lt_index]))
                                tag_buffer = [("text", after_tag[lt_index:])]
                                capturing = True
                    else:
                        if tag_buffer:
                            tag_buffer[-1] = (tag_buffer[-1][0], tag_buffer[-1][1] + after_tag)
                        output_nodes.extend(tag_buffer)
                        tag_buffer, capturing = [], False
                else:
                    tag_buffer.append(node)
            else:
                lt_index = find_last_unclosed_lt(text)
                if lt_index is None:
                    output_nodes.append(node)
                else:
                    if lt_index:
                        output_nodes.append(("text", text[:lt_index]))
                    tag_buffer = [("text", text[lt_index:])]
                    capturing = True
        else:
            (tag_buffer if capturing else output_nodes).append(node)

    if tag_buffer:
        if contains_dynamic_elements(tag_buffer):
            output_nodes.append(["#reactiveelement", tag_buffer])
        else:
            output_nodes.extend(tag_buffer)

    return output_nodes


def ast_param_dependencies(ast):
    """Return parameter names referenced anywhere in *ast* expressions.

    The function traverses the AST produced by :func:`build_ast` and
    collects all parameter names used in SQL expressions or directives.
    """
    if isinstance(ast, tuple) and len(ast) == 2:
        body, partials = ast
    else:
        body, partials = ast, {}

    deps: set[str] = set()

    def walk_nodes(nodes):
        for node in nodes:
            walk(node)

    def walk(node):
        if isinstance(node, tuple):
            t, c = node
            if t in {"render_expression", "render_raw"}:
                deps.update(get_dependencies(_convert_dot_sql(c)))
            elif t == "#let":
                deps.update(get_dependencies(_convert_dot_sql(c[1])))
            elif t in {"#update", "#insert", "#delete", "#merge", "#create", "#attach", "#redirect", "#statuscode", "#error"}:
                deps.update(get_dependencies(_convert_dot_sql(c)))
            elif t == "#respond":
                status_expr, body_expr = c
                if status_expr:
                    deps.update(get_dependencies(_convert_dot_sql(status_expr)))
                if body_expr:
                    deps.update(get_dependencies(_convert_dot_sql(body_expr)))
            elif t == "#fetch":
                deps.update(get_dependencies(_convert_dot_sql(c[1])))
                header_exprs = c[3]
                method_expr = c[4]
                body_expr = c[5]
                for header_expr in header_exprs:
                    deps.update(get_dependencies(_convert_dot_sql(header_expr)))
                if method_expr is not None:
                    deps.update(get_dependencies(_convert_dot_sql(method_expr)))
                if body_expr is not None:
                    deps.update(get_dependencies(_convert_dot_sql(body_expr)))
            elif t == "#header":
                if isinstance(c, tuple):
                    _, expr = c
                    deps.update(get_dependencies(_convert_dot_sql(expr)))
                else:
                    _, rest = parsefirstword(c)
                    if rest:
                        deps.update(get_dependencies(_convert_dot_sql(rest)))
            elif t == "#cookie":
                _, rest = parsefirstword(c)
                if rest:
                    m = re.match(r'("[^"]*"|\'[^\']*\'|\S+)', rest)
                    if m:
                        deps.update(get_dependencies(_convert_dot_sql(m.group(1))))
            elif t == "#render":
                _, rest = parsefirstword(c)
                if rest:
                    for expr in re.findall(r"=[^=]+(?:(?=\s+[A-Za-z_][A-Za-z0-9_.]*\s*=)|$)", rest):
                        deps.update(get_dependencies(_convert_dot_sql(expr[1:].strip())))
            elif t in {"#ifdef", "#ifndef"}:
                param = c.strip()
                if param.startswith(":"):
                    param = param[1:]
                param = param.replace(".", "__")
                deps.add(param)
        elif isinstance(node, list):
            name = node[0]
            if name == "#if":
                deps.update(get_dependencies(_convert_dot_sql(node[1][0])))
                walk_nodes(node[2])
                i = 3
                while i < len(node):
                    if i == len(node) - 1:
                        walk_nodes(node[i])
                        break
                    deps.update(get_dependencies(_convert_dot_sql(node[i][0])))
                    walk_nodes(node[i + 1])
                    i += 2
            elif name in {"#ifdef", "#ifndef"}:
                param = node[1].strip()
                if param.startswith(":"):
                    param = param[1:]
                param = param.replace(".", "__")
                deps.add(param)
                walk_nodes(node[2])
                if len(node) > 3:
                    walk_nodes(node[3])
            elif name == "#from":
                deps.update(get_dependencies(_convert_dot_sql("SELECT * FROM " + node[1][0])))
                if len(node) == 4:
                    walk_nodes(node[3])
                else:
                    walk_nodes(node[2])
            elif name == "#each":
                param = node[1].strip()
                if param.startswith(":"):
                    param = param[1:]
                param = param.replace(".", "__")
                deps.add(f"{param}__count")
                walk_nodes(node[2])
            elif name == "#render":
                _, rest = parsefirstword(node[1])
                if rest:
                    for expr in re.findall(r"=[^=]+(?:(?=\s+[A-Za-z_][A-Za-z0-9_.]*\s*=)|$)", rest):
                        deps.update(get_dependencies(_convert_dot_sql(expr[1:].strip())))
            else:
                for part in node[1:]:
                    if isinstance(part, list):
                        walk_nodes(part)
        # ignore other nodes

    walk_nodes(body)

    def walk_partials(parts):
        for val in parts.values():
            if len(val) == 2:
                b, sub = val
            else:
                _, b, sub = val
            walk_nodes(b)
            walk_partials(sub)

    walk_partials(partials)
    return deps

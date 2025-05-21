import re


def parsefirstword(s):
    s = s.strip()
    if s.find(' ') < 0:
        return s, None
    return s[:s.find(' ')], s[s.find(' '):].strip()


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
    parts = re.split(r'({{.*?}}}?)', source, flags=re.DOTALL)
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
            if '{{' in inner or '}}' in inner:
                snippet = _shorten_error_token(inner)
                raise SyntaxError(f"mismatched {{{{ in token: {snippet!r}")
            inner = inner.strip()
            if inner.startswith('!--') and inner.endswith('--'):
                pass  # Skip comment nodes
            elif inner.startswith('#') or inner.startswith('/'):
                nodes.append(parsefirstword(inner))
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


def _read_block(node_list, i, stop, partials):
    """Return (body, new_index) while filling *partials* dict in‑place."""
    body = []
    while i < len(node_list):
        ntype, ncontent = node_list[i]
        if ntype in stop:
            break

        # ------------------------------------------------------------- #if ...
        if ntype == "#if" or ntype == "#ifdef" or ntype == "#ifndef":
            if_terms = {"#elif", "#else", "/if", "/ifdef", "/ifndef"}  # inline terminators for this IF
            i += 1
            then_body, i = _read_block(node_list, i, if_terms, partials)
            else_body = None
            r = [ntype, ncontent, then_body]
            while i < len(node_list):
                k, c = node_list[i]
                if k == "#elif":
                    if ntype != "#if":
                        raise SyntaxError("{{#elif}} must be used with {{#if}}")
                    i += 1
                    elif_body, i = _read_block(node_list, i, if_terms, partials)
                    r.append(c)
                    r.append(elif_body)
                    continue
                if k == "#else":
                    i += 1
                    else_body, i = _read_block(node_list, i, if_terms, partials)
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
            i += 1
            loop_body, i = _read_block(node_list, i, from_terms, partials)
            if node_list[i][0] != "/from":
                raise SyntaxError("missing {{/from}}")
            i += 1
            body.append(["#from", query, loop_body])
            continue

        # -------------------------------------------------------- #partial ...
        if ntype == "#partial":
            part_terms = {"/partial"}
            first, rest = parsefirstword(ncontent)
            
            # Check if first token is a verb or 'public'
            if first in ["public", "get", "post", "put", "delete", "patch"]:
                partial_type = first.upper() if first != "public" else "PUBLIC"
                name = rest
            else:
                partial_type = None
                name = first
                
            i += 1
            partial_partials = {}
            part_body, i = _read_block(node_list, i, part_terms, partial_partials)
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

        # -------------------------------------------------------------- leaf --
        body.append((ntype, ncontent))
        i += 1
    return body, i

def build_ast(node_list):
    """
    Builds an abstract syntax tree from a list of nodes.
    
    Args:
        node_list: List of (type, content) tuples from tokenize()
        
    Returns:
        Tuple of (body, partials) where body is the AST and partials is a dict of partial definitions
        
    >>> nodes = [('text', 'hello'), ('#partial', 'test'), ('text', 'world'), ('/partial', '')]
    >>> build_ast(nodes)
    ([('text', 'hello')], {('test', None): [[('text', 'world')], {}]})
    >>> nodes = [('text', 'hello'), ('#if', 'x > 5'), ('text', 'big'), ('#else', ''), ('text', 'small'), ('/if', '')]
    >>> build_ast(nodes)
    ([('text', 'hello'), ['#if', 'x > 5', [('text', 'big')], [('text', 'small')]]], {})
    >>> nodes = [('text', 'hello'), ('#ifdef', 'x'), ('text', 'big'), ('#else', ''), ('text', 'small'), ('/ifdef', '')]
    >>> build_ast(nodes)
    ([('text', 'hello'), ['#ifdef', 'x', [('text', 'big')], [('text', 'small')]]], {})
    >>> nodes = [('text', 'hello'), ('#ifndef', 'x'), ('text', 'big'), ('#else', ''), ('text', 'small'), ('/ifndef', '')]
    >>> build_ast(nodes)
    ([('text', 'hello'), ['#ifndef', 'x', [('text', 'big')], [('text', 'small')]]], {})
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
    body, idx = _read_block(node_list, 0, set(), partials)
    if idx != len(node_list):
        raise SyntaxError("extra tokens after top‑level parse")
    return body, partials
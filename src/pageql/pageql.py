"""
Python API for the PageQL template engine (Dynamically Typed).

This module provides the PageQL class for programmatically loading, managing,
and rendering PageQL templates, primarily intended for testing purposes.

Classes:
    PageQL: The main engine class.
    RenderResult: Holds the output of a render operation.
"""

# Instructions for LLMs and devs: Keep the code short. Make changes minimal. Don't change even tests too much.

import re, time, sys, json, hashlib, base64
import doctest
import sqlite3
import html
import pathlib

if __package__ is None:                      # script / doctest-by-path
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


from pageql.parser import tokenize, parsefirstword, build_ast, add_reactive_elements
from pageql.reactive import (
    Signal,
    DerivedSignal,
    DerivedSignal2,
    OneValue,
    get_dependencies,
    Tables,
    ReadOnly,
)
from pageql.reactive_sql import parse_reactive, _replace_placeholders
import sqlglot

def flatten_params(params):
    """
    Recursively flattens a nested dictionary using __ separator.
    
    Args:
        params: A dictionary, potentially containing nested dictionaries
        
    Returns:
        A flattened dictionary
        
    Example:
        >>> flatten_params({"a": {"b": "c"}})
        {'a__b': 'c'}
        >>> flatten_params({"x": 1, "y": {"z": 2, "w": {"v": 3}}})
        {'x': 1, 'y__z': 2, 'y__w__v': 3}
    """
    result = {}
    for key, value in params.items():
        if isinstance(value, dict):
            flattened = flatten_params(value)
            for k, v in flattened.items():
                result[f"{key}__{k}"] = v
        else:
            result[key] = value
    return result

def parse_param_attrs(s):
    """Parse attributes from a ``#param`` directive.

    Handles optional whitespace around the ``=`` sign and quoted values.
    Tokens with an ``=`` but no following value are treated as boolean flags
    equivalent to specifying just the name.

    Example::

        >>> parse_param_attrs("a=1 b = 2 c")
        {'a': '1', 'b': '2', 'c': True}
        >>> parse_param_attrs("a='hello world' optional")
        {'a': 'hello world', 'optional': True}
        >>> parse_param_attrs("a=1 b=2 flag")
        {'a': '1', 'b': '2', 'flag': True}
    """

    if not s:
        return {}

    attrs: dict[str, object] = {}
    token_re = re.compile(r'(\w+)(?:\s*=\s*("[^"]*"|\'[^\']*\'|\S+))?')

    for match in token_re.finditer(s):
        key = match.group(1)
        value = match.group(2)
        if value is None:
            attrs[key] = True
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        attrs[key] = value

    return attrs

# Short descriptions for valid PageQL directives. Each entry includes a
# minimal syntax reminder to make the help output more useful.
DIRECTIVE_HELP: dict[str, str] = {
    "#create <sql>": "execute an SQL CREATE statement",
    "#delete from <table> where <cond>": "execute an SQL DELETE query",
    "#dump <table>": "dump a table's contents",
    "#from <select>": "iterate SQL query results",
    "#if <expr>": "conditional block",
    "#ifdef <var>": "branch if variable defined",
    "#ifndef <var>": "branch if variable not defined",
    "#import <module>": "import another module",
    "#insert into <table> (cols) values (vals)": "execute an SQL INSERT",
    "#log <message>": "log a message",
    "#merge <sql>": "execute an SQL MERGE",
    "#param <name> [type] [attrs]": "declare and validate a request parameter",
    "#partial <name>": "define a reusable partial block",
    "#reactive on|off": "toggle reactive rendering mode",
    "#redirect <url>": "issue an HTTP redirect",
    "#render <name>": "render a named partial",
    "#set <name> <expr>": "assign a variable from an expression",
    "#statuscode <code>": "set the HTTP status code",
    "#update <table> set <expr> where <cond>": "execute an SQL UPDATE",
}

def format_unknown_directive(directive: str) -> str:
    """Return a helpful error message for unknown directives."""
    lines = [f"Unknown directive '{directive}'. Valid directives:<pre>"]
    for name, desc in DIRECTIVE_HELP.items():
        lines.append(f"  {name:8} - {desc}")
    return "\n".join(lines) + "</pre>"


# Define RenderResult as a simple class
class RenderResult:
    """Holds the results of a render operation."""

    def __init__(self, status_code=200, headers=None, body="", context=None):
        if headers is None:
            headers = []
        self.body = body
        self.status_code = status_code
        self.headers = headers  # List of (name, value) tuples
        self.redirect_to = None
        self.context = context


class RenderContext:
    """Track state for a single render pass."""

    def __init__(self):
        self.next_id = 0
        self.initialized = False
        self.listeners = []
        self.out = []
        self.scripts: list[str] = []
        self.send_script = None
        self.rendering = True
        self.reactiveelement = None

    def ensure_init(self):
        if not self.initialized:
            self.initialized = True

    def marker_id(self) -> int:
        mid = self.next_id
        self.next_id += 1
        return mid

    def add_listener(self, signal, listener):
        signal.listeners.append(listener)
        self.listeners.append((signal, listener))

    def add_dependency(self, signal):
        """Track *signal* for cleanup without reacting to updates."""
        self.add_listener(signal, lambda *_: None)

    def cleanup(self):
        for signal, listener in self.listeners:
            signal.remove_listener(listener)
        self.listeners.clear()

    def clear_output(self):
        self.out.clear()

    def append_script(self, content, out=None):
        if out is None:
            out = self.out

        send_directly = out is self.out and not self.rendering

        if not send_directly:
            # Avoid prematurely closing the script tag if ``content`` contains
            # the ``</script>`` sequence by escaping it. This can happen when
            # reactive HTML snippets include nested ``<script>`` tags that are
            # inserted via ``pinsert`` or ``pupdate``.
            # Escape any nested ``</script>`` sequences to avoid prematurely
            # terminating the surrounding script tag. Using a double backslash
            # prevents ``SyntaxWarning: invalid escape sequence`` from Python
            # while producing the desired ``<\/script>`` string in HTML.
            safe_content = content.replace("</script>", "<\\/script>")
            out.append(f"<script>{safe_content}</script>")
        else:
            if self.send_script is not None:
                self.send_script(content)
            else:
                self.scripts.append(content)


def db_execute_dot(db, exp, params):
    """
    Executes an SQL expression after converting dot notation parameters to double underscore format.
    
    Args:
        db: SQLite database connection
        exp: SQL expression string
        params: Parameters dictionary
        
    Returns:
        The result of db.execute()
        
    Example:
        >>> db = sqlite3.connect(":memory:")
        >>> cursor = db_execute_dot(db, "select :user.name", {"user__name": "John"})
        >>> cursor.fetchone()[0]
        'John'
        >>> cursor = db_execute_dot(db, "select :headers.meta.title", {"headers__meta__title": "Page"})
        >>> cursor.fetchone()[0]
        'Page'
    """
    # Convert :param.name.subname to :param__name__subname in the expression
    converted_exp = re.sub(r':([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)',
                          lambda m: ':' + m.group(1).replace('.', '__'),
                          exp)
    converted_params = {}
    for k, v in params.items():
        if isinstance(v, (DerivedSignal, ReadOnly)):
            converted_params[k] = v.value
        else:
            converted_params[k] = v
    return db.execute(converted_exp, converted_params)

def evalone(db, exp, params, reactive=False, tables=None, expr=None):
    exp = exp.strip()
    if re.match("^:?[a-zA-z._][a-zA-z._0-9]*$", exp):
        if exp[0] == ':':
            exp = exp[1:]
        exp = exp.replace('.', '__')
        if exp in params:
            val = params[exp]
            if reactive:
                if isinstance(val, Signal):
                    return val
                if isinstance(val, ReadOnly):
                    return val.value
                signal = DerivedSignal(lambda v=val: v, [])
                params[exp] = signal
                return signal
            if isinstance(val, (DerivedSignal, ReadOnly)):
                return val.value
            return val
        
    if not re.match(r"(?i)^\s*(select|\(select)", exp):
        exp = "select " + exp

    if reactive:
        sql = re.sub(
            r':([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)',
            lambda m: ':' + m.group(1).replace('.', '__'),
            exp,
        )
        if tables is None:
            tables = Tables(db)
        dep_names = [name.replace('.', '__') for name in get_dependencies(sql)]
        for name in dep_names:
            val = params.get(name)
            if val is not None and not isinstance(val, (Signal, ReadOnly)):
                params[name] = ReadOnly(val)
        deps = [params[name] for name in dep_names if isinstance(params[name], Signal)]
        def _build():
            nonlocal expr
            if expr is None:
                expr = sqlglot.parse_one(sql)
            #print("parse_reactive: ", expr.sql())
            comp = parse_reactive(expr, tables, params, one_value=True)
            return comp

        dv = DerivedSignal2(_build, deps)

        return dv

    try:
        r = db_execute_dot(db, exp, params).fetchone()
        if len(r) != 1:
            raise ValueError(f"SQL expression `{exp}` with params `{params}` returned {len(r)} rows, expected 1")
        return r[0]
    except sqlite3.Error as e:
        raise ValueError(f"Error evaluating SQL expression `{exp}` with params `{params}`: {e}")


class RenderResultException(Exception):
    """
    Exception raised when a render result is returned from a render call.
    """
    def __init__(self, render_result):
        self.render_result = render_result

class PageQL:
    """
    Manages and renders PageQL templates against an SQLite database.

    Attributes:
        db_path: Path to the SQLite database file.
        _modules: Internal storage for loaded module source strings or parsed nodes.
    """

    def __init__(self, db_path):
        """
        Initializes the PageQL engine instance.

        Args:
            db_path: Path to the SQLite database file to be used.
        """
        self._modules = {} # Store parsed node lists here later
        self._parse_errors = {} # Store errors here
        self.db = sqlite3.connect(db_path)
        # Configure SQLite for web server usage
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute("PRAGMA temp_store=MEMORY")
            self.db.execute("PRAGMA cache_size=10000")
        self.tables = Tables(self.db)
        self._from_cache = {}

    def load_module(self, name, source):
        """
        Loads and parses PageQL source code into an AST (Abstract Syntax Tree).

        Args:
            name: The logical name of the module.
            source: A string containing the raw .pageql template code.

        Example:
            >>> r = PageQL(":memory:")
            >>> source_with_comment = '''
            ... Start Text.
            ... {{!-- This is a comment --}}
            ... End Text.
            ... '''
            >>> # Verify loading doesn't raise an error
            >>> r.load_module("comment_test", source_with_comment)
            >>> # Verify the module was stored
            >>> "comment_test" in r._modules
            True
            >>> r.load_module("a/b/c", source_with_comment)
            >>> "a/b/c" in r._modules
            True
        """
        if name in self._modules:
            del self._modules[name]
        if name in self._parse_errors:
            del self._parse_errors[name]
        # Tokenize the source and build AST
        try:
            tokens = tokenize(source)
            body, partials = build_ast(tokens)
            body = add_reactive_elements(body)

            def _apply(parts):
                for k, v in parts.items():
                    if k[0] == ':':
                        v[1] = add_reactive_elements(v[1])
                        _apply(v[2])
                    else:
                        v[0] = add_reactive_elements(v[0])
                        _apply(v[1])

            _apply(partials)
            self._modules[name] = [body, partials]
        except Exception as e:
            print(f"Error parsing module {name}: {e}")
            self._parse_errors[name] = e
        
    def handle_param(self, node_content, params):
        """
        Handles parameter validation and processing for #param nodes.
        
        Args:
            node_content: The content of the #param node
            params: Current parameters dictionary
            
        Returns:
            Tuple of (param_name, param_value) after validation
        """
        param_name, attrs_str = parsefirstword(node_content)
        attrs = parse_param_attrs(attrs_str)

        is_required = attrs.get('required', not attrs.__contains__('optional')) # Default required
        param_value = params.get(param_name) # Get from input params dict

        if param_value is None:
            if 'default' in attrs:
                param_value = attrs['default']
                is_required = False # Default overrides required check if param missing
            elif is_required:
                raise ValueError(f"Required parameter '{param_name}' is missing")

        # --- Basic Validation (Type, Minlength) ---
        if param_value is not None: # Only validate if value exists
            param_type = attrs.get('type', 'string')
            try:
                if param_type == 'integer':
                    param_value = int(param_value)
                elif param_type == 'boolean': # Basic truthiness
                    param_value = bool(param_value) and str(param_value).lower() not in ['0', 'false', '']
                # Add float later if needed
                else: # Default to string
                    param_value = str(param_value)

                if param_type == 'string' and 'minlength' in attrs:
                    minlen = int(attrs['minlength'])
                    if len(param_value) < minlen:
                        raise ValueError(f"Parameter '{param_name}' length {len(param_value)} is less than minlength {minlen}.")
                if param_type == 'string' and 'maxlength' in attrs:
                    maxlen = int(attrs['maxlength'])
                    if len(param_value) > maxlen:
                        raise ValueError(f"Parameter '{param_name}' length {len(param_value)} is greater than maxlength {maxlen}.")
                if param_type == 'string' and 'pattern' in attrs:
                    pattern = attrs['pattern']
                    if not re.match(pattern, param_value):
                        raise ValueError(f"Parameter '{param_name}' does not match pattern '{pattern}'.")
                if param_type == 'integer' and 'min' in attrs:
                    minval = int(attrs['min'])
                    if param_value < minval:
                        raise ValueError(f"Parameter '{param_name}' value {param_value} is less than min {minval}.")
                if param_type == 'integer' and 'max' in attrs:
                    maxval = int(attrs['max'])
                    if param_value > maxval:
                        raise ValueError(f"Parameter '{param_name}' value {param_value} is greater than max {maxval}.")
                if param_type == 'boolean' and 'required' in attrs:
                    if param_value is None:
                        raise ValueError(f"Parameter '{param_name}' is required but was not provided.")
            except (ValueError, TypeError) as e:
                raise ValueError(f"Parameter '{param_name}' failed type/validation '{param_type}': {e}")
        
        return param_name, param_value

    def handle_render(self, node_content, path, params, includes,
                     http_verb=None, reactive=False, ctx=None):
        """
        Handles the #render directive processing.
        
        Args:
            node_content: The content of the #render node
            path: The current request path
            params: Current parameters dictionary
            includes: Dictionary mapping module aliases to real paths
            http_verb: Optional HTTP verb for accessing verb-specific partials
            ctx: Optional :class:`RenderContext` to reuse for nested renders
            
        Returns:
            The rendered content as a string
        """
        partial_name_str, args_str = parsefirstword(node_content)
        partial_names = []
        render_params = params.copy()
        
        # Use uppercase HTTP verb for consistency
        if http_verb:
            http_verb = http_verb.upper()

        # Check if the partial name is in the includes dictionary
        render_path = path

        current_path = partial_name_str
        partial_parts = []
        
        while '/' in current_path and current_path not in includes:
            module_part, partial_part = current_path.rsplit('/', 1)
            partial_parts.insert(0, partial_part)
            current_path = module_part
        
        # Check if we found a valid module
        if current_path in includes:
            render_path = includes[current_path]  # Use the real module path
            partial_names = partial_parts  # Set the partial names to look for
        else:
            # Not found as an import, try all in local module
            partial_names = partial_name_str.split('/')
        
        # Parse key=value expressions from args_str and update render_params
        if args_str:
            # Simple parsing: find key=, evaluate value expression until next key= or end
            current_pos = 0
            while current_pos < len(args_str):
                args_part = args_str[current_pos:].lstrip()
                if not args_part: break
                eq_match = re.search(r"=", args_part)
                if not eq_match: break # Malformed args

                key = args_part[:eq_match.start()].strip()
                if not key or not key.isidentifier(): break # Invalid key

                value_start_pos = eq_match.end()
                # Find where the value expression ends (before next ' key=' or end)
                next_key_match = re.search(r"\s+[a-zA-Z_][a-zA-Z0-9_.]*\s*=", args_part[value_start_pos:])
                value_end_pos = value_start_pos + next_key_match.start() if next_key_match else len(args_part)
                value_expr = args_part[value_start_pos:value_end_pos].strip()
                # Advance scanner position based on the slice we just processed
                current_pos += value_end_pos

                if value_expr:
                    try:
                        evaluated_value = evalone(
                            self.db, value_expr, params, reactive, self.tables
                        )
                        if isinstance(evaluated_value, Signal) and ctx:
                            ctx.add_dependency(evaluated_value)
                        render_params[key] = evaluated_value
                    except Exception as e:
                        raise Exception(
                            f"Warning: Error evaluating SQL expression `{value_expr}` for key `{key}` in #render: {e}"
                        )
                else:
                    raise Exception(f"Warning: Empty value expression for key `{key}` in #render args")

        # Perform the recursive render call with the potentially modified parameters
        result = self.render(
            render_path,
            render_params,
            partial_names,
            http_verb,
            in_render_directive=True,
            reactive=reactive,
            ctx=ctx,
        )
        if result.status_code == 404:
            raise ValueError(f"handle_render: Partial or import '{partial_name_str}' not found with http verb {http_verb}, render_path: {render_path}, partial_names: {partial_names}")
        
        # Clean up the output to match expected format
        return result.body.rstrip()

    def process_node(self, node, params, path, includes, http_verb=None, reactive=False, ctx=None, out=None):
        """
        Process a single AST node and append its rendered output to the buffer.
        
        Args:
            node: The AST node to process
            params: Current parameters dictionary
            path: Current request path
            includes: Dictionary of imported modules
            http_verb: Optional HTTP verb for accessing verb-specific partials
            
        Returns:
            None (output is appended to *out* or ctx.out)
        """
        if out is None:
            out = ctx.out

        if isinstance(node, tuple):
            node_type, node_content = node

            if node_type == 'text':
                out.append(node_content)
            elif node_type == 'render_expression':
                result = evalone(self.db, node_content, params, reactive, self.tables)
                if isinstance(result, Signal):
                    signal = result
                    result = result.value
                else:
                    signal = None
                value = html.escape(str(result))
                if ctx.reactiveelement is not None:
                    out.append(value)
                    if signal:
                        ctx.reactiveelement.append(signal)
                elif reactive and signal is not None:
                    ctx.ensure_init()
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})", out)
                    out.append(value)
                    ctx.append_script(f"pend({mid})", out)
                    def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                        ctx.ensure_init()
                        ctx.append_script(
                            f"pset({mid},{json.dumps(html.escape(str(sig.value)))})",
                            out,
                        )
                    ctx.add_listener(signal, listener)
                else:
                    out.append(value)
            elif node_type == 'render_param':
                try:
                    val = params[node_content]
                    if isinstance(val, ReadOnly):
                        out.append(html.escape(str(val.value)))
                    else:
                        signal = val if isinstance(val, Signal) else None
                        if isinstance(val, Signal):
                            val = val.value
                        value = html.escape(str(val))
                        if ctx.reactiveelement is not None:
                            out.append(value)
                            if signal:
                                ctx.reactiveelement.append(signal)
                        elif reactive:
                            ctx.ensure_init()
                            mid = ctx.marker_id()
                            ctx.append_script(f"pstart({mid})", out)
                            out.append(value)
                            ctx.append_script(f"pend({mid})", out)
                            if signal:
                                def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                                    ctx.ensure_init()
                                    ctx.append_script(f"pset({mid},{json.dumps(html.escape(str(sig.value)))})", out)
                                ctx.add_listener(signal, listener)
                        else:
                            out.append(value)
                except KeyError:
                    raise ValueError(f"Parameter `{node_content}` not found in params `{params}`")
            elif node_type == 'render_raw':
                result = evalone(self.db, node_content, params, reactive, self.tables)
                if isinstance(result, Signal):
                    signal = result
                    result = result.value
                else:
                    signal = None
                value = str(result)
                if ctx.reactiveelement is not None:
                    out.append(value)
                    if signal:
                        ctx.reactiveelement.append(signal)
                elif reactive and signal is not None:
                    ctx.ensure_init()
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})", out)
                    out.append(value)
                    ctx.append_script(f"pend({mid})", out)
                    def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                        ctx.ensure_init()
                        ctx.append_script(
                            f"pset({mid},{json.dumps(str(sig.value))})",
                            out,
                        )
                    ctx.add_listener(signal, listener)
                else:
                    out.append(value)
            elif node_type == '#param':
                param_name, param_value = self.handle_param(node_content, params)
                params[param_name] = param_value
            elif node_type == '#set':
                var, sql, expr = node_content
                if var[0] == ':':
                    var = var[1:]
                var = var.replace('.', '__')
                if var in params:
                    raise ValueError(f"Parameter '{var}' is already set")
                if isinstance(params.get(var), ReadOnly):
                    raise ValueError(f"Parameter '{var}' is read only")
                if reactive:
                    value = evalone(self.db, sql, params, True, self.tables, expr)
                    existing = params.get(var)
                    if isinstance(existing, Signal):
                        if isinstance(value, Signal):
                            def update(v=None, *, src=value, dst=existing):
                                dst.set_value(src.value)
                            value.listeners.append(update)
                            existing.set_value(value.value)
                        else:
                            existing.set_value(value)
                        signal = existing
                    else:
                        signal = value if isinstance(value, Signal) else DerivedSignal(lambda v=value: v, [])
                        params[var] = signal
                    # Track dependency so cleanup detaches it after rendering
                    ctx.add_dependency(signal)
                else:
                    params[var] = evalone(self.db, sql, params, False, self.tables, expr)
            elif node_type == '#render':
                rendered_content = self.handle_render(
                    node_content,
                    path,
                    params,
                    includes,
                    None,
                    reactive,
                    ctx,
                )
                ctx.out.append(rendered_content)
            elif node_type == '#reactive':
                mode = node_content.strip().lower()
                if mode == 'on':
                    reactive = True
                elif mode == 'off':
                    reactive = False
                else:
                    raise ValueError(f"Unknown reactive mode '{node_content}'")
                params['reactive'] = reactive
            elif node_type == '#redirect':
                url = evalone(self.db, node_content, params, reactive, self.tables)
                raise RenderResultException(RenderResult(status_code=302, headers=[('Location', url)]))
            elif node_type == '#statuscode':
                code = evalone(self.db, node_content, params, reactive, self.tables)
                raise RenderResultException(RenderResult(status_code=code, body="".join(ctx.out)))
            elif node_type in ("#update", "#insert", "#delete"):
                try:
                    # Use the reactive table helpers for data modifications so
                    # listeners get notified even outside reactive mode.
                    self.tables.executeone(node_type[1:] + " " + node_content, params)
                except sqlite3.Error as e:
                    raise ValueError(
                        f"Error executing {node_type[1:]} {node_content} with params {params}: {e}"
                    )
            elif node_type in ("#create", "#merge"):
                try:
                    db_execute_dot(self.db, node_type[1:] + " " + node_content, params)
                except sqlite3.Error as e:
                    raise ValueError(
                        f"Error executing {node_type[1:]} {node_content} with params {params}: {e}"
                    )
            elif node_type == '#import':
                parts = node_content.split()
                if not parts:
                    raise ValueError("Empty import statement")
                    
                module_path = parts[0]
                alias = parts[2] if len(parts) > 2 and parts[1] == 'as' else module_path
                
                if module_path not in self._modules:
                    raise ValueError(f"Module '{module_path}' not found, modules: " + str(self._modules.keys()))
                
                includes[alias] = module_path
            elif node_type == '#log':
                print(
                    "Logging: " + str(evalone(self.db, node_content, params, reactive, self.tables))
                )
            elif node_type == '#dump':
                # fetchall the table and dump it
                cursor = db_execute_dot(self.db, "select * from " + node_content, params)
                t = time.time()
                all = cursor.fetchall()
                end_time = time.time()
                ctx.out.append("<table>")
                for col in cursor.description:
                    ctx.out.append("<th>" + col[0] + "</th>")
                ctx.out.append("</tr>")
                for row in all:
                    ctx.out.append("<tr>")
                    for cell in row:
                        ctx.out.append("<td>" + str(cell) + "</td>")
                    ctx.out.append("</tr>")
                ctx.out.append("</table>")
                ctx.out.append(f"<p>Dumping {node_content} took {(end_time - t)*1000:.2f} ms</p>")
            else:
                if not node_type.startswith('/'):
                    raise ValueError(format_unknown_directive(node_type))

            return reactive
        elif isinstance(node, list):
            directive = node[0]
            if directive == '#reactiveelement':
                prev = ctx.reactiveelement
                ctx.reactiveelement = []
                buf = []
                self.process_nodes(
                    node[1],
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                    out=buf,
                )
                signals = ctx.reactiveelement
                ctx.reactiveelement = prev
                out.extend(buf)
                if reactive and ctx:
                    ctx.ensure_init()
                    mid = ctx.marker_id()
                    ctx.append_script(f"pprevioustag({mid})", out)

                    def listener(_=None, *, mid=mid, ctx=ctx):
                        ctx.ensure_init()
                        new_buf = []
                        cur = ctx.reactiveelement
                        ctx.reactiveelement = []
                        self.process_nodes(
                            node[1],
                            params,
                            path,
                            includes,
                            http_verb,
                            True,
                            ctx,
                            out=new_buf,
                        )
                        ctx.reactiveelement = cur
                        html_content = "".join(new_buf).strip()
                        tag = ''
                        if html_content.startswith('<'):
                            m = re.match(r'<([A-Za-z0-9_-]+)', html_content)
                            if m:
                                tag = m.group(1)
                        void_elements = {
                            'area','base','br','col','embed','hr','img','input',
                            'link','meta','param','source','track','wbr'
                        }
                        if (
                            tag
                            and tag.lower() not in void_elements
                            and not re.search(r'/\s*>$', html_content)
                            and not html_content.endswith(f'</{tag}>')
                        ):
                            html_content += f"</{tag}>"
                        ctx.append_script(
                            f"pupdatetag({mid},{json.dumps(html_content)})",
                            out,
                        )

                    for sig in signals:
                        ctx.add_listener(sig, listener)
                return reactive
            if directive == '#if':
                if reactive and ctx:
                    cond_exprs = []
                    bodies = []
                    j = 1
                    while j < len(node):
                        if j + 1 < len(node):
                            cond_exprs.append(node[j])
                            bodies.append(node[j + 1])
                            j += 2
                        else:
                            cond_exprs.append(None)
                            bodies.append(node[j])
                            j += 1

                    cond_vals = [
                        evalone(self.db, ce[0], params, True, self.tables, ce[1]) if ce is not None else True
                        for ce in cond_exprs
                    ]
                    signals = [v for v in cond_vals if isinstance(v, Signal)]

                    def pick_index():
                        for idx, val in enumerate(cond_vals):
                            cur = val.value if isinstance(val, Signal) else val
                            if cur:
                                return idx
                        return None

                    if ctx.reactiveelement is not None:
                        idx = pick_index()
                        if idx is not None:
                            reactive = self.process_nodes(
                                bodies[idx],
                                params,
                                path,
                                includes,
                                http_verb,
                                True,
                                ctx,
                                out,
                            )
                        ctx.reactiveelement.extend(signals)
                    else:
                        mid = ctx.marker_id()
                        ctx.ensure_init()
                        ctx.append_script(f"pstart({mid})", out)

                        idx = pick_index()
                        if idx is not None:
                            reactive = self.process_nodes(
                                bodies[idx],
                                params,
                                path,
                                includes,
                                http_verb,
                                reactive,
                                ctx,
                                out,
                            )

                        ctx.append_script(f"pend({mid})", out)

                        def listener(_=None, *, mid=mid, ctx=ctx):
                            ctx.ensure_init()
                            new_idx = pick_index()
                            buf = []
                            if new_idx is not None:
                                self.process_nodes(
                                    bodies[new_idx],
                                    params,
                                    path,
                                    includes,
                                    http_verb,
                                    True,
                                    ctx,
                                    out=buf,
                                )
                            html_content = "".join(buf).strip()
                            ctx.append_script(
                                f"pset({mid},{json.dumps(html_content)})",
                                out,
                            )

                        for sig in signals:
                            ctx.add_listener(sig, listener)
                else:
                    i = 1
                    while i < len(node):
                        if i + 1 < len(node):
                            expr = node[i]
                            if not evalone(self.db, expr[0], params, reactive, self.tables, expr[1]):
                                i += 2
                                continue
                            i += 1
                        reactive = self.process_nodes(
                            node[i],
                            params,
                            path,
                            includes,
                            http_verb,
                            reactive,
                            ctx,
                            out,
                        )
                        i += 1
            elif directive == '#ifdef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name in params:
                    reactive = self.process_nodes(
                        then_body,
                        params,
                        path,
                        includes,
                        http_verb,
                        reactive,
                        ctx,
                        out,
                    )
                elif else_body:
                    reactive = self.process_nodes(
                        else_body,
                        params,
                        path,
                        includes,
                        http_verb,
                        reactive,
                        ctx,
                        out,
                    )
            elif directive == '#ifndef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name not in params:
                    reactive = self.process_nodes(
                        then_body,
                        params,
                        path,
                        includes,
                        http_verb,
                        reactive,
                        ctx,
                        out,
                    )
                elif else_body:
                    reactive = self.process_nodes(
                        else_body,
                        params,
                        path,
                        includes,
                        http_verb,
                        reactive,
                        ctx,
                        out,
                    )
            elif directive == '#from':
                query, expr = node[1]
                body = node[2]

                if reactive:
                    sql = "SELECT * FROM " + query
                    sql = re.sub(r':([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)',
                                 lambda m: ':' + m.group(1).replace('.', '__'),
                                 sql)
                    converted_params = {
                        k: (v.value if isinstance(v, (DerivedSignal, ReadOnly)) else v)
                        for k, v in params.items()
                    }
                    expr_copy = expr.copy()
                    _replace_placeholders(expr_copy, converted_params)
                    cache_key = expr_copy.sql()
                    comp = self._from_cache.get(cache_key)
                    if comp is None or not comp.listeners:
                        comp = parse_reactive(expr, self.tables, params)
                        self._from_cache[cache_key] = comp
                    cursor = self.db.execute(comp.sql, converted_params)
                    col_names = comp.columns if not isinstance(comp.columns, str) else [comp.columns]
                else:
                    cursor = db_execute_dot(self.db, "select * from " + query, params)
                    col_names = [col[0] for col in cursor.description]

                rows = cursor.fetchall()
                mid = None
                if ctx and reactive:
                    ctx.ensure_init()
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})")
                saved_params = params.copy()
                for row in rows:
                    row_params = params.copy()
                    for i, col_name in enumerate(col_names):
                        row_params[col_name] = ReadOnly(row[i])

                    row_buffer = []
                    self.process_nodes(body, row_params, path, includes, http_verb, reactive, ctx, out=row_buffer)
                    row_content = ''.join(row_buffer).strip()
                    if ctx and reactive:
                        row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(row)).encode()).digest())[:8].decode()}"
                        ctx.ensure_init()
                        ctx.append_script(f"pstart('{row_id}')")
                        ctx.out.append(row_content)
                        ctx.append_script(f"pend('{row_id}')")
                    else:
                        ctx.out.append(row_content)
                    ctx.out.append('\n')

                if ctx and reactive:
                    ctx.append_script(f"pend({mid})")
                    def on_event(ev, *, mid=mid, ctx=ctx,
                                   body=body, col_names=col_names, path=path,
                                   includes=includes, http_verb=http_verb,
                                   saved_params=saved_params):
                        if ev[0] == 2:
                            row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                            ctx.ensure_init()
                            ctx.append_script(f"pdelete('{row_id}')")
                        elif ev[0] == 1:
                            row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                            row_params = saved_params.copy()
                            for i, col_name in enumerate(col_names):
                                row_params[col_name] = ReadOnly(ev[1][i])
                            row_buf = []
                            self.process_nodes(body, row_params, path, includes, http_verb, True, ctx, out=row_buf)
                            row_content = ''.join(row_buf).strip()
                            ctx.ensure_init()
                            ctx.append_script(f"pinsert('{row_id}',{json.dumps(row_content)})")
                        elif ev[0] == 3:
                            old_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                            new_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[2])).encode()).digest())[:8].decode()}"
                            row_params = saved_params.copy()
                            for i, col_name in enumerate(col_names):
                                row_params[col_name] = ReadOnly(ev[2][i])
                            row_buf = []
                            self.process_nodes(body, row_params, path, includes, http_verb, True, ctx, out=row_buf)
                            row_content = ''.join(row_buf).strip()
                            ctx.ensure_init()
                            ctx.append_script(f"pupdate('{old_id}','{new_id}',{json.dumps(row_content)})")
                    ctx.add_listener(comp, on_event)

                params.clear()
                params.update(saved_params)
            else:
                if not directive.startswith('/'):
                    raise ValueError(format_unknown_directive(directive))
            return reactive

            return reactive

    def process_nodes(self, nodes, params, path, includes, http_verb=None, reactive=False, ctx=None, out=None):
        """
        Process a list of AST nodes and append their rendered output to the buffer.
        
        Args:
            nodes: List of AST nodes to process
            params: Current parameters dictionary
            path: Current request path
            includes: Dictionary of imported modules
            http_verb: Optional HTTP verb for accessing verb-specific partials
            
        Returns:
            None (output is appended to *out* or ctx.out)
        """
        if out is None:
            out = ctx.out

        for node in nodes:
            reactive = self.process_node(node, params, path, includes, http_verb, reactive, ctx, out)
        return reactive

    def render(self, path, params={}, partial=None, http_verb=None,
               in_render_directive=False, reactive=False, ctx=None):
        """
        Renders a module using its parsed AST.

        Args:
            path: The request path string (e.g., "/todos").
            params: An optional dictionary.
            partial: Name of partial to render instead of the full template.
            http_verb: Optional HTTP verb for accessing verb-specific partials.
            ctx: Optional :class:`RenderContext` to reuse when rendering
                 recursively.  A new context is created when omitted.

        Returns:
            A RenderResult object.

        Additional examples are provided in tests/test_render_docstring.py.
        """
        module_name = path.strip('/')
        params = flatten_params(params)
        if reactive:
            for k, v in list(params.items()):
                if not isinstance(v, DerivedSignal):
                    params[k] = DerivedSignal(lambda v=v: v, [])
        params['reactive'] = reactive
        
        # Convert partial to list if it's a string
        partial_path = []
        if partial and isinstance(partial, str):
            partial = partial.split('/')
            partial_path = partial
        
        # Convert http_verb to uppercase for consistency
        if http_verb:
            http_verb = http_verb.upper()

        # --- Handle partial path mapping ---
        original_module_name = module_name
        
        # If the module isn't found directly, try to interpret it as a partial path
        while '/' in module_name and module_name not in self._modules and module_name not in self._parse_errors:
            module_name, partial_segment = module_name.rsplit('/', 1)
            partial_path.insert(0, partial_segment)
        
           # --- Start Rendering ---
        result = RenderResult()
        result.status_code = 200

        try:
            if self._parse_errors.get(module_name):
                raise ValueError(
                    f"Error parsing module {module_name}: {self._parse_errors[module_name]}"
                )
            if module_name in self._modules:
                own_ctx = ctx is None
                if own_ctx:
                    ctx = RenderContext()
                includes = {None: module_name}  # Dictionary to track imported modules
                module_body, partials = self._modules[module_name]
                
                # If we have partial segments and no explicit partial list was provided
                if partial_path and not partial:
                    partial = partial_path
                while partial and len(partial) > 1:
                    if (partial[0], None) in partials:
                        partials = partials[(partial[0], None)][1]
                        partial = partial[1:]
                    elif (partial[0], "PUBLIC") in partials:
                        partials = partials[(partial[0], "PUBLIC")][1]
                        partial = partial[1:]
                    elif (':', None) in partials:
                        value = partials[(':', None)]
                        if in_render_directive:
                            if value[0] != partial[0]:
                                raise ValueError(f"Partial '{partial}' not found in module, found '{value[0]}'")
                        else:
                            params[value[0][1:]] = partial[0]
                        partials = value[2]
                        partial = partial[1:]
                    else:
                        raise ValueError(f"Partial '{partial}' not found in module '{module_name}'")
                if partial:
                    partial_name = partial[0]
                    http_key = (partial_name, http_verb)
                    http_key_public = (partial_name, "PUBLIC")
                    if http_key in partials or http_key_public in partials:
                        body = partials[http_key][0] if http_key in partials else partials[http_key_public][0]
                        reactive = self.process_nodes(body, params, path, includes, http_verb, reactive, ctx)
                    elif (':', None) in partials or (':', 'PUBLIC') in partials or (':', http_verb) in partials:
                        value = partials[(':', http_verb)] if (':', http_verb) in partials else partials[(':', None)] if (':', None) in partials else partials[(':', 'PUBLIC')]
                        if in_render_directive:
                            if value[0] != partial[0]:
                                raise ValueError(f"Partial '{partial}' not found in module, found '{value[0]}'")
                        else:
                            params[value[0][1:]] = partial[0]
                        partials = value[2]
                        partial = partial[1:]
                        reactive = self.process_nodes(value[1], params, path, includes, http_verb, reactive, ctx)
                    else:
                        raise ValueError(f"render: Partial '{partial_name}' with http verb '{http_verb}' not found in module '{module_name}'")
                else:
                    # Render the entire module
                    reactive = self.process_nodes(module_body, params, path, includes, http_verb, reactive, ctx)

                result.body = "".join(ctx.out)
                ctx.clear_output()

                # Store the render context so callers can keep it if needed
                result.context = ctx

                # Clean up listeners only when not rendering reactively
                if not reactive and own_ctx:
                    ctx.cleanup()

                # Process the output to match the expected format in tests
                result.body = result.body.replace('\n\n', '\n')  # Normalize extra newlines
                if own_ctx:
                    ctx.rendering = False
            else:
                result.status_code = 404
                result.body = f"Module {original_module_name} not found"
        except RenderResultException as e:
            self.db.commit()
            return e.render_result
        self.db.commit()
        return result

# Example of how to run the examples if this file is executed
if __name__ == '__main__':
    # add current directory to sys.path
    
    # Run doctests, ignoring extra whitespace in output and blank lines
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL)
    
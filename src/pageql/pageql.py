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
import os
import html
import pathlib
from urllib.parse import urlparse

if __package__ is None:                      # script / doctest-by-path
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


from pageql.parser import tokenize, parsefirstword, build_ast, add_reactive_elements
from pageql.reactive import (
    Signal,
    DerivedSignal,
    DerivedSignal2,
    derive_signal2,
    OneValue,
    get_dependencies,
    Tables,
    ReadOnly,
    _convert_dot_sql,
)
from pageql.render_context import RenderContext, RenderResult, RenderResultException
from pageql.reactive_sql import parse_reactive, _replace_placeholders
from pageql.database import (
    connect_database,
    flatten_params,
    parse_param_attrs,
    db_execute_dot,
    evalone,
)

from pageql.params import handle_param
from pageql.http_utils import fetch_sync, fetch
import sqlglot





_ONEVENT_CACHE: dict[tuple[int, int, str, tuple], str] = {}
tasks: list = []

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
    "#test <name>": "define a unit test",
    "#redirect <url>": "issue an HTTP redirect",
    "#error <expr>": "raise an error with the evaluated expression",
    "#render <name>": "render a named partial",
    "#let <name> = <expr>": "assign a variable from an expression",
    "#statuscode <code>": "set the HTTP status code",
    "#respond [code] [body=<expr>]": "return a response with optional status and body",
    "#header <name> <expr>": "add an HTTP response header",
    "#cookie <name> <expr> [opts]": "set an HTTP cookie",
    "#update <table> set <expr> where <cond>": "execute an SQL UPDATE",
    "#fetch [async] <var> from <url> [header=<expr>]": "fetch a remote URL into a variable",
}

def format_unknown_directive(directive: str) -> str:
    """Return a helpful error message for unknown directives."""
    lines = [f"Unknown directive '{directive}'. Valid directives:<pre>"]
    for name, desc in DIRECTIVE_HELP.items():
        lines.append(f"  {name:8} - {desc}")
    return "\n".join(lines) + "</pre>"







class PageQL:
    """
    Manages and renders PageQL templates against a database.

    Attributes:
        db_path: Path to the SQLite database file or a database URL.
        _modules: Internal storage for loaded module source strings or parsed nodes.
        dialect: SQL dialect used by the connected database.
    """

    def __init__(self, db_path):
        """
        Initializes the PageQL engine instance.

        Args:
            db_path: Path to the SQLite database file or database URL.
        """
        self._modules = {} # Store parsed node lists here later
        self._parse_errors = {} # Store errors here
        self.tests = {}
        sqlite_file = None
        if not (
            db_path.startswith("postgres://")
            or db_path.startswith("postgresql://")
            or db_path.startswith("mysql://")
        ):
            sqlite_file = db_path
            if sqlite_file.startswith("sqlite://"):
                sqlite_file = sqlite_file.split("://", 1)[1]
        new_db = False
        if sqlite_file is not None:
            new_db = sqlite_file == ":memory:" or not os.path.exists(sqlite_file)
        self.db, self.dialect = connect_database(db_path)
        if isinstance(self.db, sqlite3.Connection) and new_db:
            # Configure SQLite for web server usage
            with self.db:
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.execute("PRAGMA synchronous=NORMAL")
                self.db.execute("PRAGMA temp_store=MEMORY")
                self.db.execute("PRAGMA cache_size=10000")
        self.tables = Tables(self.db, self.dialect)
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
        if name in self.tests:
            del self.tests[name]
        # Tokenize the source and build AST
        try:
            tokens = tokenize(source)
            tests = {}
            body, partials = build_ast(tokens, self.dialect, tests)
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
            if tests:
                self.tests[name] = tests
        except Exception as e:
            print(f"Error parsing module {name}: {e}")
            self._parse_errors[name] = e
        

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

    # ------------------------------------------------------------------
    # Individual node processing helpers
    # ------------------------------------------------------------------

    def _process_text_node(self, node_content, params, path, includes,
                            http_verb, reactive, ctx, out):
        out.append(node_content)
        return reactive

    def _process_render_expression_node(self, node_content, params, path,
                                         includes, http_verb, reactive, ctx,
                                         out):
        result = evalone(self.db, node_content, params, reactive, self.tables)
        if isinstance(result, ReadOnly):
            signal = None
            result = result.value
        elif isinstance(result, Signal):
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
            mid = ctx.marker_id()
            ctx.append_script(f"pstart({mid})")
            out.append(value)
            ctx.append_script(f"pend({mid})")

            def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                ctx.append_script(
                    f"pset({mid},{json.dumps(html.escape(str(sig.value)))})",
                )

            ctx.add_listener(signal, listener)
        else:
            out.append(value)
        return reactive

    def _process_render_param_node(self, node_content, params, path, includes,
                                   http_verb, reactive, ctx, out):
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
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})")
                    out.append(value)
                    ctx.append_script(f"pend({mid})")
                    if signal:

                        def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                            ctx.append_script(
                                f"pset({mid},{json.dumps(html.escape(str(sig.value)))})",
                            )

                        ctx.add_listener(signal, listener)
                else:
                    out.append(value)
        except KeyError:
            raise ValueError(f"Parameter `{node_content}` not found in params `{params}`")
        return reactive

    def _process_render_raw_node(self, node_content, params, path, includes,
                                 http_verb, reactive, ctx, out):
        result = evalone(self.db, node_content, params, reactive, self.tables)
        if isinstance(result, ReadOnly):
            signal = None
            result = result.value
        elif isinstance(result, Signal):
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
            mid = ctx.marker_id()
            ctx.append_script(f"pstart({mid})")
            out.append(value)
            ctx.append_script(f"pend({mid})")

            def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                ctx.append_script(
                    f"pset({mid},{json.dumps(str(sig.value))})",
                )

            ctx.add_listener(signal, listener)
        else:
            out.append(value)
        return reactive

    def _process_param_directive(self, node_content, params, path, includes,
                                 http_verb, reactive, ctx, out):
        param_name, param_value = handle_param(node_content, params)
        params[param_name] = param_value
        return reactive

    def _process_let_directive(self, node_content, params, path, includes,
                               http_verb, reactive, ctx, out):
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
            ctx.add_dependency(signal)
        else:
            params[var] = evalone(self.db, sql, params, False, self.tables, expr)
        return reactive

    def _process_render_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out):
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
        return reactive

    def _process_reactive_directive(self, node_content, params, path, includes,
                                    http_verb, reactive, ctx, out):
        mode = node_content.strip().lower()
        if mode == 'on':
            reactive = True
        elif mode == 'off':
            reactive = False
        else:
            raise ValueError(f"Unknown reactive mode '{node_content}'")
        params['reactive'] = reactive
        return reactive

    def _process_redirect_directive(self, node_content, params, path, includes,
                                    http_verb, reactive, ctx, out):
        url = evalone(self.db, node_content, params, reactive, self.tables)
        raise RenderResultException(
            RenderResult(
                status_code=302,
                headers=[('Location', url), *ctx.headers],
                cookies=ctx.cookies,
            )
        )

    def _process_error_directive(self, node_content, params, path, includes,
                                 http_verb, reactive, ctx, out):
        msg = evalone(self.db, node_content, params, reactive, self.tables)
        raise ValueError(str(msg))

    def _process_statuscode_directive(self, node_content, params, path, includes,
                                      http_verb, reactive, ctx, out):
        code = evalone(self.db, node_content, params, reactive, self.tables)
        raise RenderResultException(
            RenderResult(
                status_code=code,
                headers=ctx.headers,
                cookies=ctx.cookies,
                body="".join(ctx.out),
            )
        )

    def _process_respond_directive(self, node_content, params, path, includes,
                                   http_verb, reactive, ctx, out):
        status_expr, body_expr = node_content
        code = evalone(self.db, status_expr, params, reactive, self.tables)
        if isinstance(code, Signal):
            code = code.value
        if body_expr is not None:
            body = evalone(self.db, body_expr, params, reactive, self.tables)
            if isinstance(body, Signal):
                body = body.value
            ctx.clear_output()
            ctx.out.append(str(body))
        raise RenderResultException(
            RenderResult(
                status_code=code,
                headers=ctx.headers,
                cookies=ctx.cookies,
                body="".join(ctx.out),
            )
        )

    def _process_header_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out):
        if isinstance(node_content, tuple):
            name, value_expr = node_content
        else:
            name, value_expr = parsefirstword(node_content)
            if value_expr is None:
                raise ValueError("#header requires a name and expression")
        value = evalone(self.db, value_expr, params, reactive, self.tables)
        if isinstance(value, Signal):
            value = value.value
        value = str(value)
        ctx.headers.append((name, value))
        return reactive

    def _process_cookie_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out):
        name, rest = parsefirstword(node_content)
        if rest is None:
            raise ValueError("#cookie requires a name and expression")
        m = re.match(r'("[^\"]*"|\'[^\']*\'|\S+)(?:\s+(.*))?$', rest)
        if not m:
            raise ValueError("Invalid #cookie syntax")
        expr = m.group(1)
        attr_str = m.group(2) or ''
        value = evalone(self.db, expr, params, reactive, self.tables)
        if isinstance(value, Signal):
            value = value.value
        value = str(value)
        attrs = parse_param_attrs(attr_str)
        ctx.cookies.append((name, value, attrs))
        return reactive

    def _process_fetch_directive(self, node_content, params, path, includes,
                                 http_verb, reactive, ctx, out):
        var, expr, is_async, header_expr, method_expr, body_expr = node_content
        if var.startswith(":"):
            var = var[1:]
        var = var.replace(".", "__")
        url = evalone(self.db, expr, params, reactive, self.tables)
        if isinstance(url, Signal):
            url = url.value
        base_url = None
        if isinstance(url, str) and url.startswith("/") and not urlparse(str(url)).scheme:
            base_url = params.get("base_url")
            if not base_url:
                headers_dict = params.get("headers") or {}
                host = None
                if isinstance(headers_dict, dict):
                    host = headers_dict.get("host") or headers_dict.get("Host")
                if not host:
                    host = params.get("headers__host") or params.get("headers__Host")
                path_val = params.get("path")
                if host:
                    scheme = "https" if str(path_val).startswith("https://") else "http"
                    base_url = f"{scheme}://{host}"
                elif path_val and "://" in str(path_val):
                    parsed = urlparse(str(path_val))
                    if parsed.scheme and parsed.netloc:
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
        req_headers = None
        if header_expr is not None:
            req_headers = evalone(self.db, header_expr, params, reactive, self.tables)
            if isinstance(req_headers, Signal):
                req_headers = req_headers.value
            if isinstance(req_headers, dict):
                req_headers = {str(k): str(v) for k, v in req_headers.items()}
            elif isinstance(req_headers, str):
                hdr_lines = req_headers.split("\n")
                hdr_dict = {}
                for line in hdr_lines:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        hdr_dict[k.strip()] = v.strip()
                req_headers = hdr_dict
            else:
                req_headers = {str(req_headers): ""}
        method = "GET"
        if method_expr is not None:
            method = evalone(self.db, method_expr, params, reactive, self.tables)
            if isinstance(method, Signal):
                method = method.value
            if method is None:
                method = "GET"
            else:
                method = str(method).upper()
        req_body = None
        if body_expr is not None:
            req_body = evalone(self.db, body_expr, params, reactive, self.tables)
            if isinstance(req_body, Signal):
                req_body = req_body.value
            if isinstance(req_body, str):
                req_body = req_body.encode()
        # Commit any pending database changes so the fetch callback sees
        # a consistent view of the database before performing the HTTP request
        self.db.commit()
        if is_async:
            body_sig = Signal(None)
            status_sig = Signal(None)
            headers_sig = Signal(None)
            params[f"{var}__body"] = body_sig
            params[f"{var}__status_code"] = status_sig
            params[f"{var}__headers"] = headers_sig

            async def do_fetch(url=url, b=body_sig, s=status_sig, h=headers_sig, headers=req_headers, meth=method, body=req_body, base=base_url):
                data = await fetch(str(url), headers=headers, method=meth, body=body, base_url=base)
                b.set_value(data.get("body"))
                s.set_value(data.get("status_code"))
                h.set_value(data.get("headers"))

            print(f"queued async fetch for {url}")
            tasks.append(do_fetch())
        else:
            data = fetch_sync(str(url), headers=req_headers, method=method, body=req_body, base_url=base_url)
            for k, v in flatten_params(data).items():
                params[f"{var}__{k}"] = v
        return reactive

    def _process_update_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out, node_type):
        try:
            self.tables.executeone(node_type[1:] + " " + node_content, params)
        except sqlite3.Error as e:
            raise ValueError(
                f"Error executing {node_type[1:]} {node_content} with params {params}: {e}"
            )
        return reactive

    def _process_schema_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out, node_type):
        try:
            db_execute_dot(self.db, node_type[1:] + " " + node_content, params)
        except sqlite3.Error as e:
            raise ValueError(
                f"Error executing {node_type[1:]} {node_content} with params {params}: {e}"
            )
        return reactive

    def _process_import_directive(self, node_content, params, path, includes,
                                  http_verb, reactive, ctx, out):
        parts = node_content.split()
        if not parts:
            raise ValueError("Empty import statement")

        module_path = parts[0]
        alias = parts[2] if len(parts) > 2 and parts[1] == 'as' else module_path

        if module_path not in self._modules:
            raise ValueError(
                f"Module '{module_path}' not found, modules: " + str(self._modules.keys())
            )

        includes[alias] = module_path
        return reactive

    def _process_log_directive(self, node_content, params, path, includes,
                               http_verb, reactive, ctx, out):
        print(
            "Logging: " + str(evalone(self.db, node_content, params, reactive, self.tables))
        )
        return reactive

    def _process_dump_directive(self, node_content, params, path, includes,
                                http_verb, reactive, ctx, out):
        cursor = db_execute_dot(self.db, "select * from " + node_content, params)
        t = time.time()
        rows_all = cursor.fetchall()
        end_time = time.time()
        ctx.out.append("<table>")
        for col in cursor.description:
            ctx.out.append("<th>" + col[0] + "</th>")
        ctx.out.append("</tr>")
        for row in rows_all:
            ctx.out.append("<tr>")
            for cell in row:
                ctx.out.append("<td>" + str(cell) + "</td>")
            ctx.out.append("</tr>")
        ctx.out.append("</table>")
        ctx.out.append(f"<p>Dumping {node_content} took {(end_time - t)*1000:.2f} ms</p>")
        return reactive

    def _process_reactiveelement_directive(self, node, params, path, includes,
                                           http_verb, reactive, ctx, out):
        prev = ctx.reactiveelement
        ctx.reactiveelement = []
        buf = []
        self.process_nodes(node[1], params, path, includes, http_verb, reactive, ctx, out=buf)
        signals = ctx.reactiveelement
        ctx.reactiveelement = prev
        out.extend(buf)
        if reactive and ctx and signals:
            mid = ctx.marker_id()
            ctx.append_script(f"pprevioustag({mid})")

            def listener(_=None, *, mid=mid, ctx=ctx):
                new_buf = []
                cur = ctx.reactiveelement
                ctx.reactiveelement = []
                prev = ctx.rendering
                ctx.rendering = True
                self.process_nodes(node[1], params, path, includes, http_verb, True, ctx, out=new_buf)
                ctx.rendering = prev
                from .pageqlapp import run_tasks
                run_tasks()
                ctx.reactiveelement = cur
                html_content = "".join(new_buf).strip()
                tag = ''
                if html_content.startswith('<'):
                    m = re.match(r'<([A-Za-z0-9_-]+)', html_content)
                    if m:
                        tag = m.group(1)
                void_elements = {
                    'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'
                }
                if (
                    tag
                    and tag.lower() not in void_elements
                    and not re.search(r'/\s*>$', html_content)
                    and not html_content.endswith(f'</{tag}>')
                ):
                    html_content += f"</{tag}>"
                ctx.append_script(
                    f"pupdatetag({mid},{json.dumps(html_content)})"
                )

            for sig in signals:
                ctx.add_listener(sig, listener)
        return reactive

    def _process_if_directive(self, node, params, path, includes,
                              http_verb, reactive, ctx, out):
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
            signals = [
                v for v in cond_vals
                if isinstance(v, Signal) and not isinstance(v, ReadOnly)
            ]

            def pick_index():
                for idx, val in enumerate(cond_vals):
                    cur = val.value if isinstance(val, Signal) else val
                    if cur:
                        return idx
                return None

            if ctx.reactiveelement is not None:
                idx = pick_index()
                if idx is not None:
                    reactive = self.process_nodes(bodies[idx], params, path, includes, http_verb, True, ctx, out)
                ctx.reactiveelement.extend(signals)
            else:
                idx = pick_index()
                if not signals:
                    if idx is not None:
                        reactive = self.process_nodes(bodies[idx], params, path, includes, http_verb, reactive, ctx, out)
                else:
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})")

                    if idx is not None:
                        reactive = self.process_nodes(bodies[idx], params, path, includes, http_verb, reactive, ctx, out)

                    ctx.append_script(f"pend({mid})")

                    def listener(_=None, *, mid=mid, ctx=ctx):
                        new_idx = pick_index()
                        buf = []
                        if new_idx is not None:
                            prev = ctx.rendering
                            ctx.rendering = True
                            self.process_nodes(bodies[new_idx], params, path, includes, http_verb, True, ctx, out=buf)
                            ctx.rendering = prev
                        from .pageqlapp import run_tasks
                        run_tasks()
                        html_content = "".join(buf).strip()
                        ctx.append_script(f"pset({mid},{json.dumps(html_content)})")

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
                reactive = self.process_nodes(node[i], params, path, includes, http_verb, reactive, ctx, out)
                i += 1
        return reactive

    def _process_ifdef_directive(self, node, params, path, includes,
                                 http_verb, reactive, ctx, out):
        param_name = node[1].strip()
        then_body = node[2]
        else_body = node[3] if len(node) > 3 else None

        if param_name.startswith(':'):
            param_name = param_name[1:]
        param_name = param_name.replace('.', '__')

        body = then_body if param_name in params else else_body
        if body:
            reactive = self.process_nodes(body, params, path, includes, http_verb, reactive, ctx, out)
        return reactive

    def _process_ifndef_directive(self, node, params, path, includes,
                                  http_verb, reactive, ctx, out):
        param_name = node[1].strip()
        then_body = node[2]
        else_body = node[3] if len(node) > 3 else None

        if param_name.startswith(':'):
            param_name = param_name[1:]
        param_name = param_name.replace('.', '__')

        body = then_body if param_name not in params else else_body
        if body:
            reactive = self.process_nodes(body, params, path, includes, http_verb, reactive, ctx, out)
        return reactive

    def _process_from_directive(self, node, params, path, includes,
                                http_verb, reactive, ctx, out):
        query, expr = node[1]
        if len(node) == 4:
            _, _, deps, body = node
        else:
            body = node[2]

        if reactive:
            sql = "SELECT * FROM (" + query + ")"
            sql = re.sub(r':([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)',
                         lambda m: ':' + m.group(1).replace('.', '__'),
                         sql)
            converted_params = {
                k: (v.value if isinstance(v, Signal) else v)
                for k, v in params.items()
            }
            expr_copy = expr.copy()
            _replace_placeholders(expr_copy, converted_params, self.dialect)
            cache_key = expr_copy.sql(dialect=self.dialect)
            cache_allowed = "randomblob" not in cache_key.lower()
            comp = self._from_cache.get(cache_key) if cache_allowed else None
            if comp is None or not comp.listeners:
                comp = parse_reactive(expr, self.tables, params)
                if cache_allowed:
                    self._from_cache[cache_key] = comp
            try:
                cursor = self.db.execute(comp.sql, converted_params)
            except sqlite3.Error as e:
                raise ValueError(
                    f"Error executing SQL `{comp.sql}` with params {converted_params}: {e}"
                )
            col_names = comp.columns if not isinstance(comp.columns, str) else [comp.columns]
        else:
            cursor = db_execute_dot(self.db, "select * from " + query, params)
            col_names = [col[0] for col in cursor.description]

        rows = cursor.fetchall()
        mid = None
        if ctx and reactive:
            mid = ctx.marker_id()
            ctx.append_script(f"pstart({mid})")
        saved_params = params.copy()
        extra_cache_key = ""
        if ctx and reactive:
            dep_set = deps if len(node) == 4 else set()
            extra_params = sorted(d for d in dep_set if d not in col_names)
            if extra_params:
                extra_cache_values = {}
                for k in extra_params:
                    v = saved_params.get(k)
                    if isinstance(v, ReadOnly):
                        v = v.value
                    if isinstance(v, Signal):
                        v = v.value
                    extra_cache_values[k] = v
                extra_cache_key = json.dumps(extra_cache_values, sort_keys=True)
        first = True
        for row in rows:
            row_params = params.copy()
            row_params["__first_row"] = ReadOnly(first)
            first = False
            for i, col_name in enumerate(col_names):
                row_params[col_name] = ReadOnly(row[i])

            row_buffer = []
            self.process_nodes(body, row_params, path, includes, http_verb, reactive, ctx, out=row_buffer)
            row_content = ''.join(row_buffer).strip()
            if ctx and reactive:
                row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(row)).encode()).digest())[:8].decode()}"
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
                           saved_params=saved_params,
                           extra_cache_key=extra_cache_key):
                if ev[0] == 2:
                    row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                    ctx.append_script(f"pdelete('{row_id}')")
                elif ev[0] == 1:
                    row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                    cache_key = (id(comp), 1, extra_cache_key, tuple(ev[1]))
                    row_content = _ONEVENT_CACHE.get(cache_key)
                    if row_content is None:
                        row_params = saved_params.copy()
                        for i, col_name in enumerate(col_names):
                            row_params[col_name] = ReadOnly(ev[1][i])
                        row_buf = []
                        self.process_nodes(body, row_params, path, includes, http_verb, True, ctx, out=row_buf)
                        row_content = ''.join(row_buf).strip()
                        _ONEVENT_CACHE[cache_key] = row_content
                    ctx.append_script(f"pinsert('{row_id}',{json.dumps(row_content)})")
                elif ev[0] == 3:
                    old_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[1])).encode()).digest())[:8].decode()}"
                    new_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(ev[2])).encode()).digest())[:8].decode()}"
                    cache_key = (id(comp), 3, extra_cache_key, tuple(ev[2]))
                    row_content = _ONEVENT_CACHE.get(cache_key)
                    if row_content is None:
                        row_params = saved_params.copy()
                        for i, col_name in enumerate(col_names):
                            row_params[col_name] = ReadOnly(ev[2][i])
                        row_buf = []
                        #print("processing node for update", body)
                        self.process_nodes(body, row_params, path, includes, http_verb, True, ctx, out=row_buf)
                        row_content = ''.join(row_buf).strip()
                        _ONEVENT_CACHE[cache_key] = row_content
                    ctx.append_script(f"pupdate('{old_id}','{new_id}',{json.dumps(row_content)})")

            ctx.add_listener(comp, on_event)

        params.clear()
        params.update(saved_params)
        return reactive

    def _process_each_directive(self, node, params, path, includes,
                                http_verb, reactive, ctx, out):
        param_name = node[1].strip()
        body = node[2]

        if param_name.startswith(':'):
            param_name = param_name[1:]
        param_name = param_name.replace('.', '__')

        count_val = params.get(f"{param_name}__count")
        if isinstance(count_val, ReadOnly):
            count_val = count_val.value
        if isinstance(count_val, Signal):
            count_val = count_val.value
        try:
            count = int(count_val)
        except Exception:
            count = 0

        original = params.get(param_name)
        had_original = param_name in params
        for i in range(count):
            val = params.get(f"{param_name}__{i}")
            if isinstance(val, ReadOnly):
                val = val.value
            if isinstance(val, Signal):
                val = val.value
            params[param_name] = val
            self.process_nodes(body, params, path, includes, http_verb, reactive, ctx, out)
            ctx.out.append('\n')
        if had_original:
            params[param_name] = original
        else:
            params.pop(param_name, None)
        return reactive


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
                return self._process_text_node(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == 'render_expression':
                return self._process_render_expression_node(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == 'render_param':
                return self._process_render_param_node(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == 'render_raw':
                return self._process_render_raw_node(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#param':
                return self._process_param_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#let':
                return self._process_let_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#render':
                return self._process_render_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#reactive':
                return self._process_reactive_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#redirect':
                return self._process_redirect_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#error':
                return self._process_error_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#statuscode':
                return self._process_statuscode_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#respond':
                return self._process_respond_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#header':
                return self._process_header_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#cookie':
                return self._process_cookie_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#fetch':
                return self._process_fetch_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type in ('#update', '#insert', '#delete'):
                return self._process_update_directive(node_content, params, path, includes, http_verb, reactive, ctx, out, node_type)
            elif node_type in ('#create', '#merge'):
                return self._process_schema_directive(node_content, params, path, includes, http_verb, reactive, ctx, out, node_type)
            elif node_type == '#import':
                return self._process_import_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#log':
                return self._process_log_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == '#dump':
                return self._process_dump_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            else:
                if not node_type.startswith('/'):
                    raise ValueError(format_unknown_directive(node_type))
                return reactive
        elif isinstance(node, list):
            directive = node[0]
            if directive == '#reactiveelement':
                return self._process_reactiveelement_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == '#if':
                return self._process_if_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == '#ifdef':
                return self._process_ifdef_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == '#ifndef':
                return self._process_ifndef_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == '#from':
                return self._process_from_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == '#each':
                return self._process_each_directive(node, params, path, includes, http_verb, reactive, ctx, out)
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
        oldout = ctx.out
        if out is not None:
            ctx.out = out

        for node in nodes:
            reactive = self.process_node(node, params, path, includes, http_verb, reactive, ctx, None)
        ctx.out = oldout
        return reactive

    def render(
        self,
        path,
        params={},
        partial=None,
        http_verb=None,
        in_render_directive=False,
        reactive=True,
        ctx=None,
    ):
        """Render a module synchronously."""
        return self._render_impl(
            path,
            params,
            partial,
            http_verb,
            in_render_directive,
            reactive,
            ctx,
        )

    def _render_impl(
        self,
        path,
        params={},
        partial=None,
        http_verb=None,
        in_render_directive=False,
        reactive=True,
        ctx=None,
    ):
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
                if not isinstance(v, Signal):
                    params[k] = ReadOnly(v)
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
                result.headers = ctx.headers
                result.cookies = ctx.cookies

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
        _ONEVENT_CACHE.clear()
        return result

# Example of how to run the examples if this file is executed
if __name__ == '__main__':
    # add current directory to sys.path
    
    # Run doctests, ignoring extra whitespace in output and blank lines
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL)
    
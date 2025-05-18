"""
Python API for the PageQL template engine (Dynamically Typed).

This module provides the PageQL class for programmatically loading, managing,
and rendering PageQL templates, primarily intended for testing purposes.

Classes:
    PageQL: The main engine class.
    RenderResult: Holds the output of a render operation.
"""

# Instructions for LLMs and devs: Keep the code short. Make changes minimal. Don't change even tests too much.

import re, time, sys    
import doctest
import sqlite3
import html
import pathlib

if __package__ is None:                      # script / doctest-by-path
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pageql.parser import tokenize, parsefirstword, build_ast
from pageql.reactive import DerivedSignal, get_dependencies, Tables
from pageql.reactive_sql import parse_reactive

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

# Define RenderResult as a simple class
class RenderResult:
    """Holds the results of a render operation."""
    def __init__(self, status_code=200, headers=[], body=""):
        self.body = body
        self.status_code = status_code
        self.headers = headers # List of (name, value) tuples
        self.redirect_to = None


class RenderContext:
    """Track state for a single render pass."""

    def __init__(self):
        self.next_id = 0
        self.initialized = False

    def ensure_init(self, out):
        if not self.initialized:
            out.append("<script>window.pageqlMarkers={};document.currentScript.remove()</script>")
            self.initialized = True

    def marker_id(self) -> int:
        mid = self.next_id
        self.next_id += 1
        return mid

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
    return db.execute(converted_exp, params)

def evalone(db, exp, params):
    exp = exp.strip()
    if re.match("^:?[a-zA-z._][a-zA-z._0-9]*$", exp):
        if exp[0] == ':':
            exp = exp[1:]
        exp = exp.replace('.', '__')
        if exp in params:
            return params[exp]

    try:
        r = db_execute_dot(db, "select " + exp, params).fetchone()
        return r[0]
    except sqlite3.Error as e:
        raise ValueError(f"Error evaluating SQL expression `select {exp}` with params `{params}`: {e}")


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
        self.tables = Tables(self.db)

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
        tokens = tokenize(source)
        try:
            body, partials = build_ast(tokens)
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

    def handle_render(self, node_content, path, params, includes, http_verb=None, reactive=False):
        """
        Handles the #render directive processing.
        
        Args:
            node_content: The content of the #render node
            path: The current request path
            params: Current parameters dictionary
            includes: Dictionary mapping module aliases to real paths
            http_verb: Optional HTTP verb for accessing verb-specific partials
            
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
                        evaluated_value = evalone(self.db, value_expr, params)
                        render_params[key] = evaluated_value
                    except Exception as e:
                        raise Exception(f"Warning: Error evaluating SQL expression `{value_expr}` for key `{key}` in #render: {e}")
                else:
                    raise Exception(f"Warning: Empty value expression for key `{key}` in #render args")

        # Perform the recursive render call with the potentially modified parameters
        result = self.render(render_path, render_params, partial_names, http_verb, in_render_directive=True, reactive=reactive)
        if result.status_code == 404:
            raise ValueError(f"handle_render: Partial or import '{partial_name_str}' not found with http verb {http_verb}, render_path: {render_path}, partial_names: {partial_names}")
        
        # Clean up the output to match expected format
        return result.body.rstrip()

    def process_node(self, node, params, output_buffer, path, includes, http_verb=None, reactive=False, ctx=None):
        """
        Process a single AST node and append its rendered output to the buffer.
        
        Args:
            node: The AST node to process
            params: Current parameters dictionary
            output_buffer: Output buffer to append rendered content to
            path: Current request path
            includes: Dictionary of imported modules
            http_verb: Optional HTTP verb for accessing verb-specific partials
            
        Returns:
            None (output is appended to output_buffer)
        """
        if isinstance(node, tuple):
            node_type, node_content = node
            
            if node_type == 'text':
                output_buffer.append(node_content)
            elif node_type == 'render_expression':
                output_buffer.append(html.escape(str(evalone(self.db, node_content, params))))
            elif node_type == 'render_param':
                try:
                    output_buffer.append(html.escape(str(params[node_content])))
                except KeyError:
                    raise ValueError(f"Parameter `{node_content}` not found in params `{params}`")
            elif node_type == 'render_raw':
                output_buffer.append(str(evalone(self.db, node_content, params)))
            elif node_type == '#param':
                param_name, param_value = self.handle_param(node_content, params)
                params[param_name] = param_value
            elif node_type == '#set':
                var, args = parsefirstword(node_content)
                if var[0] == ':':
                    var = var[1:]
                var = var.replace('.', '__')
                if reactive:
                    converted = re.sub(r':([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)',
                                       lambda m: ':' + m.group(1).replace('.', '__'),
                                       args)
                    dep_names = get_dependencies(converted)
                    deps = []
                    for name in dep_names:
                        dep = params.get(name)
                        if isinstance(dep, DerivedSignal):
                            deps.append(dep)

                    def compute(args=args, params=params):
                        env = {}
                        for k, v in params.items():
                            if isinstance(v, DerivedSignal):
                                env[k] = v.value
                            else:
                                env[k] = v
                        return evalone(self.db, args, env)

                    existing = params.get(var)
                    if isinstance(existing, DerivedSignal):
                        existing.replace(compute, deps)
                        signal = existing
                    else:
                        signal = DerivedSignal(compute, deps)
                        params[var] = signal
                else:
                    params[var] = evalone(self.db, args, params)
            elif node_type == '#render':
                rendered_content = self.handle_render(node_content, path, params, includes, None, reactive)
                output_buffer.append(rendered_content)
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
                url = evalone(self.db, node_content, params)
                raise RenderResultException(RenderResult(status_code=302, headers=[('Location', url)]))
            elif node_type == '#statuscode':
                code = evalone(self.db, node_content, params)
                raise RenderResultException(RenderResult(status_code=code, body="".join(output_buffer)))
            elif node_type == '#update' or node_type == "#insert" or node_type == "#create" or node_type == "#merge" or node_type == "#delete":
                try:
                    db_execute_dot(self.db, node_type[1:] + " " + node_content, params)
                except sqlite3.Error as e:
                    raise ValueError(f"Error executing {node_type[1:]} {node_content} with params {params}: {e}")
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
                print("Logging: " + str(evalone(self.db, node_content, params)))
            elif node_type == '#dump':
                # fetchall the table and dump it
                cursor = db_execute_dot(self.db, "select * from " + node_content, params)
                t = time.time()
                all = cursor.fetchall()
                end_time = time.time()
                output_buffer.append("<table>")
                for col in cursor.description:
                    output_buffer.append("<th>" + col[0] + "</th>")
                output_buffer.append("</tr>")
                for row in all:
                    output_buffer.append("<tr>")
                    for cell in row:
                        output_buffer.append("<td>" + str(cell) + "</td>")
                    output_buffer.append("</tr>")
                output_buffer.append("</table>")
                output_buffer.append(f"<p>Dumping {node_content} took {(end_time - t)*1000:.2f} ms</p>")
            return reactive
        elif isinstance(node, list):
            directive = node[0]
            if directive == '#if':
                i = 1
                while i < len(node):
                    if i + 1 < len(node):
                        if not evalone(self.db, node[i], params):
                            i += 2
                            continue
                        i += 1
                    reactive = self.process_nodes(node[i], params, output_buffer, path, includes, http_verb, reactive, ctx)
                    i += 1
            elif directive == '#ifdef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name in params:
                    reactive = self.process_nodes(then_body, params, output_buffer, path, includes, http_verb, reactive, ctx)
                elif else_body:
                    reactive = self.process_nodes(else_body, params, output_buffer, path, includes, http_verb, reactive, ctx)
            elif directive == '#ifndef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name not in params:
                    reactive = self.process_nodes(then_body, params, output_buffer, path, includes, http_verb, reactive, ctx)
                elif else_body:
                    reactive = self.process_nodes(else_body, params, output_buffer, path, includes, http_verb, reactive, ctx)
            elif directive == '#from':
                query = node[1]
                body = node[2]

                if reactive:
                    sql = "SELECT * FROM " + query
                    sql = re.sub(r':([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)',
                                 lambda m: ':' + m.group(1).replace('.', '__'),
                                 sql)
                    comp = parse_reactive(sql, self.tables, params)
                    cursor = self.db.execute(comp.sql, params)
                    col_names = comp.columns if not isinstance(comp.columns, str) else [comp.columns]
                else:
                    cursor = db_execute_dot(self.db, "select * from " + query, params)
                    col_names = [col[0] for col in cursor.description]

                rows = cursor.fetchall()
                mid = None
                if ctx and reactive:
                    ctx.ensure_init(output_buffer)
                    mid = ctx.marker_id()
                    output_buffer.append(
                        f"<!--pageql-start:{mid}--><script>(window.pageqlMarkers||(window.pageqlMarkers={{}}))[{mid}]={{s:document.currentScript.previousSibling}};document.currentScript.remove()</script>"
                    )

                saved_params = params.copy()
                for row in rows:
                    row_params = params.copy()
                    for i, col_name in enumerate(col_names):
                        row_params[col_name] = row[i]

                    row_buffer = []
                    self.process_nodes(body, row_params, row_buffer, path, includes, http_verb, reactive, ctx)
                    output_buffer.append(''.join(row_buffer).strip())
                    output_buffer.append('\n')

                params.clear()
                params.update(saved_params)

                if ctx and reactive:
                    output_buffer.append(
                        f"<!--pageql-end:{mid}--><script>window.pageqlMarkers[{mid}].e=document.currentScript.previousSibling;document.currentScript.remove()</script>"
                    )
            return reactive

    def process_nodes(self, nodes, params, output_buffer, path, includes, http_verb=None, reactive=False, ctx=None):
        """
        Process a list of AST nodes and append their rendered output to the buffer.
        
        Args:
            nodes: List of AST nodes to process
            params: Current parameters dictionary
            output_buffer: Output buffer to append rendered content to
            path: Current request path
            includes: Dictionary of imported modules
            http_verb: Optional HTTP verb for accessing verb-specific partials
            
        Returns:
            None (output is appended to output_buffer)
        """
        for node in nodes:
            reactive = self.process_node(node, params, output_buffer, path, includes, http_verb, reactive, ctx)
        return reactive

    def render(self, path, params={}, partial=None, http_verb=None, in_render_directive=False, reactive=False):
        """
        Renders a module using its parsed AST.

        Args:
            path: The request path string (e.g., "/todos").
            params: An optional dictionary.
            partial: Name of partial to render instead of the full template.
            http_verb: Optional HTTP verb for accessing verb-specific partials.

        Returns:
            A RenderResult object.
            
        Example:
            >>> r = PageQL(":memory:")
            >>> r.load_module("include_test", '''This is included
            ... {{#partial p}}
            ...   included partial {{z}}
            ... {{/partial}}
            ... ''')

            >>> source_with_comment = '''
            ... {{#set :ww 3+3}}
            ... Start Text.
            ... {{!-- This is a comment --}}
            ... {{ :hello }}
            ... {{ :ww + 4 }}
            ... {{#partial public add}}
            ... hello {{ :addparam }}
            ... {{/partial}}
            ... {{#if 3+3 == :ww }}
            ... :)
            ... {{#if 3+3 == 7 }}
            ... :(
            ... {{/if}}
            ... {{/if}}
            ... {{#ifdef :hello}}
            ... Hello is defined!
            ... {{#else}}
            ... Nothing is defined!
            ... {{/ifdef}}
            ... {{#ifndef :hello}}
            ... Hello is not defined!
            ... {{#else}}
            ... Hello is defined :)
            ... {{/ifndef}}
            ... {{#ifdef :hello2}}
            ... Hello is defined!
            ... {{#else}}
            ... Hello2 isn't defined!
            ... {{/ifdef}}
            ... {{#ifdef :he.lo}}
            ... He.lo is defined: {{he.lo}}, in expression: {{:he.lo || ':)'}}
            ... {{#else}}
            ... He.lo isn't defined!
            ... {{/ifdef}}
            ... {{#set a.b he.lo}}
            ... {{#ifdef a.b}}
            ... a.b is defined
            ... {{/ifdef}}
            ... {{#create table if not exists todos (id primary key, text text, done boolean) }}
            ... {{#insert into todos (text) values ('hello sql')}}
            ... {{#insert into todos (text) values ('hello second row')}}
            ... {{count(*) from todos}}
            ... {{#from todos}}
            ... {{#from todos}} {{ text }} {{/from}}
            ... {{/from}}
            ... {{#delete from todos}}
            ... {{#from todos}}Bad Dobby{{/from}}
            ... {{#render add addparam='world'}}
            ... {{#if 2<1}}
            ... 2<1
            ... {{#elif 2<2}}
            ... 2<2
            ... {{#elif 2<3}}
            ... 2<3
            ... {{/if}}
            ... {{'&amp;'}}
            ... {{{'&amp;'}}}
            ... {{#import include_test as it}}
            ... {{#render it}}
            ... {{#render it/p z=3}}
            ... End Text.
            ... '''
            >>> r.load_module("comment_test", source_with_comment)
            >>> result1 = r.render("/comment_test", {'hello': 'world', 'he': {'lo': 'wor'}})
            >>> print(result1.status_code)
            200
            >>> print(result1.body.strip())
            Start Text.
            world
            10
            :)
            Hello is defined!
            Hello is defined :)
            Hello2 isn't defined!
            He.lo is defined: wor, in expression: wor:)
            a.b is defined
            2
            hello sql
            hello second row
            hello sql
            hello second row
            hello world
            2<3
            &amp;amp;
            &amp;
            This is included
            included partial 3
            End Text.
            >>> # Simulate GET /nonexistent
            >>> print(r.render("/nonexistent").status_code)
            404
            >>> print(r.render("/comment_test", {'addparam': 'world'}, 'add').body)
            hello world
            >>> print(r.render("/comment_test/add", {'addparam': 'world'}).body)
            hello world
            >>> # Test HTTP verb-specific partials
            >>> r.load_module("verbs", '''
            ... {{#partial public endpoint}}Default handler{{/partial}}
            ... {{#partial get endpoint}}GET handler{{/partial}}
            ... {{#partial post endpoint}}POST handler{{/partial}}
            ... ''')
            >>> print(r.render("/verbs", partial="endpoint").body)
            Default handler
            >>> print(r.render("/verbs", partial="endpoint", http_verb="GET").body)
            GET handler
            >>> print(r.render("/verbs", partial="endpoint", http_verb="POST").body)
            POST handler
            >>> r.load_module("a/b/c", "hello")
            >>> print(r.render("/a/b/c").body)
            hello
            >>> r.load_module("a/b/d", "{{#partial public e}}abde{{/partial}}")
            >>> print(r.render("/a/b/d", partial="e").body)
            abde
            >>> print(r.render("/a/b/d", partial="e", http_verb="GET").body)
            abde
            >>> print(r.render("/a/b/d", partial="e", http_verb="POST").body)
            abde
            >>> print(r.render("/a/b/d/e").body)
            abde
            >>> print(r.render("/a/b/d/e", http_verb="POST").body)
            abde
            >>> r.load_module("a/b/e", "{{#partial public f/g}}abefg{{/partial}}{{#render f/g}}{{#render f/g}}")
            >>> print(r.render("/a/b/e", partial="f/g").body)
            abefg
            >>> print(r.render("/a/b/e").body)
            abefgabefg
            >>> r.load_module("x", "{{#partial public :id/toggle}}toggled {{id}}{{/partial}}")
            >>> print(r.render("/x", partial="5/toggle").body)
            toggled 5
            >>> r.load_module("xx", "{{#partial public :id}}now {{id}}{{/partial}}")
            >>> print(r.render("/xx", partial="5").body)
            now 5
            >>> r.load_module("y", "{{#partial public :a/b/:c}}a is {{a}}, c is {{c}}{{/partial}}{{#render :a/b/:c}}")
            >>> print(r.render("/y", params={'a': 5, 'c': 'cc'}).body)
            a is 5, c is cc
            >>> r.load_module("redirect", "{{#redirect '/redirected'}}")
            >>> print(r.render("/redirect").status_code)
            302
            >>> r.load_module("optional", "{{#param text optional}}cool{{/param}}")
            >>> print(r.render("/optional").body)
            cool
            >>> r.load_module("delete_test", "{{#partial delete :id}}deleted<{{id}}>{{/partial}}")
            >>> print(r.render("/delete_test/1", http_verb="DELETE").body)
            deleted<1>
            >>> r.load_module("varnum", "{{#set idd0 3}}{{idd0}}")
            >>> print(r.render("/varnum").body)
            3
            >>> r.load_module("fromtest", "{{#from (select 1 as id)}}<{{id}}>{{/from}}")
            >>> print(r.render("/fromtest").body)
            <1>
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
                raise ValueError(f"Error parsing module {module_name}: {self._parse_errors[module_name]}")
            if module_name in self._modules:
                output_buffer = []
                includes = {None: module_name}  # Dictionary to track imported modules
                module_body, partials = self._modules[module_name]
                ctx = RenderContext()
                
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
                        reactive = self.process_nodes(body, params, output_buffer, path, includes, http_verb, reactive, ctx)
                    elif (':', None) in partials or (':', 'PUBLIC') in partials or (':', http_verb) in partials:
                        value = partials[(':', http_verb)] if (':', http_verb) in partials else partials[(':', None)] if (':', None) in partials else partials[(':', 'PUBLIC')]
                        if in_render_directive:
                            if value[0] != partial[0]:
                                raise ValueError(f"Partial '{partial}' not found in module, found '{value[0]}'")
                        else:
                            params[value[0][1:]] = partial[0]
                        partials = value[2]
                        partial = partial[1:]
                        reactive = self.process_nodes(value[1], params, output_buffer, path, includes, http_verb, reactive, ctx)
                    else:
                        raise ValueError(f"render: Partial '{partial_name}' with http verb '{http_verb}' not found in module '{module_name}'")
                else:
                    # Render the entire module
                    reactive = self.process_nodes(module_body, params, output_buffer, path, includes, http_verb, reactive, ctx)
                    
                result.body = "".join(output_buffer)
                
                # Process the output to match the expected format in tests
                result.body = result.body.replace('\n\n', '\n')  # Normalize extra newlines
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
    
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
    """
    Parses a simple set of attributes from a string like:
      "status=302 addtoken=true secure"
    Returns them as a dictionary. Tokens without '=' are treated as boolean flags.
    Values can be quoted with single or double quotes to include spaces.
    """
    if not s:
        return {}
    attrs = {}
    # Use regex to handle quoted values
    pattern = r'([^\s=]+)(?:=(?:"([^"]*)"|\'([^\']*)\'|([^\s]*)))?'
    matches = re.findall(pattern, s.strip())
    for match in matches:
        key = match[0].strip()
        # Get the value from whichever group matched (double quote, single quote, or unquoted)
        value = match[1] or match[2] or match[3]
        if value == '':  # If there was an equals sign but empty value
            attrs[key] = ''
        elif '=' in s and key in s and s.find(key) + len(key) < len(s) and s[s.find(key) + len(key)] == '=':
            attrs[key] = value
        else:
            attrs[key] = True
    return attrs

# Define RenderResult as a simple class
class RenderResult:
    """Holds the results of a render operation."""
    def __init__(self, status_code=200, headers=[], body=""):
        self.body = body
        self.status_code = status_code
        self.headers = headers # List of (name, value) tuples
        self.redirect_to = None

def parsefirstword(s):
    s = s.strip()
    if s.find(' ') < 0:
        return s, None
    return s[:s.find(' ')], s[s.find(' '):].strip()

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
    if re.match("^:?[a-zA-z._]+$", exp):
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


def tokenize(source):
    """
    Parses source into ('text', content) and ('comment', content) tuples.
    
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
        if not part: # Skip empty strings that can result from split
            continue
        if part.startswith('{{{') and part.endswith('}}}'):
            part = part[3:-3].strip()
            nodes.append(('render_raw', part))
        elif part.startswith('{{') and part.endswith('}}'):
            part = part[2:-2].strip()
            if part.startswith('!--') and part.endswith('--'):
                pass # Skip comment nodes
            elif part.startswith('#') or part.startswith('/'):
                nodes.append(parsefirstword(part))
            else:
                if re.match("^:?[a-zA-z._]+$", part):
                    if part[0] == ':':
                        part = part[1:]
                    part = part.replace('.', '__')
                    nodes.append(('render_param', part))
                else:
                    nodes.append(('render_expression', part))
        else:
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
                if (split_name[0], None) not in dest_partials:
                    dest_partials[(split_name[0], None)] = [[], {}]
                dest_partials = dest_partials[(split_name[0], None)][1]
                split_name = split_name[1:]
            dest_partials[(split_name[-1], partial_type)] = [part_body, partial_partials]
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
    """
    partials = {}
    body, idx = _read_block(node_list, 0, set(), partials)
    if idx != len(node_list):
        raise SyntaxError("extra tokens after top‑level parse")
    return body, partials

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
        self.db = sqlite3.connect(db_path)

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
        # Tokenize the source and build AST
        tokens = tokenize(source)
        body, partials = build_ast(tokens)
        self._modules[name] = [body, partials]
        
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
        
        is_required = attrs.get('required', not attrs.get('optional', False)) # Default required
        param_value = params.get(param_name) # Get from input params dict

        if param_value is None:
            if 'default' in attrs:
                param_value = attrs['default']
                is_required = False # Default overrides required check if param missing
            elif is_required:
                raise ValueError(f"Required parameter '{param_name}' is missing.")

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

    def handle_render(self, node_content, path, params, includes, http_verb=None):
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
        
        # Check for dot notation (e.g., it.p) - might be a partial within an imported module
        if '.' in partial_name_str and partial_name_str not in includes:
            # Try to load the whole path first, then try removing parts from the end
            current_path = partial_name_str
            partial_parts = []
            
            while '.' in current_path and current_path not in includes:
                # Split at the last dot
                module_part, partial_part = current_path.rsplit('.', 1)
                # Add the partial segment to the beginning of the partial path
                partial_parts.insert(0, partial_part)
                current_path = module_part
            
            # Check if we found a valid module
            if current_path in includes:
                render_path = includes[current_path]  # Use the real module path
                partial_names = partial_parts  # Set the partial names to look for
            else:
                # Not found as an import or as a dot notation of an import
                raise ValueError(f"Import '{partial_name_str}' not found")
        elif partial_name_str in includes:
            # Direct import reference
            render_path = includes[partial_name_str]
        elif partial_name_str and not partial_name_str.startswith('/'):
            # Need to verify the partial exists
            partial_found = False
            selected_partial = None
            selected_module = None
            module_name = includes[None]
            partials = self._modules[module_name][1]
            
            # Search for the partial with the specified HTTP verb first
            for part_key in partials:
                part_name, part_type = part_key
                if part_name == partial_name_str:
                    # Check if the HTTP verb matches or fallback to PUBLIC type
                    if part_type == http_verb or part_type == "PUBLIC" or part_type == None:
                        partial_found = True
                        selected_partial = (part_name, part_type)
                        selected_module = module_name
                        break
            
            if partial_found:
                render_path = selected_module
                partial_names = [selected_partial[0]]  # Set partial name for rendering
            elif partial_name_str not in self._modules:
                raise ValueError(f"Partial or module '{partial_name_str}' not found")
            
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
        result = self.render(render_path, render_params, partial_names, http_verb)
        if result.status_code == 404:
            print(f"handle_render: Partial or import '{partial_name_str}' not found with http verb '{http_verb}'")
            raise ValueError(f"handle_render: Partial or import '{partial_name_str}' not found with http verb '{http_verb}'")
        
        # Clean up the output to match expected format
        return result.body.rstrip()

    def process_node(self, node, params, output_buffer, path, includes, http_verb=None):
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
                params[var] = evalone(self.db, args, params)
            elif node_type == '#render':
                rendered_content = self.handle_render(node_content, path, params, includes, None)  # http_verb may be specified in the #render node
                output_buffer.append(rendered_content)
            elif node_type == '#redirect':
                url = evalone(self.db, node_content, params)
                raise KeyboardInterrupt(RenderResult(status_code=302, headers=[('Location', url)]))
            elif node_type == '#statuscode':
                code = evalone(self.db, node_content, params)
                raise KeyboardInterrupt(RenderResult(status_code=code, body="".join(output_buffer)))
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
                    self.process_nodes(node[i], params, output_buffer, path, includes, http_verb)
                    i += 1
            elif directive == '#ifdef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name in params:
                    self.process_nodes(then_body, params, output_buffer, path, includes, http_verb)
                elif else_body:
                    self.process_nodes(else_body, params, output_buffer, path, includes, http_verb)
            elif directive == '#ifndef':
                param_name = node[1].strip()
                then_body = node[2]
                else_body = node[3] if len(node) > 3 else None
                
                if param_name.startswith(':'):
                    param_name = param_name[1:]
                param_name = param_name.replace('.', '__')
                
                if param_name not in params:
                    self.process_nodes(then_body, params, output_buffer, path, includes, http_verb)
                elif else_body:
                    self.process_nodes(else_body, params, output_buffer, path, includes, http_verb)
            elif directive == '#from':
                query = node[1]
                body = node[2]
                
                cursor = db_execute_dot(self.db, "select * from " + query, params)
                rows = cursor.fetchall()
                if rows:
                    col_names = [col[0] for col in cursor.description]
                    saved_params = params.copy()
                    
                    # Format to match the old output format exactly
                    processed_rows = []
                    for row in rows:
                        # Create a row-specific params set
                        row_params = params.copy()
                        for i, col_name in enumerate(col_names):
                            row_params[col_name] = row[i]
                        
                        row_buffer = []
                        self.process_nodes(body, row_params, row_buffer, path, includes, http_verb)
                        output_buffer.append(' '.join(row_buffer).strip())
                        output_buffer.append('\n')
                    
                    # Restore original params
                    params.clear()
                    params.update(saved_params)

    def process_nodes(self, nodes, params, output_buffer, path, includes, http_verb=None):
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
            self.process_node(node, params, output_buffer, path, includes, http_verb)

    def render(self, path, params={}, partial=None, http_verb=None):
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
            ... {{#render it.p z=3}}
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
            >>> r.load_module("a/b/e", "{{#partial public f/g}}abefg{{/partial}}")
            >>> print(r.render("/a/b/e", partial="f/g").body)
            abefg
        """
        module_name = path.strip('/')
        params = flatten_params(params)
        
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
        while '/' in module_name and module_name not in self._modules:
            module_name, partial_segment = module_name.rsplit('/', 1)
            partial_path.insert(0, partial_segment)
        
           # --- Start Rendering ---
        result = RenderResult()
        result.status_code = 200
        
        if module_name in self._modules:
            output_buffer = []
            includes = {None: module_name}  # Dictionary to track imported modules
            module_body, partials = self._modules[module_name]
            
            try:
                # If we have partial segments and no explicit partial list was provided
                if partial_path and not partial:
                    partial = partial_path
                if partial:
                    # Render the specified partial
                    partial_name = partial[0]
                    remaining_partials = partial[1:] if len(partial) > 1 else None
                    
                    # Look for the partial with matching HTTP verb, falling back to PUBLIC
                    partial_found = False

                    # Try with the specified HTTP verb first
                    if http_verb:
                        # Look for the partial with the specified HTTP verb or PUBLIC
                        http_key = (partial_name, http_verb)
                        http_key_public = (partial_name, "PUBLIC")
                        if http_key in partials or http_key_public in partials:
                            value = partials[http_key][0] if http_key in partials else partials[http_key_public][0]
                            self.process_nodes(value, params, output_buffer, path, includes, http_verb)
                            partial_found = True
                    else:
                        # Try to find any partial with the given name
                        for partial_key in partials:
                            part_name, part_type = partial_key
                            if part_name == partial_name:
                                self.process_nodes(partials[partial_key][0], params, output_buffer, path, includes, http_verb)
                                partial_found = True
                                break
                    
                    if not partial_found:
                        result.status_code = 404
                        print(f"render: Partial '{partial_name}' with http verb '{http_verb}' not found in module '{module_name}', remaining partials: {remaining_partials}, module: {self._modules[module_name]}")
                        result.body = f"render: Partial '{partial_name}' with http verb '{http_verb}' not found in module '{module_name}', remaining partials: {remaining_partials}, module: {self._modules[module_name]}"
                else:
                    # Render the entire module
                    self.process_nodes(module_body, params, output_buffer, path, includes, http_verb)
                    
                result.body = "".join(output_buffer)
                
                # Process the output to match the expected format in tests
                result.body = result.body.replace('\n\n', '\n')  # Normalize extra newlines
                
            except KeyboardInterrupt as e:
                # Used for early return (redirect, status code change)
                return e.args[0]
                
        else:
            result.status_code = 404
            result.body = f"Module {original_module_name} not found"
            
        self.db.commit()
        return result

# Example of how to run the examples if this file is executed
if __name__ == '__main__':
    # Run doctests, ignoring extra whitespace in output and blank lines
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL)
    
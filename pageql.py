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

def evalone(db, exp, params):
    exp = exp.strip()
    if re.match("^:?[a-zA-z]+$", exp):
        if exp[0] == ':':
            exp = exp[1:]
        return params[exp]
    try:
        r = db.execute("select " + exp, params).fetchone()
        return r[0]
    except sqlite3.Error as e:
        raise ValueError(f"Error evaluating SQL expression `select {exp}` with params `{params}`: {e}")

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
        Loads and parses PageQL source code into a simple node list.

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
        """
        # Parse the source and store the list of node tuples
        self._modules[name] = self.parse(source) # Use self.parse

    def parse(self, source):
        """Parses source into ('text', content) and ('comment', content) tuples."""
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
                    if re.match("^:?[a-zA-z]+$", part):
                        if part[0] == ':':
                            part = part[1:]
                        nodes.append(('render_param', part))
                    else:
                        nodes.append(('render_expression', part))
            else:
                nodes.append(('text', part))
        return nodes

    def render(self, path, params={}, partial=[]):
        """
        Simulates a request, executes the parsed node list, and renders content.

        Currently handles text, comments, basic tags, and skips partial definitions.

        Args:
            path: The request path string (e.g., "/todos").
            params: An optional dictionary.

        Returns:
            A RenderResult object.

        Example:
            >>> r = PageQL(":memory:")
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
            ... End Text.
            ... '''
            >>> r.load_module("comment_test", source_with_comment)
            >>> result1 = r.render("/comment_test", {'hello': 'world'})
            >>> print(result1.status_code)
            200
            >>> print(result1.body.strip())
            Start Text.
            world
            10
            :)
            2
            hello sql
            hello second row
            hello sql
            hello second row
            hello world
            2<3
            &amp;amp;
            &amp;
            End Text.
            >>> # Simulate GET /nonexistent
            >>> print(r.render("/nonexistent").status_code)
            404
            >>> print(r.render("/comment_test", {'addparam': 'world'}, ['add']).body)
            hello world
            >>> print(r.render("/comment_test/add", {'addparam': 'world'}).body)
            hello world
        """
        module_name = path.strip('/')

        # --- Execute Node List ---
        result = RenderResult()
        result.status_code = 200
        froms = []
        params_stack = []
        descriptions = []
        ptrs = []
        # Handle module name with dot notation for partial lookups
        original_module_name = module_name
        partial_path = []
        
        # If the module isn't found directly, try to interpret it as a partial path
        while '/' in module_name and module_name not in self._modules:
            # Split at the last dot
            module_name, partial_segment = module_name.rsplit('/', 1)
            # Add the partial segment to the beginning of the partial path
            partial_path.insert(0, partial_segment)
        
        # If we have partial segments and no explicit partial list was provided
        if partial_path and not partial:
            partial = partial_path
        
        # If we still can't find the module, restore the original name for proper error handling
        if module_name not in self._modules:
            module_name = original_module_name
        if module_name in self._modules:
            node_list = self._modules[module_name]
            output_buffer = []
            skip_if = 0
            skip_partial = 0 # New: Counter for skipping partial definitions
            skip_from = 0
            i = 0
            while i < len(node_list):
                node_type, node_content = node_list[i]
                i += 1
                if skip_partial:
                    if node_type == '#partial':
                        skip_partial += 1
                    elif node_type == '/partial':
                        skip_partial -= 1
                    # else: stay in skip_partial mode
                    continue # Skip the current node processing

                if partial:
                    if node_type == '#partial':
                        a, b = parsefirstword(node_content)
                        if a == 'public':
                            node_content = b
                        if partial[0] == node_content:
                            partial = partial[1:]
                        else:
                            skip_partial += 1
                    continue

                if skip_if:
                    if node_type == '#if':
                        skip_if += 1
                    elif node_type == '/if':
                        skip_if -= 1
                    elif node_type == "#elif" and skip_if == 1: # If we are skipping because the previous if/elif was false
                        if evalone(self.db, node_content, params):
                            skip_if = 0 # Start executing this elif block
                        # else: continue skipping (skip_if remains 1)
                    elif node_type == "#else" and skip_if == 1:
                        skip_if = 0 # Start executing the else block
                    # else: stay in skip_if mode (nested ifs, or elif/else after a true if/elif)
                    continue # Skip the current node processing

                if skip_from:
                    if node_type == '#from':
                        skip_from += 1
                    elif node_type == '/from':
                        skip_from -= 1
                    # else: stay in skip_from mode
                    continue # Skip the current node processing
                # --- End Skip logic checks ---


                # --- Main node processing ---
                if node_type == 'text':
                    output_buffer.append(node_content)
                elif node_type == 'comment':
                    pass
                elif node_type == '#partial': # New: Start skipping partial definition
                    skip_partial += 1
                elif node_type == '/partial': # Should not be reached unless nesting is wrong
                     break
                elif node_type == '#param':
                    param_name, attrs_str = parsefirstword(node_content)
                    attrs = {}
                    while attrs_str:
                        attr_name, attr_value_str = parsefirstword(attrs_str)
                        if '=' in attr_name:
                            # Handle case where there's no space after equals
                            attr_parts = attr_name.split('=', 1)
                            attr_name = attr_parts[0]
                            if len(attr_parts) > 1:
                                attr_value = attr_parts[1].strip('"\'')
                                attrs[attr_name] = attr_value
                                attrs_str = attr_value_str
                                continue
                        
                        if attr_value_str and attr_value_str.startswith('='):
                            # Handle equals sign as separate token
                            _, attr_value_with_quotes = parsefirstword(attr_value_str[1:].lstrip())
                            if attr_value_with_quotes:
                                attr_value = attr_value_with_quotes.strip('"\'')
                                attrs[attr_name] = attr_value
                                _, attrs_str = parsefirstword(attr_value_with_quotes)
                        else:
                            # Boolean flag like "required" or "optional"
                            attrs[attr_name] = True
                            attrs_str = attr_value_str

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

                    # Store validated/defaulted value in current scope with ':' prefix
                    params[param_name] = param_value
                elif node_type == '#set':
                    var, args = parsefirstword(node_content)
                    if var[0] == ':':
                        var = var[1:]
                    params[var]=evalone(self.db, args, params)
                elif node_type == '#if':
                    if not evalone(self.db, node_content, params):
                        skip_if += 1
                elif node_type == '#elif': # Encountered elif while NOT skipping (previous if/elif was true)
                    skip_if += 1 # Skip this block and subsequent elif/else blocks
                elif node_type == '#else':
                    skip_if += 1  # Skip the else block because the if or an elif was true
                elif node_type == '/if':
                    pass
                elif node_type == 'render_expression':
                    output_buffer.append(html.escape(str(evalone(self.db, node_content, params))))
                elif node_type == 'render_param':
                    try:
                        output_buffer.append(html.escape(str(params[node_content])))
                    except KeyError:
                        raise ValueError(f"Parameter `{node_content}` not found in params `{params}`")
                elif node_type == '#update' or node_type == "#insert" or node_type == "#create" or node_type == "#merge" or node_type == "#delete":
                    try:
                        self.db.execute(node_type[1:] + " " + node_content, params)
                    except sqlite3.Error as e:
                        raise ValueError(f"Error executing {node_type[1:]} {node_content} with params {params}: {e}")
                elif node_type == '#render':
                    partial_name_str, args_str = parsefirstword(node_content)
                    partial_names = partial_name_str.split('.') if partial_name_str else []
                    render_params = params.copy()

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
                            next_key_match = re.search(r"\s+[a-zA-Z_][a-zA-Z0-9_]*\s*=", args_part[value_start_pos:])
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
                    output_buffer.append(self.render(path, render_params, partial_names).body) # <-- Use the copy
                elif node_type == '#redirect':
                    url = evalone(self.db, node_content, params)
                    return RenderResult(status_code=302, headers=[('Location', url)])
                elif node_type == '#statuscode':
                    result.status_code = evalone(self.db, node_content, params)
                elif node_type == '#from':
                    cursor = self.db.execute("select * from " + node_content, params)
                    all = cursor.fetchall()
                    if len(all) == 0:
                        skip_from = 1
                        continue
                    params_stack.append(params)
                    params = dict(params)
                    froms.append(all)
                    descriptions.append([x[0] for x in cursor.description])
                    for j in range(len(descriptions[-1])):
                        params[descriptions[-1][j]] = froms[-1][0][j]
                    froms[-1] = froms[-1][1:]
                    ptrs.append(i)
                elif node_type == '/from':
                    if len(froms) == 0:
                        raise Exception("Found {{/from}} without {{#from}}")
                    elif len(froms[-1]) > 0:
                        i = ptrs[-1] # Jump back to start of the loop body
                        for j in range(len(descriptions[-1])):
                             params[descriptions[-1][j]] = froms[-1][0][j]
                        froms[-1] = froms[-1][1:] # Consume the row for next check
                    else: # Loop finished
                        params = params_stack.pop()
                        froms.pop()
                        ptrs.pop()
                        descriptions.pop()
                elif node_type == '#dump':
                    # fetchall the table and dump it
                    cursor = self.db.execute("select * from " + node_content, params)
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
                elif node_type == '#log':
                    print("Logging: " + str(evalone(self.db, node_content, params)))
                elif node_type == 'render_raw':
                    output_buffer.append(str(evalone(self.db, node_content, params)))
                else:
                    raise Exception(f"Unknown node type: {node_type}")
                # --- End Main node processing ---

            # Check for unclosed blocks at the end? (Optional)
            if skip_if > 0: print("Warning: Unclosed #if block at end of render")
            if skip_partial > 0: print("Warning: Unclosed #partial block at end of render")
            if skip_from > 0: print("Warning: Unclosed #from block at end of render")


            result.body = "".join(output_buffer)
        else:
             result.status_code = 404
             result.body = "Not Found"
        self.db.commit()
        return result

# Example of how to run the examples if this file is executed
if __name__ == '__main__':
    # Run doctests, ignoring extra whitespace in output and blank lines
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE | doctest.IGNORE_EXCEPTION_DETAIL)
    
PageQL is a template / application language / micro python web framework that allows embedding SQL inside HTML directly.

It was inspired by ColdFusion language that allows embedding SQL and Handlebars / Mustache logic-less templates and also HTMX that simplifies web development

PageQL is **reactive-first**: rendered HTML automatically updates when the underlying database data changes.

Usage: ```pageql <database> templates [--create] [--test]```

Install: pip install pageql  # uvicorn[standard] is installed automatically

## Benchmarking

Basic performance tests can be executed using the standalone script in
`benchmarks/benchmark_pageql.py`.  The script exercises 20 different
rendering features of PageQL using a temporary file based SQLite database.

Run it with the repository's `src` directory on the Python path so that the
`pageql` package can be imported:

```bash
PYTHONPATH=src python benchmarks/benchmark_pageql.py
```

## Core Philosophy

PageQL aims to simplify web development involving relational data by allowing direct embedding of SQL-like queries within HTML templates. It draws inspiration from ColdFusion Markup Language (CFML) but focuses specifically on rendering reactive relational data.

**Key Principles:**

*   **Data-Centric:** The primary goal is displaying and manipulating data from a relational database. It is *not* intended as a full-fledged backend language.
*   **Declarative Focus:** While control structures (`#if`, potentially `#each`) exist, extensive scripting is discouraged to maintain clarity and focus on data presentation.
*   **Leverages SQL:** PageQL relies on the underlying SQL engine for expression evaluation, rather than implementing its own complex expression language.

## Reactive Queries

PageQL renders templates **reactively by default**. HTML output automatically updates whenever the underlying data used by a query (e.g., within a `#from` block) changes in the database.

This capability drives several core design choices:

*   **Declarative Nature:** Using declarative tags like `#from` helps the system understand the data dependencies of a template fragment.
*   **Minimal Scripting (`Logic-less`):** Limiting imperative scripting makes it feasible to analyze template dependencies statically and determine which data changes should trigger UI updates.
*   **Focus on SQL:** Leveraging the database allows integration with notification or change‑tracking mechanisms (e.g., triggers, event systems, logical replication) to power this reactivity.

By keeping templates focused on declaring *what* data is needed rather than *how* to fetch and update it imperatively, PageQL automatically reflects database changes in the rendered HTML with minimal developer effort.

## Design Choices & Simplifications

To maintain focus and simplicity, several design choices have been made:

*   **Simplified Imports/Rendering:** A single `#import` tag for modules and a single `#render` tag for partials/snippets provide a consistent mechanism for code reuse.
*   **Basic Error Handling:** On encountering an error, processing stops, and the error is written to a debug output (details TBD). There is no complex exception handling mechanism.
*   **Database-Driven State:** Communication and state management between requests should primarily occur via the database, not through internal application state or direct communication tags.
*   **External Extensibility:** Extensibility is planned via external APIs, not through mechanisms within the template language itself.

**Features explicitly *out of scope* (currently):**

*   Complex backend logic
*   Direct file management
*   Built-in form generation tags
*   Direct internet protocol tags (HTTP requests, etc.)
*   Advanced application framework features (handled externally)

## Usage (Preliminary)

PageQL is intended to be run via a command-line tool. The basic usage involves pointing the tool at a directory of `.pageql` files and specifying the SQLite database or a database URL to use.

```bash
pageql -path/to/your/database.sqlite ./templates
```

*   `<database>`: (Required) Path to the SQLite database file or a PostgreSQL/MySQL connection URL.
*   `<path>`: (Required) Path to the directory containing the PageQL template files (`.pageql`) to be served.
*   `--port <number>`: (Optional) Port number to run the development server on. Defaults to a standard port (e.g., 8000 or 8080).
*   `-q, --quiet`: (Optional) Only output errors when running the server.
*   `--fallback-url <url>`: (Optional) Forward unknown routes to this base URL.
*   `--no-csrf`: (Optional) Disable CSRF protection. Useful for local testing but not recommended in production.
*   `--test`: (Optional) Run template tests and exit instead of serving.
*   `--http-disconnect-cleanup-timeout <seconds>`: (Optional) Delay before cleaning up HTTP disconnect contexts.
*   `--profile`: (Optional) Profile the server using `cProfile` and print statistics when it stops.
*   PageQL automatically configures new SQLite databases with write-ahead logging
    and an increased cache for better concurrency.
*   When a PostgreSQL or MySQL URL is provided, `--create` is ignored and the
    database must already exist.
*   Although `postgres://` and `mysql://` URLs work, remote connections add read
    latency that can degrade performance of reactive queries.

*(Note: Actual command name and argument flags are subject to change.)*

## Proposed Tag Syntax

**Database/Query:**

* (Note: All database modification tags (`#insert`, `#update`, `#delete`) executed within a single request lifecycle are typically treated as a single atomic transaction. Processing stops on the first error, and prior modifications within the same request are rolled back.)*
*   `#from <table> [WHERE ...] [ORDER BY ...]`: Executes a `SELECT` query against a table (or potentially a view) and iterates over the results. Supports binding parameters (e.g., `:limit`).
*   `#view <name> from <table> [WHERE ...]`: Creates a reusable SQL view definition. Supports binding parameters (e.g., `:halfusers`).
*   `#insert into <table> [(col1, col2, ...)] values (val1, val2, ...)`: Executes an `INSERT` SQL command. The column list is optional if values are provided for all columns in order. Values (`val1`, `val2`, etc.) can be literals or bound parameters (e.g., `:form_field_name`).
*   `#update <table> set col1=val1, col2=val2, ... [WHERE ...]`: Executes an `UPDATE` SQL command. Values (`val1`, `val2`, etc.) can be literals or bound parameters.
*   `#delete from <table> [WHERE ...]`: Executes a `DELETE` SQL command. Supports binding parameters in the `WHERE` clause.

**Partials/Modules:**

*   `#render [GET | POST | PUT | DELETE | PATCH] <partial> [param=value ...]`: Renders a partial (defined locally or imported). When calling a partial that is tied to a specific HTTP verb, that verb must appear directly after `#render`.
*   `#partial [public | GET | POST | PUT | DELETE | PATCH] <name>`: Defines a reusable partial block.
    *   **Public Access:** Using `public` (or specifying `GET`) makes the partial reachable via an HTTP GET request at `/<filename>/<partial_name>` (where `<filename>` is the template file name without the `.pageql` extension). Other verbs restrict access to that specific HTTP method.
    *   **Base File Access:** Requests to the base URL path corresponding to the file (`/<filename>`) render the *top-level content* outside any named `#partial` block.
    *   **Parameters:** For all public/verb-specific accesses, URL query parameters are available via the standard parameter binding mechanism (e.g., `:param_name`).
    *   **Example:** `{{#partial DELETE :id}}...{{/partial}}` can only be requested with an HTTP `DELETE` and must be rendered using `#render DELETE some_module/:id`.
*   `#import <module> [as <alias>]`: Imports modules relative to the template root directory, optionally assigning an alias. Assumes `.pageql` extension (e.g., `#import "components/button"` loads `components/button.pageql`).

**Variable Manipulation:**

*   `#let :<variable> = <expression> [from <table> [WHERE ...]]`: Sets a variable. The value can be a literal (string, integer, float, `NULL`), or the result of a SQL expression, optionally evaluated against a table with a `WHERE` clause.
*   `#param <name> [type=<type>] [optional | required] [default=<simple_expression>] [min=<num>] [max=<num>] [minlength=<num>] [maxlength=<num>] [pattern="<regex>"]`: Declares and optionally validates an expected request parameter (URL query string or POST form variable) named `<name>`.
    *   **Behavior:** Choose `optional` or `required`. **If neither is specified, the default is `required`.**
        *   `required` (or default): Processing stops with an error if the parameter is missing and no `default` is provided.
        *   `optional`: Parameter may be missing. If missing and no `default` is given, `:<name>`  set to `NULL` (instead of being undefined)
    *   `default=<simple_expression>`: Provides a default value if the parameter is missing from the request. If present, this prevents the `required` check from failing.
    *   **Validation:** Optional attributes (`type`, `min`/`max`, `minlength`/`maxlength`, `pattern`) enforce rules on the parameter's value (after applying the default, if applicable). If any validation fails, processing stops with an error.
    *   **Access:** The validated (and potentially defaulted) parameter value is made available as `:<name>`. Direct access via `:<name>` without this tag bypasses validation and defaults.
    *   Dots in `<name>` are converted to `__` when the parameter is looked up, so `#param cookies.session` binds the value of `cookies__session`.

*   `#fetch <var> from <url_expression>`: Fetches an external URL using a callback provided to `PageQL` and exposes the result as `<var>.body`, `<var>.status_code` and `<var>.headers`.

**Flow Control:**

*   `#if <expression>`: Conditional rendering based on an expression.
*   `#else`: Else condition within an `#if` block.
*   `#elif <expression>`: Else-if condition within an `#if` block.
*   `#ifdef <variable>`: Checks if a variable is defined
*   `#ifndef <variable>`: Checks if a variable is not defined
*  [NOT IMPLEMENTED]  `#each collection`: (Potential loop/iteration construct over a collection, likely passed in params. Probably it should introduce :this param like in Handlebars)
*   `#reactive on|off`: Toggle reactive rendering. PageQL starts in reactive mode, automatically wrapping dynamic output so changes can be pushed to the browser. Use `#reactive off` to disable live updates and `#reactive on` to re-enable them.

**Debugging:**
*   `#dump <expression>`: Dumps a table / SQL expression with timing info
*   `#log <message>`: Writes a message to a log.

**Page Processing:**

*   `#statuscode <expression>`: Sets the HTTP response status code.
*   `#redirect <url_expression>`: Performs an HTTP redirect by setting the `Location` header and status code to 302.
*   `#error <expression>`: Raises an error with the evaluated expression.
*   `#header <name> <value_expression>`: Sets an HTTP response header. The `<name>` (e.g., `Cache-Control`, `"X-Custom-Header"`) and `<value_expression>` (e.g., `"no-cache"`, `:some_variable`) are required positional arguments. Example: `#header Cache-Control "no-cache, no-store, must-revalidate"`.
*   `#cookie <name> <expression> [options...]`: Sets an outgoing HTTP cookie. The `<name>` is a literal string and `<expression>` is evaluated to determine the cookie value. Optional attributes like `expires="..."`, `path="..."`, `domain="..."`, `secure`, and `httponly` may follow.
*   [NOT IMPLEMENTED] `#contenttype <expression>`: Sets the `Content-Type` HTTP response header (e.g., `text/html; charset=utf-8`).

When a directive is mistyped or unrecognized, PageQL prints a list of valid directives with short syntax hints. These hints show minimal syntax like `#insert into <table> (cols) values (vals)`, `#update <table> set ... where ...`, or `#delete from <table> where ...`. This quick reference can help diagnose typos during development.

## Reactivity Mode

PageQL operates in reactive mode by default. Templates automatically
update in the browser whenever the underlying variables or SQL queries
change. Use `#reactive off` before a section that should render
statically, and `#reactive on` to re-enable live updates. The mode
persists from the point it is toggled until the opposite directive is
encountered.

## Parameter Binding & Output

PageQL uses a unified namespace for variables originating from different sources:

*   Request parameters declared and validated via `#param`.
*   Variables explicitly set using `#let`.
*   Columns selected within a `#from` loop (each column becomes a variable within the loop's scope).
*   Parameters passed to a partial via `#render <partial> param_name=value`.
*   (Potentially cookie values, details TBD).

The engine distinguishes between binding these variables *into* SQL queries and rendering their values *into* the HTML output.

**1. SQL Parameter Binding (`:param_name`)**

*   **Purpose:** To safely include dynamic values within SQL statements (`WHERE` clauses, `VALUES` lists, `SET` assignments in `#from`, `#insert`, `#update`, `#delete`, `#view`, `#let ... from`).
*   **Syntax:** Use a colon prefix followed by the parameter name (e.g., `:user_id`, `:search_term`, `:text`, `:id`, `:active_count`).
*   **Security:** **This is the ONLY safe way to include dynamic data in SQL queries.** It prevents SQL injection vulnerabilities by ensuring the database driver handles the value correctly, rather than simply concatenating strings. The colon prefix is **mandatory** in these SQL contexts.
*   **`#from` Scope:** Within a `#from` loop, each selected column is directly accessible as a parameter using the colon prefix (e.g., `{{ :column_name }}`).

**2. Output Rendering and Simple Conditions (`{{ }}` and `#if`)**

*   **Purpose:** To display variable values within the HTML template content or use them in simple conditional checks.
*   **Standard Syntax (`{{ :variable }}` or `#if :variable`):** Using the colon prefix is always valid and often preferred for consistency.
*   **Optional Colon Shorthand (`{{ variable }}` or `#if variable`):** The colon prefix (`:`) **can be omitted** *if and only if* the expression consists of a **single variable name**.
    *   Example: `{{ my_var }}` is allowed (equivalent to `{{ :my_var }}`).
    *   Example: `#if my_var` is allowed (equivalent to `#if :my_var`).
    *   This shorthand **cannot** be used for more complex expressions within `{{ }}` or `#if`. For instance, `{{ my_var + 1 }}` or `#if my_var > 0` would require evaluation by the SQL engine and thus necessitate the colon prefix for clarity and proper parsing (e.g., `#if :my_var > 0`). The exact handling of complex expressions within `{{ }}` is still under consideration, but simple variable output is the primary use case.
*   **HTML Escaped Output (`{{ expression }}` or `{{ variable }}`):**
    *   This is the default and recommended way to output data.
    *   It automatically escapes HTML special characters (like `<`, `>`, `&`) to prevent Cross-Site Scripting (XSS) attacks.
    *   **Context-Aware Quoting:** When used inside an HTML attribute value (`<input value={{ :username }}>` or `<input value={{ username }}>`) or within a `<script>` tag for generating JSON-like structures, it *should ideally* automatically wrap string values in appropriate quotes (`<input value="Adam">`). *(Implementation detail)*
*   **Raw/Unescaped Output (`{{{ expression }}}` or `{{{ variable }}}`):**
    *   Outputs the variable's value directly without any HTML escaping. The same optional colon rule applies.
    *   **Use with extreme caution!** Only use this if you are certain the variable contains safe, pre-sanitized HTML or content that should not be escaped. Incorrect use can easily lead to XSS vulnerabilities.

## Expressions

PageQL does not define its own expression language. Instead, it leverages the expression evaluation capabilities of the underlying SQL database engine (e.g., SQLite).

Expressions are primarily used in:

*   **`#if <expression>` / `#elif <expression>`:** To conditionally render blocks of content. The expression should evaluate to a boolean-like value (in SQLite, 0 is false, non-zero is true). If the expression is more complex than a single variable name, it **must** use the colon prefix for variables (e.g., `#if :count > 10`).
*   **`#let :<variable> = <expression> [from ...]`:** To compute a value to assign to a variable. Variables used within the `<expression>` **must** use the colon prefix (e.g., `#let :total_price = :quantity * :unit_price`).
*   **`WHERE <expression>` clauses:** Within database query tags (`#from`, `#update`, `#delete`, `#view`, `#let ... from`) to filter data. Variables **must** use the colon prefix (e.g., `WHERE user_id = :id`).
*   **Value clauses:** In `#insert` (`values (...)`), `#update` (`set col = ...`), `#cookie`, `#header`, `#redirect`. Variables **must** use the colon prefix.

**Allowed Expressions:**

Generally, you can use standard SQL expressions supported by your database, such as:

*   Comparisons (`=`, `!=`, `<`, `>`, `<=`, `>=`, `IS NULL`, `IS NOT NULL`, `LIKE`, `IN`)
*   Logical operators (`AND`, `OR`, `NOT`)
*   Basic arithmetic (`+`, `-`, `*`, `/`)
*   Standard SQL functions (e.g., `LOWER()`, `UPPER()`, `LENGTH()`, `SUBSTR()`, `DATE()`, aggregate functions like `COUNT`, `SUM`, `AVG`, `MAX`, `MIN`)

**Important:** Since expressions are evaluated by the database, their exact syntax and available functions depend on the specific SQL database being used (primarily SQLite in the initial design). Variables within these expressions must be prefixed with `:`.


# Example

```html
{{!-- ============================================= --}}
{{!--          ACTION PARTIALS (CRUD etc.)          --}}
{{!-- ============================================= --}}

{{!-- Add a new Todo --}}
{{#partial POST add}}
  {{#param text required minlength=0}}
  {{#insert into todos (text, completed) values (:text, 0)}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}

{{!-- Delete a Todo --}}
{{#partial POST delete}}
  {{#param id required type=integer min=1}}
  {{#delete from todos WHERE id = :id}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}

{{!-- Toggle a single Todo's completion status --}}
{{#partial POST toggle}}
  {{#param id required type=integer min=1}}
  {{#update todos set completed = 1 - completed WHERE id = :id}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}

{{!-- Save edited Todo text --}}
{{#partial POST save}}
  {{#param id required type=integer min=1}}
  {{#param text required minlength=1}}
  {{#param filter default='all'}} {{!-- Preserve filter for redirect --}}
  {{#update todos set text = :text WHERE id = :id}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}

{{!-- Delete all completed Todos --}}
{{#partial POST clear_completed}}
  {{#param filter default='all'}} {{!-- Preserve filter for redirect --}}
  {{#delete from todos WHERE completed = 1}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}

{{!-- Toggle all Todos' completion status --}}
{{#partial POST toggle_all}}
  {{#param filter default='all'}} {{!-- Preserve filter for redirect --}}
  {{!-- Check if all are currently complete to decide toggle direction --}}
  {{#let :active_count = COUNT(*) from todos WHERE completed = 0}}
  {{#let :new_status = 1}} {{!-- Default to marking all complete --}}
  {{#if :active_count == 0}} {{!-- If none active, mark all incomplete --}}
    {{#let :new_status = 0}}
  {{/if}}
  {{#update todos set completed = :new_status}}
  {{#redirect '/todos?filter=' || :filter}} {{!-- Redirect to base path --}}
{{/partial}}


{{!-- ============================================= --}}
{{!--           MAIN DISPLAY PARTIAL                --}}
{{!-- ============================================= --}}

{{!-- Ensure the 'todos' table exists before proceeding --}}
{{#create table if not exists todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    completed INTEGER DEFAULT 0 CHECK(completed IN (0, 1))
)}}


{{!-- Default view (maps to /todos), displays the list and handles edit state --}}
{{#param filter default='all' pattern="^(all|active|completed)$" optional}}
{{#param edit_id type=integer optional}}


{{!-- Get counts for footer and toggle-all logic --}}
{{#let active_count = COUNT(*) from todos WHERE completed = 0}}
{{#let completed_count = COUNT(*) from todos WHERE completed = 1}}
{{#let total_count  = COUNT(*) from todos}}
{{#let all_complete = (:active_count == 0 AND :total_count > 0)}}

<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PageQL • TodoMVC</title>
<!-- Link to TodoMVC base CSS -->
<link rel="stylesheet" href="base.css">
<link rel="stylesheet" href="index.css">
<!-- Your custom CSS might go here -->

</head>
<body>
<section class="todoapp">
    <header class="header">
    <h1>todos</h1>
    <form method="POST" action="/todos/add">
        <input type="hidden" name="filter" value="{{filter}}">
        <input name="text" class="new-todo" placeholder="What needs to be done?" autofocus>
    </form>
    </header>

    {{!-- This section should be hidden if there are no todos --}}
    {{#if :total_count > 0}}
    <section class="main">
        <form method="POST" action="/todos/toggle_all" id="toggle-all-form" style="display: block;">
            <input type="hidden" name="filter" value="{{filter}}">
            <input id="toggle-all" class="toggle-all" type="checkbox" {{#if all_complete}}checked{{/if}} onchange="document.getElementById('toggle-all-form').submit();">
            <label for="toggle-all">Mark all as complete</label>
        </form>

        <ul class="todo-list">

        {{#from todos WHERE (:filter == 'all') OR (:filter == 'active' AND completed = 0) OR (:filter == 'completed' AND completed == 1) ORDER BY id}}
            {{!-- TODO:  completed isn't part of the sql expression here. There shouldn't be difference between param and column I guess,
                 we need to shallow dup params for all rows for now. New rule: : is optional only for 1 word expressions, in that case sql eval is skipped, just direct --}}
            <li {{#if completed}}class="completed"{{/if}} {{#if :edit_id == :id}}class="editing"{{/if}}>

            {{#if :edit_id == :id}}
                {{!-- Edit State --}}
                <form method="POST" action="/todos/save" style="margin: 0; padding: 0; display: inline;">
                <input type="hidden" name="id" value="{{id}}">
                <input type="hidden" name="filter" value="{{filter}}">
                <input class="edit" name="text" value="{{text}}" autofocus>
                </form>
            {{#else}}
                {{!-- View State --}}
                <div class="view">
                <form method="POST" action="/todos/toggle" style="display: inline;">
                    <input type="hidden" name="id" value="{{id}}">
                    <input type="hidden" name="filter" value="{{filter}}">
                    <input class="toggle" type="checkbox" {{#if completed}}checked{{/if}} onchange="this.form.submit();">
                </form>
                {{!-- Edit link points to base path --}}
                <label ondblclick="window.location.href='/todos?filter={{filter}}&edit_id={{id}}'">{{text}}</label>
                    <form method="POST" action="/todos/delete" style="display: inline;">
                    <input type="hidden" name="id" value="{{id}}">
                    <input type="hidden" name="filter" value="{{filter}}">
                    <button class="destroy"></button>
                </form>
                </div>
            {{/if}}

            </li>
        {{/from}}
        </ul>
    </section>

    {{!-- This footer should be hidden if there are no todos --}}
    <footer class="footer">
        <span class="todo-count"><strong>{{active_count}}</strong> item{{#if :active_count != 1}}s{{/if}} left
         {{#if :total_count > :active_count}}from {{ total_count}}{{/if}}</span>
       
        <ul class="filters">
            {{!-- Filter links point to base path --}}
        <li><a {{#if :filter == 'all'}}class="selected"{{/if}} href="/todos?filter=all">All</a></li>
        <li><a {{#if :filter == 'active'}}class="selected"{{/if}} href="/todos?filter=active">Active</a></li>
        <li><a {{#if :filter == 'completed'}}class="selected"{{/if}} href="/todos?filter=completed">Completed</a></li>
        </ul>
        {{!-- This should be hidden if there are no completed todos --}}
        {{#if :completed_count > 0}}
        <form method="POST" action="/todos/clear_completed" style="display: inline;">
            <input type="hidden" name="filter" value="{{filter}}">
            <button class="clear-completed">Clear completed</button>
        </form>
        {{/if}}
    </footer>
    {{/if}} {{!-- End total_count > 0 --}}

</section>
<footer class="info">
    <p>Double-click to edit a todo</p>
</footer>

</body>
</html>
```

## Integration & Extensibility

PageQL applications can register hooks that run before or after a template is rendered. Use `@app.before('/path')` to modify parameters before rendering.

```python
@app.before('/path')
async def before_handler(params):
    params['title'] = 'Custom Title'
    return params
```

The returned dictionary is merged into the template namespace.

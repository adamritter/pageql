import asyncio
import argparse
import os, time
import sqlite3
import mimetypes
from urllib.parse import urlparse, parse_qs
from watchfiles import awatch
import uuid

# Assuming pageql.py is in the same directory or Python path
from .pageql import PageQL

# Base client script used for reactive updates.
base_script = """
<script src=\"/htmx.min.js\"></script>
<script>
  htmx.config.defaultSwapStyle = 'none';
  window.pageqlMarkers={};
  function pstart(i){var s=document.currentScript,c=document.createComment('pageql-start:'+i);var p=s.parentNode;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);document.body.appendChild(c);}else{s.replaceWith(c);}window.pageqlMarkers[i]=c;if(document.currentScript)document.currentScript.remove();}
  function pend(i){var s=document.currentScript,c=document.createComment('pageql-end:'+i);var p=s.parentNode;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);document.body.appendChild(c);}else{s.replaceWith(c);}if(window.pageqlMarkers[i])window.pageqlMarkers[i].e=c;else{window.pageqlMarkers[i]={e:c};}if(document.currentScript)document.currentScript.remove();}
  function pprevioustag(i){var s=document.currentScript,p=s.parentNode,t=s.previousElementSibling;if(p&&p.tagName==='HEAD'&&document.body){p.removeChild(s);t=null;p=document.body;}else{s.remove();}window.pageqlMarkers[i]=t||p;if(document.currentScript)document.currentScript.remove();}
  function pset(i,v){var s=window.pageqlMarkers[i],e=s.e,r=document.createRange();r.setStartAfter(s);r.setEndBefore(e);r.deleteContents();var t=document.createElement('template');t.innerHTML=v;var c=t.content;e.parentNode.insertBefore(c,e);if(window.htmx){var x=s.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pdelete(i){var m=window.pageqlMarkers[i],e=m.e,r=document.createRange();r.setStartBefore(m);r.setEndAfter(e);r.deleteContents();delete window.pageqlMarkers[i];if(document.currentScript)document.currentScript.remove();}
  function pupdate(o,n,v){var m=window.pageqlMarkers[o],e=m.e;m.textContent='pageql-start:'+n;e.textContent='pageql-end:'+n;delete window.pageqlMarkers[o];window.pageqlMarkers[n]=m;pset(n,v);if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pinsert(i,v){var m=window.pageqlMarkers[i];if(!m){var mid=i.split('_')[0];var c=window.pageqlMarkers[mid];if(!c){return;}m=document.createComment('pageql-start:'+i);var e=document.createComment('pageql-end:'+i);m.e=e;window.pageqlMarkers[i]=m;c.e.parentNode.insertBefore(m,c.e);var t=document.createElement('template');t.innerHTML=v;c.e.parentNode.insertBefore(t.content,c.e);c.e.parentNode.insertBefore(e,c.e);}else{var e=m.e;var t=document.createElement('template');t.innerHTML=v;e.parentNode.insertBefore(t.content,e);}if(window.htmx){var x=m.nextSibling;while(x&&x!==e){var nx=x.nextSibling;if(x.nodeType===1)htmx.process(x);x=nx;}}if(document.currentScript)document.currentScript.remove();}
  function pupdatetag(i,c){var t=window.pageqlMarkers[i];var d=document.createElement('template');d.innerHTML=c;var n=d.content.firstChild;if(!n)return;for(var j=t.attributes.length-1;j>=0;j--){var a=t.attributes[j].name;if(!n.hasAttribute(a))t.removeAttribute(a);}for(var j=0;j<n.attributes.length;j++){var at=n.attributes[j];t.setAttribute(at.name,at.value);}if(document.currentScript)document.currentScript.remove();}
  document.currentScript.remove()
</script>
"""

# Additional script that connects the live-reload websocket.
def reload_ws_script(client_id: str) -> str:
    return f"""
<script>
  (function() {{
    const host = window.location.hostname;
    const port = window.location.port;
    const clientId = "{client_id}";
    function setup() {{
      document.body.addEventListener('htmx:configRequest', (evt) => {{
        evt.detail.headers['ClientId'] = clientId;
      }});
      const ws_url = `ws://${{host}}:${{port}}/reload-request-ws?clientId=${{clientId}}`;

      function forceReload() {{
        const socket = new WebSocket(ws_url);
        socket.onopen = () => {{
          window.location.reload();
        }};
        socket.onerror = () => {{
          setTimeout(forceReload, 100);
        }};
      }}

      const socket = new WebSocket(ws_url);
      socket.onopen = () => {{
        console.log("WebSocket opened with id", clientId);
      }};

      socket.onmessage = (event) => {{
        if (event.data == "reload") {{
          window.location.reload();
        }} else {{
          try {{
            eval(event.data);
          }} catch (e) {{
            console.error("Failed to eval script", event.data, e);
          }}
        }}
      }};

      socket.onclose = () => {{
        setTimeout(forceReload, 100);
      }};

      socket.onerror = () => {{
        setTimeout(forceReload, 100);
      }};
    }}
    if (document.body) {{
      setup();
    }} else {{
      window.addEventListener('DOMContentLoaded', setup);
    }}
    document.currentScript.remove();
  }})();
</script>
"""


class PageQLApp:
    def __init__(self, db_path, template_dir, create_db=False, should_reload=True, reactive=True):
        self.stop_event = None
        self.notifies = []
        self.should_reload = should_reload
        self.reactive_default = reactive
        self.to_reload = []
        self.static_files = {}
        self.static_headers = {}
        self.before_hooks = {}
        self.render_contexts = {}
        self.websockets = {}
        self.template_dir = template_dir
        self.load_builtin_static()
        self.prepare_server(db_path, template_dir, create_db)

    def load_builtin_static(self):
        """Load bundled static assets like htmx."""
        import importlib.resources as resources
        try:
            with resources.files(__package__).joinpath("static/htmx.min.js").open("rb") as f:
                self.static_files["htmx.min.js"] = f.read()
                self.static_headers["htmx.min.js"] = [
                    (b"Cache-Control", b"public, max-age=31536000, immutable")
                ]
        except FileNotFoundError:
            # Optional dependency; ignore if missing
            pass
    
    def before(self, path):
        """
        Decorator for registering a before hook for a specific path.
        
        Example usage:
        @app.before('/path')
        async def before_handler(params):
            params['title'] = 'Custom Title'
            return params
        """
        def decorator(func):
            # Check if the function is async or sync and store it appropriately
            if asyncio.iscoroutinefunction(func):
                self.before_hooks[path] = func
            else:
                # Wrap sync function in an async function
                async def async_wrapper(params):
                    return func(params)
                self.before_hooks[path] = async_wrapper
            return func
        return decorator


    def load(self, template_dir, filename):
        filepath = os.path.join(template_dir, filename)
        if filename.endswith(".pageql"):
            module_name = os.path.splitext(filename)[0]
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    source = f.read()
                    self.pageql_engine.load_module(module_name, source)
                    print(f"  Loaded: {filename} as module '{module_name}'")
            except Exception as e:
                print(f"  Error loading {filename}: {e}")
                # Optionally exit or continue loading others
                # exit(1)
        else:
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                self.static_files[filename] = data
            except IsADirectoryError:
                pass
            except Exception as e:
                print(f"  Error loading {filename}: {e}")
                del self.static_files[filename]
                


    async def pageql_handler(self, scope, receive, send):
        """Handles common logic for GET and POST requests."""
        # print(f"Thread ID: {threading.get_ident()}")
        method = scope['method']

        while self.to_reload:
            f = self.to_reload.pop()
            self.load(self.template_dir, f)

        parsed_path = urlparse(scope['path'])
        path_cleaned = parsed_path.path.strip('/')
        if not path_cleaned:  # Handle root path, maybe map to 'index' or similar?
            path_cleaned = 'index'  # Default to 'index' if root is requested

        # Decode headers and query parameters early so we can obtain the client id
        headers = {k.decode('utf-8').replace('-', '_'): v.decode('utf-8') for k, v in scope['headers']}
        query = scope['query_string']
        query_params = parse_qs(query, keep_blank_values=True)

        params = {}
        for key, value in query_params.items():
            params[key.decode('utf-8')] = value[0].decode('utf-8') if len(value) == 1 else map(lambda v: v.decode('utf-8'), value)

        incoming_client_id = params.pop('clientId', None)
        if incoming_client_id is None:
            incoming_client_id = headers.get('ClientId')
        client_id = incoming_client_id or uuid.uuid4().hex

        params['headers'] = headers
        params['method'] = method

        if path_cleaned in self.static_files:
            content_type, _ = mimetypes.guess_type(path_cleaned)
            print(f"Serving static file: {path_cleaned} as {content_type}")
            if content_type == 'text/html':
                content_type = 'text/html; charset=utf-8'
                scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
                body = scripts.encode('utf-8') + self.static_files[path_cleaned]
            else:
                body = self.static_files[path_cleaned]
            headers_list = [(b'content-type', content_type.encode('utf-8'))]
            headers_list.extend(self.static_headers.get(path_cleaned, []))
            await send({
                'type': 'http.response.start',
                'status': 200,
                'headers': headers_list,
            })
            await send({
                'type': 'http.response.body',
                'body': body,
            })
            return

        # Form data parameters (for POST)
        if method == 'POST':
            print(scope)
            headers = {k.decode('utf-8'): v.decode('utf-8') for k, v in scope['headers']}
            content_length = int(headers.get('content-length', 0))
            if content_length > 0:
                content_type = headers.get('content-type', '')
                # Basic form data parsing
                if 'application/x-www-form-urlencoded' in content_type:
                    message = await receive()
                    post_body = message['body']
                    post_body = post_body.decode('utf-8')
                    post_params = parse_qs(post_body, keep_blank_values=True)
                    print(f"post_params: {post_params}")
                    # Merge/overwrite query params with post params
                    for key, value in post_params.items():
                        params[key] = value[0] if len(value) == 1 else value
                else:
                    # Log or handle unsupported content types if necessary
                    print(f"Warning: Unsupported POST Content-Type: {content_type}")

        try:
            # The render method in pageql.py handles path resolution (e.g., /todos/add)
            t = time.time()
            path = parsed_path.path
            print(f"Rendering {path} as {path_cleaned} with params: {params}")
            if path in self.before_hooks:
                print(f"Before hook for {path}")
                await self.before_hooks[path](params)
            result = self.pageql_engine.render(
                path_cleaned,
                params,
                None,
                method,
                reactive=self.reactive_default,
            )
            if client_id:
                self.render_contexts[client_id] = result.context
                ws = self.websockets.get(client_id)
                if ws:
                    def sender(sc, send=ws):
                        asyncio.create_task(send({"type": "websocket.send", "text": sc}))

                    result.context.send_script = sender
            print(f"{method} {path_cleaned} Params: {params} ({(time.time() - t) * 1000:.2f} ms)")
            print(f"Result: {result.status_code} {result.redirect_to} {result.headers}")

            # --- Handle Redirect ---
            if result.redirect_to:
                await send({
                    'type': 'http.response.start',
                    'status': result.status_code,
                    'headers': [(b'Location', result.redirect_to)],
                })
                # Send other headers added by #header or #cookie? (Currently not implemented in RenderResult)
                await send({
                    'type': 'http.response.body',
                    'body': result.body.encode('utf-8'),
                })
                print(f"Redirecting to: {result.redirect_to} (Status: {result.status_code})")
            # --- Handle Normal Response ---
            else:
                headers = [(b'Content-Type', b'text/html; charset=utf-8')]    
                for name, value in result.headers:
                    headers.append((name.encode('utf-8'), value.encode('utf-8')))
                await send({
                    'type': 'http.response.start',
                    'status': result.status_code,
                    'headers': headers,
                })
                scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
                body_content = scripts + result.body
                low = result.body.lower()
                if '<body' not in low:
                    body_content = '<body>' + body_content + '</body>'
                if '<html' not in low:
                    body_content = '<html>' + body_content + '</html>'
                await send({
                    'type': 'http.response.body',
                    'body': body_content.encode('utf-8'),
                })

        except sqlite3.Error as db_err:
            print(f"ERROR: Database error during render: {db_err}")
            import traceback
            traceback.print_exc()  # Print full traceback for debugging
            await send({
                'type': 'http.response.start',
                'status': 500,
                'headers': [(b'content-type', b'text/html; charset=utf-8')],
            })
            scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
            await send({
                'type': 'http.response.body',
                'body': (scripts + f"Database Error: {db_err}").encode('utf-8'),
            })
        except ValueError as val_err: # Catch validation errors from #param etc.
            print(f"ERROR: Validation or Value error during render: {val_err}")
            await send({
                'type': 'http.response.start',
                'status': 400,
                'headers': [(b'content-type', b'text/html; charset=utf-8')],
            })
            scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
            await send({
                'type': 'http.response.body',
                'body': (scripts + f"Bad Request: {val_err}").encode('utf-8'),
            })
        except FileNotFoundError: # If pageql_engine.render raises this for missing modules
            print(f"ERROR: Module not found for path: {path_cleaned}")
            await send({
                'type': 'http.response.start',
                'status': 404,
                'headers': [(b'content-type', b'text/html; charset=utf-8')],
            })
            scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
            await send({
                'type': 'http.response.body',
                'body': (scripts.encode('utf-8') + b"Not Found"),
            })
        except Exception as e:
            print(f"ERROR: Unexpected error during render: {e}")
            import traceback
            traceback.print_exc() # Print full traceback for debugging
            await send({
                'type': 'http.response.start',
                'status': 500,
                'headers': [(b'content-type', b'text/html; charset=utf-8')],
            })
            scripts = base_script + (reload_ws_script(client_id) if self.should_reload else '')
            await send({
                'type': 'http.response.body',
                'body': (scripts + f"Internal Server Error: {e}").encode('utf-8'),
            })

        return client_id
    
    async def watch_directory(self, directory, stop_event):
        print(f"Watching directory: {directory}")
        async for changes in awatch(directory, stop_event=stop_event, step=10):
            print("Changes:", changes)
            for change in changes:
                path = change[1]
                filename = os.path.relpath(path, self.template_dir)
                print(f"Reloading {filename}")
                self.to_reload.append(filename)
            for n in self.notifies:
                n.set()
            self.notifies.clear()    

    async def lifespan(self, _scope, receive, send):
        while True:
            message = await receive()
            # print(f"lifespan message: {message}")
            self.stop_event = asyncio.Event()

            if message["type"] == "lifespan.startup":
                if self.should_reload:
                    asyncio.create_task(self.watch_directory(self.template_dir, self.stop_event))
                await send({"type": "lifespan.startup.complete"})

            elif message["type"] == "lifespan.shutdown":
                if self.pageql_engine and self.pageql_engine.db:
                    self.pageql_engine.db.close()
                for n in self.notifies:
                    n.set()
                self.stop_event.set()
                await send({"type": "lifespan.shutdown.complete"})
                break
        
    def prepare_server(self, db_path, template_dir, create_db):
        """Loads templates and starts the HTTP server."""
        self.stop_event = asyncio.Event()

        # --- Database File Handling ---
        db_exists = os.path.isfile(db_path)

        if not db_exists:
            if create_db:
                print(f"Database file not found at '{db_path}'. Creating...")
                try:
                    # Connecting creates the file if it doesn't exist
                    conn = sqlite3.connect(db_path)
                    conn.close()
                    print(f"Database file created successfully at '{db_path}'.")
                except sqlite3.Error as e:
                    print(f"Error: Failed to create database file at '{db_path}': {e}")
                    exit(1)
            else:
                print(f"Error: Database file not found at '{db_path}'. Use --create to create it.")
                exit(1)

        if not os.path.isdir(template_dir):
            print(f"Error: Template directory not found at '{template_dir}'")
            exit(1)

        print(f"Loading database from: {db_path}")

        try:
            self.pageql_engine = PageQL(db_path)
            self.conn = self.pageql_engine.db
        except Exception as e:
            print(f"Error initializing PageQL engine: {e}")
            exit(1)

        print(f"Loading templates from: {template_dir}")
        try:
            for root, dirs, files in os.walk(template_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, template_dir)
                    self.load(template_dir, rel_path)
        except OSError as e:
            print(f"Error reading template directory '{template_dir}': {e}")
            exit(1)

        if not self.pageql_engine._modules:
            print("Warning: No .pageql templates found or loaded.")
        
    async def __call__(self, scope, receive, send):
        # print(f"Thread ID: {threading.get_ident()}")
        if scope['type'] == 'lifespan':
            return await self.lifespan(scope, receive, send)
        path = scope.get('path', '/')
        print(f"path: {path}")
        # ws_app.py
        if scope["type"] == "websocket" and scope["path"] == "/reload-request-ws":
            await send({"type": "websocket.accept"})
            client_id = None
            qs = parse_qs(scope.get("query_string", b""))
            if b"clientId" in qs:
                client_id = qs[b"clientId"][0].decode()
                print(f"Client connected with id: {client_id}")
                self.websockets[client_id] = send
                ctx = self.render_contexts.get(client_id)
                if ctx:
                    def sender(sc, send=send):
                        asyncio.create_task(send({"type": "websocket.send", "text": sc}))

                    ctx.send_script = sender
                    scripts = list(ctx.scripts)
                    ctx.scripts.clear()
                    for sc in scripts:
                        await send({"type": "websocket.send", "text": sc})
            fut = asyncio.Event()
            self.notifies.append(fut)
            receive_task = asyncio.create_task(receive())
            while True:
                fut_task = asyncio.create_task(fut.wait())
                done, pending = await asyncio.wait(
                    [receive_task, fut_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    result = await task
                    if isinstance(result, dict) and result.get("type") == "websocket.connect":
                        receive_task = asyncio.create_task(receive())
                    if isinstance(result, dict) and result.get("type") == "websocket.disconnect":
                        if client_id:
                            self.websockets.pop(client_id, None)
                            ctx = self.render_contexts.get(client_id)
                            if ctx:
                                ctx.send_script = None
                                ctx.cleanup()
                        return

                    elif result is True:
                        # fut triggered
                        await send({"type": "websocket.send", "text": "reload"})
                        fut = asyncio.Event()
                        self.notifies.append(fut)
                        fut_task = asyncio.create_task(fut.wait())
        else:
            client_id = await self.pageql_handler(scope, receive, send)
            message = await receive()
            if (
                isinstance(message, dict)
                and message.get("type") == "http.disconnect"
                and client_id
            ):
                async def cleanup_later():
                    await asyncio.sleep(0.1)
                    if client_id not in self.websockets:
                        ctx = self.render_contexts.pop(client_id, None)
                        if ctx:
                            ctx.cleanup()

                asyncio.create_task(cleanup_later())

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed. Please install it with 'pip install uvicorn'.")
        exit(1)

    parser = argparse.ArgumentParser(description="Run the PageQL development server.")
    parser.add_argument('--db', required=True, help="Path to the SQLite database file.")
    parser.add_argument('--dir', required=True, help="Path to the directory containing .pageql template files.")
    parser.add_argument('--port', type=int, default=8000, help="Port number to run the server on.")
    parser.add_argument('--create', action='store_true', help="Create the database file and directory if it doesn't exist.")
    parser.add_argument('--no-reload', action='store_true', help="Do not reload and refresh the templates on file changes.")

    args = parser.parse_args()
    if args.create:
        os.makedirs(args.dir, exist_ok=True)
    app = PageQLApp(args.db, args.dir, create_db=args.create, should_reload=not args.no_reload)

    config = uvicorn.Config(app, host="0.0.0.0", port=args.port)
    server = uvicorn.Server(config)

    print(f"\nPageQL server running on http://localhost:{args.port}")
    print(f"Using database: {args.db}")
    print(f"Serving templates from: {args.dir}")
    print("Press Ctrl+C to stop.")

    asyncio.run(server.serve())
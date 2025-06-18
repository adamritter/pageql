"""Async wrappers for PageQL rendering methods."""

from .pageql import PageQL, _ONEVENT_CACHE, format_unknown_directive, tasks
from .render_context import RenderContext, RenderResult, RenderResultException
from .parser import parsefirstword
from .database import evalone, flatten_params, db_execute_dot
from .http_utils import fetch
from .reactive import Signal, ReadOnly
from .reactive_sql import parse_reactive, _replace_placeholders
import re, json, html, hashlib, base64, sqlite3


class PageQLAsync(PageQL):
    """Async subclass that exposes async render helpers."""

    async def handle_render_async(
        self,
        node_content,
        path,
        params,
        includes,
        http_verb=None,
        reactive=False,
        ctx=None,
    ):
        partial_name_str, args_str = parsefirstword(node_content)
        partial_names = []
        render_params = params.copy()

        if http_verb:
            http_verb = http_verb.upper()

        render_path = path
        current_path = partial_name_str
        partial_parts = []

        while "/" in current_path and current_path not in includes:
            module_part, partial_part = current_path.rsplit("/", 1)
            partial_parts.insert(0, partial_part)
            current_path = module_part

        if current_path in includes:
            render_path = includes[current_path]
            partial_names = partial_parts
        else:
            partial_names = partial_name_str.split("/")

        if args_str:
            current_pos = 0
            while current_pos < len(args_str):
                args_part = args_str[current_pos:].lstrip()
                if not args_part:
                    break
                eq_match = re.search(r"=", args_part)
                if not eq_match:
                    break

                key = args_part[: eq_match.start()].strip()
                if not key or not key.isidentifier():
                    break

                value_start_pos = eq_match.end()
                next_key_match = re.search(r"\s+[a-zA-Z_][a-zA-Z0-9_.]*\s*=", args_part[value_start_pos:])
                value_end_pos = value_start_pos + next_key_match.start() if next_key_match else len(args_part)
                value_expr = args_part[value_start_pos:value_end_pos].strip()
                current_pos += value_end_pos

                if value_expr:
                    try:
                        evaluated_value = evalone(self.db, value_expr, params, reactive, self.tables)
                        if isinstance(evaluated_value, Signal) and ctx:
                            ctx.add_dependency(evaluated_value)
                        render_params[key] = evaluated_value
                    except Exception as e:
                        raise Exception(
                            f"Warning: Error evaluating SQL expression `{value_expr}` for key `{key}` in #render: {e}"
                        )
                else:
                    raise Exception(f"Warning: Empty value expression for key `{key}` in #render args")

        result = await self.render_async(
            render_path,
            render_params,
            partial_names,
            http_verb,
            in_render_directive=True,
            reactive=reactive,
            ctx=ctx,
        )
        if result.status_code == 404:
            raise ValueError(
                f"handle_render: Partial or import '{partial_name_str}' not found with http verb {http_verb}, render_path: {render_path}, partial_names: {partial_names}"
            )

        return result.body.rstrip()

    async def _process_render_expression_node_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
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
            ctx.out.append(value)
            if signal:
                ctx.reactiveelement.append(signal)
        elif reactive and signal is not None:
            mid = ctx.marker_id()
            ctx.append_script(f"pstart({mid})")
            ctx.out.append(value)
            ctx.append_script(f"pend({mid})")

            def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                ctx.append_script(
                    f"pset({mid},{json.dumps(html.escape(str(sig.value)))})"
                )

            ctx.add_listener(signal, listener)
        else:
            ctx.out.append(value)
        return reactive

    async def _process_render_param_node_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        try:
            val = params[node_content]
            if isinstance(val, ReadOnly):
                ctx.out.append(html.escape(str(val.value)))
            else:
                signal = val if isinstance(val, Signal) else None
                if isinstance(val, Signal):
                    val = val.value
                value = html.escape(str(val))
                if ctx.reactiveelement is not None:
                    ctx.out.append(value)
                    if signal:
                        ctx.reactiveelement.append(signal)
                elif reactive:
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})")
                    ctx.out.append(value)
                    ctx.append_script(f"pend({mid})")
                    if signal:

                        def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                            ctx.append_script(
                                f"pset({mid},{json.dumps(html.escape(str(sig.value)))})"
                            )

                        ctx.add_listener(signal, listener)
                else:
                    ctx.out.append(value)
        except KeyError:
            raise ValueError(f"Parameter `{node_content}` not found in params `{params}`")
        return reactive

    async def _process_render_raw_node_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
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
            ctx.out.append(value)
            if signal:
                ctx.reactiveelement.append(signal)
        elif reactive and signal is not None:
            mid = ctx.marker_id()
            ctx.append_script(f"pstart({mid})")
            ctx.out.append(value)
            ctx.append_script(f"pend({mid})")

            def listener(v=None, *, sig=signal, mid=mid, ctx=ctx):
                ctx.append_script(
                    f"pset({mid},{json.dumps(str(sig.value))})"
                )

            ctx.add_listener(signal, listener)
        else:
            ctx.out.append(value)
        return reactive

    async def _process_render_directive_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        rendered_content = await self.handle_render_async(
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

    async def _process_reactiveelement_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        prev = ctx.reactiveelement
        ctx.reactiveelement = []
        buf = []
        await self.process_nodes_async(node[1], params, path, includes, http_verb, reactive, ctx, out=buf)
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
                self.process_nodes(node[1], params, path, includes, http_verb, True, ctx, out=new_buf)
                from .pageqlapp import run_tasks
                run_tasks()
                ctx.reactiveelement = cur
                html_content = "".join(new_buf).strip()
                tag = ""
                if html_content.startswith("<"):
                    m = re.match(r"<([A-Za-z0-9_-]+)", html_content)
                    if m:
                        tag = m.group(1)
                void_elements = {
                    "area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"
                }
                if (
                    tag
                    and tag.lower() not in void_elements
                    and not re.search(r"/\s*>$", html_content)
                    and not html_content.endswith(f"</{tag}>")
                ):
                    html_content += f"</{tag}>"
                ctx.append_script(
                    f"pupdatetag({mid},{json.dumps(html_content)})"
                )

            for sig in signals:
                ctx.add_listener(sig, listener)
        return reactive

    async def _process_if_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
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
                    await self.process_nodes_async(bodies[idx], params, path, includes, http_verb, True, ctx, out)
                ctx.reactiveelement.extend(signals)
            else:
                idx = pick_index()
                if not signals:
                    if idx is not None:
                        await self.process_nodes_async(bodies[idx], params, path, includes, http_verb, reactive, ctx, out)
                else:
                    mid = ctx.marker_id()
                    ctx.append_script(f"pstart({mid})")

                    if idx is not None:
                        await self.process_nodes_async(bodies[idx], params, path, includes, http_verb, reactive, ctx, out)

                    ctx.append_script(f"pend({mid})")

                    def listener(_=None, *, mid=mid, ctx=ctx):
                        new_idx = pick_index()
                        buf = []
                        if new_idx is not None:
                            self.process_nodes(bodies[new_idx], params, path, includes, http_verb, True, ctx, out=buf)
                        from .pageqlapp import run_tasks
                        run_tasks()
                        html_content = "".join(buf).strip()
                        ctx.append_script(
                            f"pset({mid},{json.dumps(html_content)})"
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
                await self.process_nodes_async(node[i], params, path, includes, http_verb, reactive, ctx, out)
                i += 1
        return reactive

    async def _process_ifdef_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        param_name = node[1].strip()
        then_body = node[2]
        else_body = node[3] if len(node) > 3 else None

        if param_name.startswith(":"):
            param_name = param_name[1:]
        param_name = param_name.replace(".", "__")

        body = then_body if param_name in params else else_body
        if body:
            await self.process_nodes_async(body, params, path, includes, http_verb, reactive, ctx, out)
        return reactive

    async def _process_ifndef_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        param_name = node[1].strip()
        then_body = node[2]
        else_body = node[3] if len(node) > 3 else None

        if param_name.startswith(":"):
            param_name = param_name[1:]
        param_name = param_name.replace(".", "__")

        body = then_body if param_name not in params else else_body
        if body:
            await self.process_nodes_async(body, params, path, includes, http_verb, reactive, ctx, out)
        return reactive

    async def _process_from_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        query, expr = node[1]
        if len(node) == 4:
            _, _, deps, body = node
        else:
            body = node[2]

        if reactive:
            sql = "SELECT * FROM (" + query + ")"
            sql = re.sub(r":([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)", lambda m: ":" + m.group(1).replace(".", "__"), sql)
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
            await self.process_nodes_async(body, row_params, path, includes, http_verb, reactive, ctx, out=row_buffer)
            row_content = "".join(row_buffer).strip()
            if ctx and reactive:
                row_id = f"{mid}_{base64.b64encode(hashlib.sha256(repr(tuple(row)).encode()).digest())[:8].decode()}"
                ctx.append_script(f"pstart('{row_id}')")
                ctx.out.append(row_content)
                ctx.append_script(f"pend('{row_id}')")
            else:
                ctx.out.append(row_content)
            ctx.out.append("\n")

        if ctx and reactive:
            ctx.append_script(f"pend({mid})")

            def on_event(ev, *, mid=mid, ctx=ctx, body=body, col_names=col_names, path=path, includes=includes, http_verb=http_verb, saved_params=saved_params, extra_cache_key=extra_cache_key):
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
                        row_content = "".join(row_buf).strip()
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
                        self.process_nodes(body, row_params, path, includes, http_verb, True, ctx, out=row_buf)
                        row_content = "".join(row_buf).strip()
                        _ONEVENT_CACHE[cache_key] = row_content
                    ctx.append_script(f"pupdate('{old_id}','{new_id}',{json.dumps(row_content)})")

            ctx.add_listener(comp, on_event)

        params.clear()
        params.update(saved_params)
        return reactive

    async def _process_each_directive_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        param_name = node[1].strip()
        body = node[2]

        if param_name.startswith(":"):
            param_name = param_name[1:]
        param_name = param_name.replace(".", "__")

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
            await self.process_nodes_async(body, params, path, includes, http_verb, reactive, ctx, out)
            ctx.out.append("\n")
        if had_original:
            params[param_name] = original
        else:
            params.pop(param_name, None)
        return reactive

    async def process_node_async(
        self,
        node,
        params,
        path,
        includes,
        http_verb=None,
        reactive=False,
        ctx=None,
    ):
        if isinstance(node, tuple):
            node_type, node_content = node
            if node_type == "text":
                return self._process_text_node(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "render_expression":
                return await self._process_render_expression_node_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                )
            elif node_type == "render_param":
                return await self._process_render_param_node_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                )
            elif node_type == "render_raw":
                return await self._process_render_raw_node_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                )
            elif node_type == "#param":
                return self._process_param_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#let":
                return self._process_let_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#render":
                return await self._process_render_directive_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                )
            elif node_type == "#reactive":
                return self._process_reactive_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#redirect":
                return self._process_redirect_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#error":
                return self._process_error_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#statuscode":
                return self._process_statuscode_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#header":
                return self._process_header_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#cookie":
                return self._process_cookie_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#fetch":
                return await self._process_fetch_directive_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                )
            elif node_type in ("#update", "#insert", "#delete"):
                return self._process_update_directive(node_content, params, path, includes, http_verb, reactive, ctx, node_type)
            elif node_type in ("#create", "#merge"):
                return self._process_schema_directive(node_content, params, path, includes, http_verb, reactive, ctx, node_type)
            elif node_type == "#import":
                return self._process_import_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#log":
                return self._process_log_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            elif node_type == "#dump":
                return self._process_dump_directive(node_content, params, path, includes, http_verb, reactive, ctx)
            else:
                if not node_type.startswith("/"):
                    raise ValueError(format_unknown_directive(node_type))
                return reactive
        elif isinstance(node, list):
            directive = node[0]
            if directive == "#reactiveelement":
                return await self._process_reactiveelement_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            elif directive == "#if":
                return await self._process_if_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            elif directive == "#ifdef":
                return await self._process_ifdef_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            elif directive == "#ifndef":
                return await self._process_ifndef_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            elif directive == "#from":
                return await self._process_from_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            elif directive == "#each":
                return await self._process_each_directive_async(node, params, path, includes, http_verb, reactive, ctx)
            else:
                if not directive.startswith("/"):
                    raise ValueError(format_unknown_directive(directive))
                return reactive
        return reactive

    async def process_nodes_async(
        self,
        nodes,
        params,
        path,
        includes,
        http_verb=None,
        reactive=False,
        ctx=None,
        out=None,
    ):
        if out is None:
            out = ctx.out

        for node in nodes:
            reactive = await self.process_node_async(node, params, path, includes, http_verb, reactive, ctx)
        return reactive

    async def _process_fetch_directive_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
    ):
        var, expr, is_async, header_expr, method_expr, body_expr = node_content
        if var.startswith(":"):
            var = var[1:]
        var = var.replace(".", "__")
        url = evalone(self.db, expr, params, reactive, self.tables)
        if isinstance(url, Signal):
            url = url.value
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
        self.db.commit()
        if is_async:
            body_sig = Signal(None)
            status_sig = Signal(None)
            headers_sig = Signal(None)
            params[f"{var}__body"] = body_sig
            params[f"{var}__status_code"] = status_sig
            params[f"{var}__headers"] = headers_sig

            async def do_fetch(url=url, b=body_sig, s=status_sig, h=headers_sig, headers=req_headers, meth=method, body=req_body):
                data = await fetch(str(url), headers=headers, method=meth, body=body)
                b.set_value(data.get("body"))
                s.set_value(data.get("status_code"))
                h.set_value(data.get("headers"))

            print(f"queued async fetch for {url}")
            tasks.append(do_fetch())
        else:
            data = await fetch(str(url), headers=req_headers, method=method, body=req_body)
            for k, v in flatten_params(data).items():
                params[f"{var}__{k}"] = v
        return reactive

    async def render_async(
        self,
        path,
        params={},
        partial=None,
        http_verb=None,
        in_render_directive=False,
        reactive=True,
        ctx=None,
    ):
        return await self._render_impl_async(
            path,
            params,
            partial,
            http_verb,
            in_render_directive,
            reactive,
            ctx,
        )

    async def _render_impl_async(
        self,
        path,
        params={},
        partial=None,
        http_verb=None,
        in_render_directive=False,
        reactive=True,
        ctx=None,
    ):
        module_name = path.strip("/")
        params = flatten_params(params)
        if reactive:
            for k, v in list(params.items()):
                if not isinstance(v, Signal):
                    params[k] = ReadOnly(v)
        params["reactive"] = reactive

        partial_path = []
        if partial and isinstance(partial, str):
            partial = partial.split("/")
            partial_path = partial

        if http_verb:
            http_verb = http_verb.upper()

        original_module_name = module_name
        while "/" in module_name and module_name not in self._modules and module_name not in self._parse_errors:
            module_name, partial_segment = module_name.rsplit("/", 1)
            partial_path.insert(0, partial_segment)

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
                includes = {None: module_name}
                module_body, partials = self._modules[module_name]

                if partial_path and not partial:
                    partial = partial_path
                while partial and len(partial) > 1:
                    if (partial[0], None) in partials:
                        partials = partials[(partial[0], None)][1]
                        partial = partial[1:]
                    elif (partial[0], "PUBLIC") in partials:
                        partials = partials[(partial[0], "PUBLIC")][1]
                        partial = partial[1:]
                    elif (":", None) in partials:
                        value = partials[(":", None)]
                        if in_render_directive:
                            if value[0] != partial[0]:
                                raise ValueError(
                                    f"Partial '{partial}' not found in module, found '{value[0]}'"
                                )
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
                        reactive = await self.process_nodes_async(body, params, path, includes, http_verb, reactive, ctx)
                    elif (":", None) in partials or (":", "PUBLIC") in partials or (":", http_verb) in partials:
                        value = (
                            partials[(":", http_verb)]
                            if (":", http_verb) in partials
                            else partials[(":", None)]
                            if (":", None) in partials
                            else partials[(":", "PUBLIC")]
                        )
                        if in_render_directive:
                            if value[0] != partial[0]:
                                raise ValueError(
                                    f"Partial '{partial}' not found in module, found '{value[0]}'"
                                )
                        else:
                            params[value[0][1:]] = partial[0]
                        partials = value[2]
                        partial = partial[1:]
                        reactive = await self.process_nodes_async(value[1], params, path, includes, http_verb, reactive, ctx)
                    else:
                        raise ValueError(
                            f"render: Partial '{partial_name}' with http verb '{http_verb}' not found in module '{module_name}'"
                        )
                else:
                    reactive = await self.process_nodes_async(module_body, params, path, includes, http_verb, reactive, ctx)

                result.body = "".join(ctx.out)
                ctx.clear_output()
                result.context = ctx
                result.headers = ctx.headers
                result.cookies = ctx.cookies

                if not reactive and own_ctx:
                    ctx.cleanup()

                result.body = result.body.replace("\n\n", "\n")
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

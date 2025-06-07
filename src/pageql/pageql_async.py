"""Async wrappers for PageQL rendering methods."""

from .pageql import PageQL, _ONEVENT_CACHE, format_unknown_directive
from .render_context import RenderContext, RenderResult, RenderResultException
from .parser import parsefirstword
from .database import evalone, flatten_params
from .http_utils import fetch
from .reactive import Signal, ReadOnly
import re


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
        out,
    ):
        return self._process_render_expression_node(
            node_content,
            params,
            path,
            includes,
            http_verb,
            reactive,
            ctx,
            out,
        )

    async def _process_render_param_node_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
        out,
    ):
        return self._process_render_param_node(
            node_content,
            params,
            path,
            includes,
            http_verb,
            reactive,
            ctx,
            out,
        )

    async def _process_render_raw_node_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
        out,
    ):
        return self._process_render_raw_node(
            node_content,
            params,
            path,
            includes,
            http_verb,
            reactive,
            ctx,
            out,
        )

    async def _process_render_directive_async(
        self,
        node_content,
        params,
        path,
        includes,
        http_verb,
        reactive,
        ctx,
        out,
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

    async def process_node_async(
        self,
        node,
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

        if isinstance(node, tuple):
            node_type, node_content = node
            if node_type == "text":
                return self._process_text_node(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "render_expression":
                return await self._process_render_expression_node_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                    out,
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
                    out,
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
                    out,
                )
            elif node_type == "#param":
                return self._process_param_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#let":
                return self._process_let_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#render":
                return await self._process_render_directive_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                    out,
                )
            elif node_type == "#reactive":
                return self._process_reactive_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#redirect":
                return self._process_redirect_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#error":
                return self._process_error_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#statuscode":
                return self._process_statuscode_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#header":
                return self._process_header_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#cookie":
                return self._process_cookie_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#fetch":
                return await self._process_fetch_directive_async(
                    node_content,
                    params,
                    path,
                    includes,
                    http_verb,
                    reactive,
                    ctx,
                    out,
                )
            elif node_type in ("#update", "#insert", "#delete"):
                return self._process_update_directive(node_content, params, path, includes, http_verb, reactive, ctx, out, node_type)
            elif node_type in ("#create", "#merge"):
                return self._process_schema_directive(node_content, params, path, includes, http_verb, reactive, ctx, out, node_type)
            elif node_type == "#import":
                return self._process_import_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#log":
                return self._process_log_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            elif node_type == "#dump":
                return self._process_dump_directive(node_content, params, path, includes, http_verb, reactive, ctx, out)
            else:
                if not node_type.startswith("/"):
                    raise ValueError(format_unknown_directive(node_type))
                return reactive
        elif isinstance(node, list):
            directive = node[0]
            if directive == "#reactiveelement":
                return self._process_reactiveelement_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == "#if":
                return self._process_if_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == "#ifdef":
                return self._process_ifdef_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == "#ifndef":
                return self._process_ifndef_directive(node, params, path, includes, http_verb, reactive, ctx, out)
            elif directive == "#from":
                return self._process_from_directive(node, params, path, includes, http_verb, reactive, ctx, out)
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
            reactive = await self.process_node_async(node, params, path, includes, http_verb, reactive, ctx, out)
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
        out,
    ):
        var, expr = node_content
        if var.startswith(":"):
            var = var[1:]
        var = var.replace(".", "__")
        url = evalone(self.db, expr, params, reactive, self.tables)
        if isinstance(url, Signal):
            url = url.value
        self.db.commit()
        data = await fetch(str(url))
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

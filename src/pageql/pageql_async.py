"""Async wrappers for PageQL rendering methods."""

from .pageql import PageQL


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
        return self.handle_render(
            node_content,
            path,
            params,
            includes,
            http_verb,
            reactive,
            ctx,
        )

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
        return self._process_render_directive(
            node_content,
            params,
            path,
            includes,
            http_verb,
            reactive,
            ctx,
            out,
        )

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
        return self.render(
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
        return self._render_impl(
            path,
            params,
            partial,
            http_verb,
            in_render_directive,
            reactive,
            ctx,
        )

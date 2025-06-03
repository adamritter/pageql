"""Utilities for managing render state and results."""


class RenderResult:
    """Holds the results of a render operation."""

    def __init__(self, status_code=200, headers=None, cookies=None, body="", context=None):
        if headers is None:
            headers = []
        if cookies is None:
            cookies = []
        self.body = body
        self.status_code = status_code
        self.headers = headers  # List of (name, value) tuples
        self.cookies = cookies  # List of (name, value, opts) tuples
        self.redirect_to = None
        self.context = context


class RenderContext:
    """Track state for a single render pass."""

    def __init__(self):
        self.next_id = 0
        self.listeners = []
        self.out = []
        self.scripts: list[str] = []
        self.send_script = None
        self.rendering = True
        self.reactiveelement = None
        self.headers: list[tuple[str, str]] = []
        self.cookies: list[tuple[str, str, dict]] = []

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


class RenderResultException(Exception):
    """Exception raised when a render result is returned from a render call."""

    def __init__(self, render_result):
        self.render_result = render_result


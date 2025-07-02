"""Utilities and classes for managing rendering state."""

import json
import re


def escape_script(content: str) -> str:
    """Escape closing ``</script>`` tags in *content* for safe embedding."""
    return re.sub(r"</script>", "<\\/script>", content, flags=re.IGNORECASE)


def embed_html_in_js(content: str) -> str:
    """Return a JSON string of *content* with ``</script>`` escaped."""
    return escape_script(json.dumps(content))

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
        self.infinites: dict[int, object] = {}

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

    def append_script(self, content):
        """Append *content* as a script tag or queue it for later."""

        send_directly = not self.rendering

        if not send_directly:
            self.out.append(f"<script>{content}</script>")
        else:
            if self.send_script is not None:
                self.send_script(content)
            else:
                self.scripts.append(content)


class RenderResultException(Exception):
    """Exception raised when a render result is returned from a render call."""

    def __init__(self, render_result):
        self.render_result = render_result

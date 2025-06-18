import json
from pageql.render_context import embed_html_in_js, escape_script


def test_embed_html_in_js_matches_escape_script_plus_json_dumps():
    s = "<div><script></script></div>"
    assert embed_html_in_js(s) == escape_script(json.dumps(s))

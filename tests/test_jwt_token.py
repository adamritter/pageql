import sys
import types
import json

sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL
from pageql import jws_serialize_compact, jws_deserialize_compact


def test_jwt_round_trip_load_render(tmp_path):
    key_path = tmp_path / "key.pem"
    r = PageQL(":memory:")
    r.db.create_function(
        "jws_serialize_compact",
        1,
        lambda payload: jws_serialize_compact(payload, key_path=str(key_path)),
    )
    r.db.create_function(
        "jws_deserialize_compact",
        1,
        lambda token: jws_deserialize_compact(token, key_path=str(key_path)).decode(),
    )
    src = """
{%let payload json_set('{}', '$.uid', 42)%}
{%let token jws_serialize_compact(:payload)%}
{{ cast(json_extract(jws_deserialize_compact(:token), '$.uid') as integer) }}
"""
    r.load_module("jwt", src)
    result = r.render("/jwt", reactive=False)
    assert result.body.strip() == "42"

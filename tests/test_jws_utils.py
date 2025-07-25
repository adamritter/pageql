import sys
from pathlib import Path
sys.path.insert(0, "src")

from pageql import jws_serialize_compact, jws_deserialize_compact


def test_jws_round_trip(tmp_path):
    key_path = tmp_path / "key.pem"
    token = jws_serialize_compact("hello", key_path=str(key_path))
    assert key_path.exists()
    assert jws_deserialize_compact(token, key_path=str(key_path)) == b"hello"


def test_jws_deserialize_null_returns_none(tmp_path):
    key_path = tmp_path / "key.pem"
    assert jws_deserialize_compact(None, key_path=str(key_path)) is None
    assert not key_path.exists()


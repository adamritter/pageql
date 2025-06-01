import os
import json
from pathlib import Path
from joserfc import jws
from joserfc.jwk import RSAKey

DEFAULT_KEY_PATH = os.path.join(Path.home(), ".pageql_jws_key.pem")
DEFAULT_ALGORITHM = "RS256"


def _load_or_create_key(path: str = DEFAULT_KEY_PATH) -> RSAKey:
    """Load an RSA key from *path* or create one if missing."""
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        key = RSAKey.import_key(data)
    else:
        key = RSAKey.generate_key(auto_kid=True)
        with open(path, "wb") as f:
            f.write(key.as_pem())
    return key


def jws_serialize_compact(payload, protected=None, *, key_path=DEFAULT_KEY_PATH):
    """Return a JWS Compact string for *payload* using ``joserfc``."""
    if protected is None:
        protected = {"alg": DEFAULT_ALGORITHM}
    key = _load_or_create_key(key_path)
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode()
    return jws.serialize_compact(protected, payload, key)


def jws_deserialize_compact(value, *, key_path=DEFAULT_KEY_PATH):
    """Deserialize a JWS Compact string and return the payload."""
    key = _load_or_create_key(key_path)
    obj = jws.deserialize_compact(value, key)
    data = obj.payload
    try:
        return json.loads(data)
    except Exception:
        return data.decode() if isinstance(data, (bytes, bytearray)) else data

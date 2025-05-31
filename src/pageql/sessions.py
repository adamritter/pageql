"""Session helpers using the token table."""
import sqlite3
import time
from typing import Optional

from .tokens import generate_token, hash_token, store_token

__all__ = [
    "create_session",
    "validate_session",
    "extend_session",
    "delete_session",
    "invalidate_user_sessions",
]


def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    expires_in: int,
    *,
    hashed: bool = True,
) -> str:
    """Create a new session returning the session token."""
    token = generate_token()
    expires_at = int(time.time()) + expires_in
    store_token(conn, token, user_id, expires_at, hashed=hashed)
    return token


def validate_session(
    conn: sqlite3.Connection,
    token: str,
    *,
    hashed: bool = True,
) -> Optional[tuple[int, int]]:
    """Return ``(user_id, expires_at)`` if the token is valid and not expired."""
    tval = hash_token(token) if hashed else token
    row = conn.execute(
        "SELECT expires_at, user_id FROM token WHERE token=?",
        (tval,),
    ).fetchone()
    if row is None:
        return None
    expires_at, user_id = row
    if int(time.time()) > expires_at:
        conn.execute("DELETE FROM token WHERE token=?", (tval,))
        conn.commit()
        return None
    return user_id, expires_at


def extend_session(
    conn: sqlite3.Connection,
    token: str,
    expires_in: int,
    *,
    hashed: bool = True,
) -> None:
    """Update ``expires_at`` for ``token`` if it exists."""
    tval = hash_token(token) if hashed else token
    new_exp = int(time.time()) + expires_in
    conn.execute(
        "UPDATE token SET expires_at=? WHERE token=?",
        (new_exp, tval),
    )
    conn.commit()


def delete_session(conn: sqlite3.Connection, token: str, *, hashed: bool = True) -> None:
    """Remove ``token`` from the table."""
    tval = hash_token(token) if hashed else token
    conn.execute("DELETE FROM token WHERE token=?", (tval,))
    conn.commit()


def invalidate_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete all sessions for ``user_id``."""
    conn.execute("DELETE FROM token WHERE user_id=?", (user_id,))
    conn.commit()


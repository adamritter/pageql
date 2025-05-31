import hashlib
import os
import base64
import sqlite3
from typing import Optional, Tuple


def generate_token(nbytes: int = 15) -> str:
    """Return a cryptographically secure base32 token."""
    return base64.b32encode(os.urandom(nbytes)).decode("ascii").lower()


def hash_token(token: str) -> str:
    """Return a hex encoded SHA-256 hash of *token*."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_tokens_table(conn: sqlite3.Connection) -> None:
    """Create the token table if it doesn't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token(
            token TEXT NOT NULL UNIQUE,
            expires_at INTEGER NOT NULL,
            user_id INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def store_token(
    conn: sqlite3.Connection,
    token: str,
    user_id: int,
    expires_at: int,
    *,
    hashed: bool = False,
) -> None:
    """Insert ``token`` into ``token`` table."""
    tval = hash_token(token) if hashed else token
    conn.execute(
        "INSERT INTO token(token, expires_at, user_id) VALUES(?, ?, ?)",
        (tval, expires_at, user_id),
    )
    conn.commit()


def get_and_delete_token(
    conn: sqlite3.Connection, token: str, *, hashed: bool = False
) -> Optional[Tuple[int, int]]:
    """Retrieve ``(expires_at, user_id)`` and delete the row atomically."""
    tval = hash_token(token) if hashed else token
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        row = cur.execute(
            "SELECT expires_at, user_id FROM token WHERE token=?", (tval,)
        ).fetchone()
        if row is not None:
            cur.execute("DELETE FROM token WHERE token=?", (tval,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return row

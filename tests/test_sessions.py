import sqlite3

from pageql.sessions import (
    create_session,
    validate_session,
    extend_session,
    delete_session,
    invalidate_user_sessions,
)
from pageql.tokens import create_tokens_table


def test_session_lifecycle():
    conn = sqlite3.connect(":memory:")
    create_tokens_table(conn)
    token = create_session(conn, 1, 10)
    user_id, exp = validate_session(conn, token)
    assert user_id == 1
    extend_session(conn, token, 20)
    _uid, exp2 = validate_session(conn, token)
    assert exp2 >= exp
    delete_session(conn, token)
    assert validate_session(conn, token) is None


def test_invalidate_user_sessions():
    conn = sqlite3.connect(":memory:")
    create_tokens_table(conn)
    t1 = create_session(conn, 2, 10)
    t2 = create_session(conn, 2, 10)
    invalidate_user_sessions(conn, 2)
    assert validate_session(conn, t1) is None
    assert validate_session(conn, t2) is None

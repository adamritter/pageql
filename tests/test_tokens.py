import sqlite3
from pageql.tokens import (
    generate_token,
    hash_token,
    create_tokens_table,
    store_token,
    get_and_delete_token,
)


def test_store_and_retrieve_token():
    conn = sqlite3.connect(":memory:")
    create_tokens_table(conn)
    tok = generate_token()
    store_token(conn, tok, 1, 123)
    row = get_and_delete_token(conn, tok)
    assert row == (123, 1)
    assert get_and_delete_token(conn, tok) is None


def test_hashed_token_storage():
    conn = sqlite3.connect(":memory:")
    create_tokens_table(conn)
    tok = generate_token()
    store_token(conn, tok, 2, 0, hashed=True)
    stored = conn.execute("select token from token").fetchone()[0]
    assert stored == hash_token(tok)
    row = get_and_delete_token(conn, tok, hashed=True)
    assert row == (0, 2)

# Database utilities extracted from pageql.py

import re
import sqlite3
from urllib.parse import urlparse

from pageql.reactive import (
    Signal,
    DerivedSignal,
    DerivedSignal2,
    derive_signal2,
    OneValue,
    get_dependencies,
    Tables,
    ReadOnly,
    _convert_dot_sql,
)
from pageql.reactive_sql import parse_reactive
import sqlglot


# cache for DerivedSignal2 instances used by evalone
_DV_CACHE: dict[tuple[int, str, tuple], DerivedSignal2] = {}


def connect_database(db_path: str):
    """Return ``(connection, dialect)`` for the given path or URL."""
    if db_path.startswith("postgres://") or db_path.startswith("postgresql://"):
        try:
            import psycopg
            return psycopg.connect(db_path), "postgresql"
        except ImportError:
            try:
                import psycopg2
                return psycopg2.connect(db_path), "postgresql"
            except ImportError:  # pragma: no cover - optional deps
                raise ImportError(
                    "PostgreSQL support requires psycopg or psycopg2 to be installed"
                )
    if db_path.startswith("mysql://"):
        parsed = urlparse(db_path)
        try:
            import mysql.connector
            return (
                mysql.connector.connect(
                    user=parsed.username,
                    password=parsed.password,
                    host=parsed.hostname,
                    port=parsed.port or 3306,
                    database=parsed.path.lstrip("/"),
                ),
                "mysql",
            )
        except ImportError:
            try:
                import pymysql
                return (
                    pymysql.connect(
                        host=parsed.hostname,
                        user=parsed.username,
                        password=parsed.password,
                        database=parsed.path.lstrip("/"),
                        port=parsed.port or 3306,
                    ),
                    "mysql",
                )
            except ImportError:  # pragma: no cover - optional deps
                raise ImportError(
                    "MySQL support requires mysql-connector-python or PyMySQL"
                )
    if db_path.startswith("sqlite://"):
        db_path = db_path.split("://", 1)[1]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        pass
    return conn, "sqlite"


def flatten_params(params):
    """Recursively flatten a nested dictionary using ``__`` separators."""
    result = {}
    for key, value in params.items():
        if isinstance(value, dict):
            flattened = flatten_params(value)
            for k, v in flattened.items():
                result[f"{key}__{k}"] = v
        else:
            result[key] = value
    return result


def parse_param_attrs(s):
    """Parse attributes from a ``#param`` directive string."""
    if not s:
        return {}
    attrs: dict[str, object] = {}
    token_re = re.compile(r"(\w+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|\S+))?")
    for match in token_re.finditer(s):
        key = match.group(1)
        value = match.group(2)
        if value is None:
            attrs[key] = True
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        attrs[key] = value
    return attrs


def db_execute_dot(db, exp, params):
    """Execute SQL replacing dotted parameter names with ``__``."""
    converted_exp = re.sub(
        r":([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)",
        lambda m: ":" + m.group(1).replace(".", "__"),
        exp,
    )
    param_names = [
        m.replace(".", "__")
        for m in re.findall(r":([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*)", exp)
    ]
    missing = [n for n in param_names if n not in params]
    if missing:
        avail = ", ".join(sorted(params.keys()))
        raise ValueError(
            f"Missing parameter(s) {', '.join(m.replace('__', '.') for m in missing)} "
            f"for SQL expression `{exp}`. Available parameters: {avail}"
        )

    converted_params = {}
    for k, v in params.items():
        converted_params[k] = v.value if isinstance(v, Signal) else v
    try:
        return db.execute(converted_exp, converted_params)
    except sqlite3.Error as e:
        raise ValueError(
            f"Error executing SQL `{converted_exp}` with params {converted_params}: {e}"
        )


def evalone(db, exp, params, reactive=False, tables=None, expr=None):
    exp = exp.strip()
    if exp.upper() == "NULL":
        return ReadOnly(None) if reactive else None
    dialect = getattr(tables, "dialect", "sqlite") if tables is not None else "sqlite"
    if re.match("^:?[a-zA-z._][a-zA-z._0-9]*$", exp):
        original = exp[1:] if exp.startswith(":") else exp
        name = original.replace(".", "__")
        if name in params:
            val = params[name]
            if reactive:
                if isinstance(val, ReadOnly):
                    return val
                if isinstance(val, Signal):
                    return val
                signal = DerivedSignal(lambda v=val: v, [])
                params[name] = signal
                return signal
            return val.value if isinstance(val, Signal) else val
        raise ValueError(
            f"Missing parameter '{original}' for expression `{exp}`. "
            f"Available parameters: {', '.join(sorted(params.keys()))}"
        )

    if not re.match(r"(?i)^\s*(select|\(select)", exp):
        exp = "select " + exp

    if reactive:
        sql = _convert_dot_sql(exp)
        if tables is None:
            tables = Tables(db, dialect)
        dep_names = [name.replace(".", "__") for name in get_dependencies(sql)]
        missing = [n for n in dep_names if n not in params]
        if missing:
            avail = ", ".join(sorted(params.keys()))
            raise ValueError(
                f"Missing parameter(s) {', '.join(m.replace('__', '.') for m in missing)} "
                f"for SQL expression `{exp}`. Available parameters: {avail}"
            )
        for name in dep_names:
            val = params.get(name)
            if val is not None and not isinstance(val, Signal):
                params[name] = ReadOnly(val)
        deps = []
        dep_keys = []
        for name in dep_names:
            val = params.get(name)
            if isinstance(val, Signal) and not isinstance(val, ReadOnly):
                deps.append(val)
            dep_keys.append(val.value if isinstance(val, ReadOnly) else id(val))

        def _build():
            nonlocal expr
            if expr is None:
                expr = sqlglot.parse_one(sql, read=dialect)
            comp = parse_reactive(expr, tables, params, one_value=True)
            return comp

        cache_key = (id(tables), sql, tuple(dep_keys))
        cache_allowed = "randomblob" not in sql.lower()
        dv = _DV_CACHE.get(cache_key) if cache_allowed else None
        if dv is not None:
            if not hasattr(dv, "listeners") or dv.listeners:
                return dv
        dv = derive_signal2(_build, deps)
        if cache_allowed:
            _DV_CACHE[cache_key] = dv
        return dv

    try:
        r = db_execute_dot(db, exp, params).fetchone()
        if len(r) != 1:
            raise ValueError(
                f"SQL expression `{exp}` with params `{params}` returned {len(r)} rows, expected 1"
            )
        return r[0]
    except sqlite3.Error as e:
        raise ValueError(
            f"Error evaluating SQL expression `{exp}` with params `{params}`: {e}"
        )


"""SQLite connection layer.

Mirrors orbit's ``db.q`` / ``db.one`` contract so ported modules read the same,
with three changes: ``?`` placeholders, dict rows, and a process-local connection
(SQLite is embedded — no pool).

Concurrency: WAL mode + busy_timeout. One connection per thread via
threading.local; the server layer (Phase 2) keeps writes on a single worker.
"""
from __future__ import annotations

import datetime
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path

from .. import config

SCHEMA_VERSION = 1
_SCHEMA_FILE = Path(__file__).parent / "schema.sql"

_local = threading.local()


# ── ids / time ──────────────────────────────────────────────────────────────

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """26-char Crockford-base32 ULID: 48-bit ms timestamp + 80 random bits."""
    ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    n = (ts << 80) | rand
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[n & 31])
        n >>= 5
    return "".join(reversed(out))


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── connection ──────────────────────────────────────────────────────────────

def _dict_factory(cursor, row):
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Open (or reuse) the thread-local connection and ensure the schema."""
    db_file = Path(path) if path else config.db_path()
    cached = getattr(_local, "conn", None)
    if cached is not None and getattr(_local, "path", None) == str(db_file):
        return cached

    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=30, isolation_level=None)  # autocommit
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    _migrate(conn)
    _local.conn = conn
    _local.path = str(db_file)
    return conn


def close() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
        _local.path = None


def _migrate(conn: sqlite3.Connection) -> None:
    (version,) = conn.execute("PRAGMA user_version").fetchone().values()
    if version >= SCHEMA_VERSION:
        return
    if version == 0:
        conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    # future migrations: elif version == 1: ... etc.


# ── query helpers (orbit contract) ──────────────────────────────────────────

def q(sql: str, params: tuple | list = ()) -> list[dict]:
    """Run a query, return list of dict rows."""
    return connect().execute(sql, tuple(params)).fetchall()


def one(sql: str, params: tuple | list = ()) -> dict | None:
    """Run a query, return the first row or None."""
    rows = connect().execute(sql, tuple(params)).fetchmany(1)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list = ()) -> int:
    """Run a statement, return rowcount."""
    cur = connect().execute(sql, tuple(params))
    return cur.rowcount


def tx():
    """Context manager for an explicit transaction."""
    return _Tx(connect())


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


# ── json column helpers ─────────────────────────────────────────────────────

def dumps(v) -> str:
    return json.dumps(v if v is not None else None, ensure_ascii=False)


def loads(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def load_row(row: dict | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    """Decode *_json columns in place → key without suffix."""
    if row is None:
        return None
    for f in json_fields:
        col = f + "_json"
        if col in row:
            row[f] = loads(row.pop(col), default=[] if f.endswith("s") else {})
    return row

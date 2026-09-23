"""Durable JSON documents. PostgreSQL in Compose, SQLite for local development/tests.

The primary key scopes idempotency and locks. Each bounded worker batch commits state,
pending jobs, metrics and events atomically; a crash rolls back the entire batch.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


class SqliteStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS v2_documents "
                               "(kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, "
                               "PRIMARY KEY (kind,id))")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def read(self, kind, key):
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM v2_documents WHERE kind=? AND id=?",
                                     (kind, key)).fetchone()
            return json.loads(row[0]) if row else None

    def keys(self, kind):
        with self._connection() as connection:
            return [row[0] for row in connection.execute(
                "SELECT id FROM v2_documents WHERE kind=? ORDER BY id", (kind,))]

    @contextmanager
    def transaction(self, kind, key):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM v2_documents WHERE kind=? AND id=?",
                                     (kind, key)).fetchone()
            document = json.loads(row[0]) if row else {}
            yield document
            connection.execute("INSERT INTO v2_documents(kind,id,payload) VALUES(?,?,?) "
                               "ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                               (kind, key, encode(document)))


class PostgresStore:
    def __init__(self, url):
        import psycopg
        self.url, self.connect = url, psycopg.connect
        with self.connect(self.url, connect_timeout=5) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS v2_documents "
                               "(kind TEXT NOT NULL, id TEXT NOT NULL, payload JSONB NOT NULL, "
                               "PRIMARY KEY (kind,id))")

    def read(self, kind, key):
        with self.connect(self.url, connect_timeout=5) as connection:
            row = connection.execute("SELECT payload FROM v2_documents WHERE kind=%s AND id=%s",
                                     (kind, key)).fetchone()
            return row[0] if row else None

    def keys(self, kind):
        with self.connect(self.url, connect_timeout=5) as connection:
            return [row[0] for row in connection.execute(
                "SELECT id FROM v2_documents WHERE kind=%s ORDER BY id", (kind,))]

    @contextmanager
    def transaction(self, kind, key):
        from psycopg.types.json import Jsonb
        with self.connect(self.url, connect_timeout=5) as connection:
            connection.execute("SET LOCAL lock_timeout = '2s'")
            connection.execute("SET LOCAL statement_timeout = '10s'")
            connection.execute("INSERT INTO v2_documents(kind,id,payload) VALUES(%s,%s,'{}') "
                               "ON CONFLICT(kind,id) DO NOTHING", (kind, key))
            document = connection.execute(
                "SELECT payload FROM v2_documents WHERE kind=%s AND id=%s FOR UPDATE", (kind, key)
            ).fetchone()[0]
            yield document
            connection.execute("UPDATE v2_documents SET payload=%s WHERE kind=%s AND id=%s",
                               (Jsonb(document, dumps=encode), kind, key))


def create_store():
    url = os.getenv("AKIM_DATABASE_URL")
    return PostgresStore(url) if url else SqliteStore(os.getenv("AKIM_V2_STORE", "var/v2/state.sqlite3"))

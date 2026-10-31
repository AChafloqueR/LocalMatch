"""Acceso a datos con dos motores:

- Si existe la variable DATABASE_URL  -> PostgreSQL (producción: Supabase, Neon, Render, etc.)
- Si no existe                        -> SQLite local (archivo DB_PATH), ideal para desarrollar.

El resto del código escribe SQL con marcadores `?` y usa `db.insert(...)` para obtener el id nuevo.
"""
import os
import re
import sqlite3
import threading
from contextlib import contextmanager

TABLES = ["sus_responses", "candidates", "vacancies", "users"]


def use_pg() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def schema(pg: bool) -> list[str]:
    pk = "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real = "DOUBLE PRECISION" if pg else "REAL"
    return [
        f"""CREATE TABLE IF NOT EXISTS users(
          id {pk}, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('reclutador','jefe','admin')), pw_hash TEXT NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS vacancies(
          id {pk}, title TEXT NOT NULL, area TEXT NOT NULL, description TEXT NOT NULL,
          must TEXT NOT NULL DEFAULT '', nice TEXT NOT NULL DEFAULT '', min_years {real} NOT NULL DEFAULT 0,
          owner_id INTEGER NOT NULL, boss_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        f"""CREATE TABLE IF NOT EXISTS candidates(
          id {pk}, vacancy_id INTEGER NOT NULL, filename TEXT NOT NULL, redacted_text TEXT NOT NULL,
          profile_json TEXT, score {real}, breakdown_json TEXT, explanation TEXT,
          shortlisted INTEGER NOT NULL DEFAULT 0, decision TEXT, decision_note TEXT, human_note TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        f"""CREATE TABLE IF NOT EXISTS sus_responses(
          id {pk}, user_id INTEGER UNIQUE NOT NULL, profile TEXT NOT NULL, answers TEXT NOT NULL,
          score {real} NOT NULL, experience TEXT, comment TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    ]


def _pg_sql(sql: str) -> str:
    sql = sql.replace("?", "%s")
    if re.match(r"\s*INSERT OR IGNORE", sql, re.I):
        sql = re.sub(r"INSERT OR IGNORE", "INSERT", sql, flags=re.I).rstrip() + " ON CONFLICT DO NOTHING"
    return sql


class DB:
    """Envoltorio mínimo con la misma interfaz para SQLite y PostgreSQL."""

    def __init__(self, conn, pg: bool):
        self.conn, self.pg = conn, pg

    def execute(self, sql, params=()):
        if self.pg:
            return self.conn.execute(_pg_sql(sql), params)
        return self.conn.execute(sql, params)

    def insert(self, sql, params=()) -> int:
        """INSERT que devuelve el id generado."""
        if self.pg:
            return self.conn.execute(_pg_sql(sql) + " RETURNING id", params).fetchone()["id"]
        return self.conn.execute(sql, params).lastrowid


_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            url = os.environ["DATABASE_URL"]
            if "sslmode" not in url and "localhost" not in url and "127.0.0.1" not in url:
                url += ("&" if "?" in url else "?") + "sslmode=require"
            _pool = ConnectionPool(
                url, min_size=1, max_size=int(os.getenv("DB_POOL_MAX", "5")), open=True,
                kwargs={"row_factory": dict_row, "prepare_threshold": None},  # compatible con pgbouncer
            )
        return _pool


@contextmanager
def get_db():
    if use_pg():
        with _get_pool().connection() as conn:  # confirma al salir, revierte si hay error
            yield DB(conn, True)
    else:
        conn = sqlite3.connect(os.getenv("DB_PATH", "localmatch.db"))
        conn.row_factory = sqlite3.Row
        try:
            yield DB(conn, False)
            conn.commit()
        finally:
            conn.close()


def init_db():
    with get_db() as db:
        for stmt in schema(db.pg):
            db.execute(stmt)


def reset_db():
    """Solo para pruebas: vacía todas las tablas."""
    with get_db() as db:
        if db.pg:
            db.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
        else:
            for t in TABLES:
                db.execute(f"DELETE FROM {t}")

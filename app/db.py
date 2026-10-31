import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('reclutador','jefe','admin')),
  pw_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vacancies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  area TEXT NOT NULL,
  description TEXT NOT NULL,
  must TEXT NOT NULL DEFAULT '',
  nice TEXT NOT NULL DEFAULT '',
  min_years REAL NOT NULL DEFAULT 0,
  owner_id INTEGER NOT NULL,
  boss_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id INTEGER NOT NULL,
  filename TEXT NOT NULL,
  redacted_text TEXT NOT NULL,
  profile_json TEXT,
  score REAL,
  breakdown_json TEXT,
  explanation TEXT,
  shortlisted INTEGER NOT NULL DEFAULT 0,
  decision TEXT,
  decision_note TEXT,
  human_note TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sus_responses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER UNIQUE NOT NULL,
  profile TEXT NOT NULL,
  answers TEXT NOT NULL,
  score REAL NOT NULL,
  experience TEXT,
  comment TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def db_path() -> str:
    return os.getenv("DB_PATH", "localmatch.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)

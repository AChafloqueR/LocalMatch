-- ============================================================
-- LocalMatch · Esquema relacional (PostgreSQL / Supabase)
-- Fiel a app/db.py + claves foráneas declaradas para que los
-- visualizadores (Supabase Schema Visualizer, drawsql, etc.)
-- dibujen el diagrama entidad-relación automáticamente.
-- ============================================================

-- Para re-ejecutar desde cero, descomentá esta línea (¡borra todos los datos!):
-- DROP TABLE IF EXISTS sus_responses, candidates, vacancies, users CASCADE;

CREATE TABLE users (
    id       SERIAL PRIMARY KEY,
    email    TEXT UNIQUE NOT NULL,
    name     TEXT NOT NULL,
    role     TEXT NOT NULL CHECK (role IN ('reclutador', 'jefe', 'admin')),
    pw_hash  TEXT NOT NULL
);

CREATE TABLE vacancies (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    area        TEXT NOT NULL,
    description TEXT NOT NULL,
    must        TEXT NOT NULL DEFAULT '',
    nice        TEXT NOT NULL DEFAULT '',
    min_years   DOUBLE PRECISION NOT NULL DEFAULT 0,
    owner_id    INTEGER NOT NULL REFERENCES users(id),   -- reclutador dueño
    boss_id     INTEGER REFERENCES users(id),            -- jefe de área asignado
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE candidates (
    id             SERIAL PRIMARY KEY,
    vacancy_id     INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    redacted_text  TEXT NOT NULL,
    profile_json   TEXT,
    score          DOUBLE PRECISION,
    breakdown_json TEXT,
    explanation    TEXT,
    shortlisted    INTEGER NOT NULL DEFAULT 0 CHECK (shortlisted IN (0, 1)),
    decision       TEXT,
    decision_note  TEXT,
    human_note     TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sus_responses (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER UNIQUE NOT NULL REFERENCES users(id),  -- 1 respuesta por usuario
    profile    TEXT NOT NULL,
    answers    TEXT NOT NULL,
    score      DOUBLE PRECISION NOT NULL,
    experience TEXT,
    comment    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices de búsqueda por clave foránea (Postgres no los crea automáticamente)
CREATE INDEX idx_vacancies_owner    ON vacancies(owner_id);
CREATE INDEX idx_vacancies_boss     ON vacancies(boss_id);
CREATE INDEX idx_candidates_vacancy ON candidates(vacancy_id);

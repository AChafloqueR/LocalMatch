"""Crea usuarios iniciales y, opcionalmente, una vacante de demostración con CV de ejemplo.

Uso:
  python -m scripts.seed            # crea admin, reclutador y jefe con contraseñas aleatorias
  python -m scripts.seed --demo     # además carga una vacante y 6 CV ficticios
"""
import secrets
import sys
from pathlib import Path

from app.auth import hash_password
from app.db import get_db, init_db
from app.parsing import extract_text
from app.skills.redact import redact


def make_user(db, email, name, role, password=None):
    password = password or secrets.token_urlsafe(9)
    db.execute("INSERT OR IGNORE INTO users(email,name,role,pw_hash) VALUES(?,?,?,?)",
               (email, name, role, hash_password(password)))
    return password


def main():
    init_db()
    demo = "--demo" in sys.argv
    with get_db() as db:
        creds = []
        for email, name, role in [
            ("admin@localmatch.local", "Equipo de investigación", "admin"),
            ("reclutadora@localmatch.local", "Rosa Reclutadora", "reclutador"),
            ("jefe@localmatch.local", "Julio Jefe de Área", "jefe"),
        ]:
            if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                continue
            creds.append((email, make_user(db, email, name, role), role))
        if demo:
            owner = db.execute("SELECT id FROM users WHERE email='reclutadora@localmatch.local'").fetchone()
            boss = db.execute("SELECT id FROM users WHERE email='jefe@localmatch.local'").fetchone()
            if owner and boss and not db.execute("SELECT 1 FROM vacancies").fetchone():
                vid = db.insert(
                    "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id) VALUES(?,?,?,?,?,?,?,?)",
                    ("Analista de datos junior", "Operaciones",
                     "Analizar datos de ventas y logística, construir reportes y tableros para la gerencia.",
                     "SQL, Excel, Power BI", "Python, ERP, inglés", 1, owner["id"], boss["id"]))
                for f in sorted(Path("samples").glob("*.txt")):
                    db.execute("INSERT INTO candidates(vacancy_id,filename,redacted_text) VALUES(?,?,?)",
                               (vid, f.name, redact(extract_text(f.name, f.read_bytes()))))
    if creds:
        print("\nUsuarios creados (guarda estas contraseñas, no se vuelven a mostrar):")
        for e, p, r in creds:
            print(f"  {r:<11} {e:<32} {p}")
    else:
        print("Los usuarios iniciales ya existían.")


if __name__ == "__main__":
    main()

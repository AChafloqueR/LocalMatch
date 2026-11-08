"""Crea cuentas para los participantes del estudio SUS y guarda las credenciales en un CSV.

Uso:
  python -m scripts.create_users --role reclutador --count 30
  python -m scripts.create_users --role jefe --count 30
El CSV (credenciales_<rol>.csv) está en .gitignore: entrégalo por un canal privado.
"""
import argparse
import csv
import secrets

from app.auth import hash_password
from app.db import get_db, init_db

ap = argparse.ArgumentParser()
ap.add_argument("--role", choices=["reclutador", "jefe"], required=True)
ap.add_argument("--count", type=int, default=30)
ap.add_argument("--company-id", type=int, required=True, help="id de la empresa (se ve en el menú Participantes)")
a = ap.parse_args()
init_db()
prefix = "rec" if a.role == "reclutador" else "jef"
out = f"credenciales_{a.role}.csv"
with get_db() as db, open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["correo", "contrasena", "rol"])
    for i in range(1, a.count + 1):
        email = f"{prefix}{i:02d}-e{a.company_id}@localmatch.local"
        pw = secrets.token_urlsafe(8)
        db.execute("INSERT OR IGNORE INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)",
                   (email, f"Participante {prefix.upper()}{i:02d}", a.role, hash_password(pw), a.company_id))
        w.writerow([email, pw, a.role])
print(f"Listo: {a.count} cuentas '{a.role}'. Credenciales en {out}")

"""Escenario del estudio (RF-25): vacante, CV sintéticos y lista corta ya generada para cada jefe de área."""
import glob
import io
import os
import secrets
import zipfile

from .auth import hash_password
from .db import audit, get_db
from .skills.pipeline import run_agent
from .skills.redact import redact

OWNER_PATTERN = "escenario-e%@localmatch.local"
TITLE = "Analista de datos junior (tarea del estudio)"
DIR = os.path.join(os.path.dirname(__file__), "scenario_cvs")


def cv_files() -> list[tuple[str, str]]:
    out = []
    for f in sorted(glob.glob(os.path.join(DIR, "*.txt"))):
        out.append((os.path.basename(f), open(f, encoding="utf-8").read()))
    return out


def cvs_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in cv_files():
            z.writestr(name, text)
    return buf.getvalue()


def prepare_for_jefes(actor_id: int | None = None) -> dict:
    """Crea la vacante de práctica (en la empresa de cada jefe) con CV sintéticos y lista corta."""
    new_vids, sin_empresa = [], 0
    with get_db() as db:
        jefes = db.execute("SELECT id, company_id FROM users WHERE role='jefe' ORDER BY id").fetchall()
        for j in jefes:
            if not j["company_id"]:
                sin_empresa += 1
                continue
            email = f"escenario-e{j['company_id']}@localmatch.local"
            owner = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not owner:
                db.execute("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)",
                           (email, "Escenario del estudio", "reclutador", hash_password(secrets.token_urlsafe(24)), j["company_id"]))
                owner = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if db.execute("SELECT 1 FROM vacancies WHERE boss_id=? AND owner_id=?", (j["id"], owner["id"])).fetchone():
                continue
            vid = db.insert(
                "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id,company_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (TITLE, "Operaciones", "Analizar datos de ventas y logística, construir reportes y tableros para la gerencia.",
                 "SQL, Excel, Power BI", "Python, ERP, inglés", 1, owner["id"], j["id"], j["company_id"]))
            for name, text in cv_files():
                db.execute("INSERT INTO candidates(vacancy_id,filename,redacted_text) VALUES(?,?,?)", (vid, name, redact(text)))
            new_vids.append(vid)
    for vid in new_vids:
        run_agent(vid)
    with get_db() as db:
        for vid in new_vids:
            top = db.execute("SELECT id FROM candidates WHERE vacancy_id=? ORDER BY score DESC, id LIMIT 5", (vid,)).fetchall()
            for t in top:
                db.execute("UPDATE candidates SET shortlisted=1 WHERE id=?", (t["id"],))
        audit(db, actor_id, "escenario_preparado", "vacante", None, f"{len(new_vids)} vacante(s) creadas; {sin_empresa} jefe(s) sin empresa")
    return {"creadas": len(new_vids), "cv_por_vacante": len(cv_files()), "lista_corta": 5, "sin_empresa": sin_empresa}

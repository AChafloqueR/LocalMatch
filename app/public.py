"""Portal público del postulante: ver vacantes, postular con CV y consultar el estado con un código (sin correos)."""
import os
import re
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import llm
from .auth import current_user
from .db import audit, get_db
from .parsing import extract_text
from .skills.pipeline import run_agent
from .skills.redact import redact
from .skills.textutil import split_terms

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
MAX_BYTES, MAX_APPLICANTS = 5_000_000, 500
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def render(request: Request, name: str, **ctx):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, {"user": current_user(request), "flash": flash, "provider": llm.provider(), **ctx})


def go(request: Request, url: str, msg: str | None = None):
    if msg:
        request.session["flash"] = msg
    return RedirectResponse(url, status_code=303)


def public_status(c) -> tuple[str, str]:
    """Estado visible para el postulante (nunca muestra puntaje, notas ni comentarios internos)."""
    if c["decision"] == "Entrevistar":
        return "Seleccionado para entrevista", "ok"
    if c["decision"] == "En espera":
        return "En espera de definición", "warn"
    if c["decision"] == "Descartar":
        return "No continúa en el proceso", "bad"
    if c["shortlisted"]:
        return "En revisión por el área solicitante", ""
    if c["score"] is not None:
        return "Evaluada por el equipo de selección", ""
    return "Recibida", ""


def _vacancy(db, vid: int):
    v = db.execute("SELECT v.*, c.name AS company FROM vacancies v JOIN companies c ON c.id=v.company_id "
                   "WHERE v.id=? AND v.status='abierta' AND v.published=1", (vid,)).fetchone()
    if not v:
        raise HTTPException(404, "Esta vacante no está disponible.")
    return v


@router.get("/empleos")
def empleos(request: Request, q: str = ""):
    sql = ("SELECT v.id, v.title, v.area, v.description, v.must, v.min_years, c.name AS company FROM vacancies v "
           "JOIN companies c ON c.id=v.company_id WHERE v.status='abierta' AND v.published=1")
    params: tuple = ()
    if q.strip():
        like = f"%{q.strip().lower()}%"
        sql += " AND (LOWER(v.title) LIKE ? OR LOWER(v.area) LIKE ? OR LOWER(c.name) LIKE ?)"
        params = (like, like, like)
    with get_db() as db:
        rows = db.execute(sql + " ORDER BY v.id DESC LIMIT 100", params).fetchall()
    cards = [dict(r, must_list=split_terms(r["must"])[:4], short=(r["description"][:160] + "…") if len(r["description"]) > 160 else r["description"]) for r in rows]
    return render(request, "empleos.html", rows=cards, q=q)


@router.get("/empleos/{vid}")
def empleo(request: Request, vid: int):
    with get_db() as db:
        v = _vacancy(db, vid)
    d = dict(v, must_list=split_terms(v["must"]), nice_list=split_terms(v["nice"]))
    return render(request, "empleo_detalle.html", v=d)


@router.post("/empleos/{vid}/postular")
async def postular(request: Request, vid: int, name: str = Form(...), email: str = Form(...), phone: str = Form(""),
                   consent: str = Form(""), cv: UploadFile = File(...)):
    back = f"/empleos/{vid}"
    name, email, phone = " ".join(name.split())[:80], email.strip().lower()[:120], phone.strip()[:30]
    if not consent:
        return go(request, back, "Debes aceptar el tratamiento de tus datos para postular.")
    if len(name) < 3 or not EMAIL_RE.match(email):
        return go(request, back, "Revisa tu nombre y tu correo.")
    data = await cv.read()
    fname = cv.filename or ""
    if not fname.lower().endswith((".pdf", ".docx", ".txt")) or len(data) > MAX_BYTES:
        return go(request, back, "Sube tu CV en PDF, DOCX o TXT (máximo 5 MB).")
    try:
        text = extract_text(fname, data).replace("\x00", "")
        if len(text.strip()) < 30:
            raise ValueError
    except Exception:
        return go(request, back, "No pudimos leer tu CV. Prueba con otro archivo (que no sea una imagen escaneada).")
    code = secrets.token_hex(4).upper()
    with get_db() as db:
        _vacancy(db, vid)
        if db.execute("SELECT 1 FROM candidates WHERE vacancy_id=? AND applicant_email=?", (vid, email)).fetchone():
            return go(request, back, "Ya existe una postulación con este correo para esta vacante.")
        if db.execute("SELECT COUNT(*) AS n FROM candidates WHERE vacancy_id=?", (vid,)).fetchone()["n"] >= MAX_APPLICANTS:
            return go(request, back, "Esta vacante ya no recibe más postulaciones.")
        cid = db.insert(
            "INSERT INTO candidates(vacancy_id,filename,redacted_text,applicant_name,applicant_email,applicant_phone,tracking_code,consent_at,source)"
            " VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP,'postulante')",
            (vid, fname[:120], redact(text), name, email, phone or None, code))
        audit(db, None, "postulacion_recibida", "candidato", cid, f"vacante {vid}; consentimiento aceptado")
    run_agent(vid)  # evaluación automática al recibir la postulación
    return go(request, f"/postulacion/{code}", "¡Postulación enviada! Guarda tu código para consultar el estado.")


@router.get("/postulacion")
def postulacion_buscar(request: Request, code: str = ""):
    code = code.strip().upper()
    if not code:
        return go(request, "/empleos", "Escribe tu código de seguimiento.")
    return RedirectResponse(f"/postulacion/{code}", status_code=303)


@router.get("/postulacion/{code}")
def postulacion(request: Request, code: str):
    code = code.strip().upper()
    with get_db() as db:
        c = db.execute("SELECT c.*, v.title AS vtitle, co.name AS company FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id "
                       "JOIN companies co ON co.id=v.company_id WHERE c.tracking_code=?", (code,)).fetchone()
    if not c:
        raise HTTPException(404, "No encontramos una postulación con ese código.")
    text, tone = public_status(c)
    return render(request, "postulacion.html", c=c, status=text, tone=tone, code=code)


@router.post("/postulacion/{code}/eliminar")
def postulacion_eliminar(request: Request, code: str):
    code = code.strip().upper()
    with get_db() as db:
        c = db.execute("SELECT id FROM candidates WHERE tracking_code=?", (code,)).fetchone()
        if not c:
            raise HTTPException(404, "No encontramos una postulación con ese código.")
        db.execute("DELETE FROM candidates WHERE id=?", (c["id"],))
        audit(db, None, "postulacion_eliminada_por_postulante", "candidato", c["id"])
    return go(request, "/empleos", "Tu postulación y tu CV fueron eliminados.")

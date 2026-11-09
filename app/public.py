"""Portal del postulante: registro, convocatorias, postulación con CV y seguimiento en «Mis postulaciones»."""
import hashlib
import random
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import catalog, geo, ranking, reqs
from .auth import current_user, hash_password
from .db import audit, get_db
from .parsing import extract_text
from .skills.pipeline import run_agent, vacancy_dict
from .skills.redact import redact
from .web import go, page

router = APIRouter()
MAX_BYTES, MAX_APPLICANTS, MAX_PER_USER = 5_000_000, 500, 15
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def public_status(c) -> tuple[str, str, str]:
    """Estado visible para el postulante (nunca muestra puntaje, notas ni comentarios internos). Devuelve (texto, tono, detalle)."""
    if c["final_decision"] == "Contratado":
        return "¡Fuiste seleccionado/a para el puesto!", "ok", ""
    if c["final_decision"] == "No contratado":
        return "El proceso concluyó sin selección", "bad", ""
    if c["interview_status"] == "Programada":
        return "Entrevista programada", "ok", f"{(c['interview_at'] or '').replace('T', ' a las ')} · {c['interview_place'] or ''}"
    if c["interview_status"] == "Realizada":
        return "Entrevista realizada: en evaluación final", "warn", ""
    if c["reject_reason"] or c["decision"] == "Descartar":
        return "No continúa en el proceso", "bad", ""
    if c["decision"] == "Entrevistar":
        return "Seleccionado/a para entrevista", "ok", "Pronto se programará la fecha."
    if c["decision"] == "En espera":
        return "En espera de definición", "warn", ""
    if c["shortlisted"]:
        return "En revisión por el área solicitante", "", ""
    if c["score"] is not None:
        return "Evaluada por el equipo de selección", "", ""
    return "Recibida", "", ""


def _postulante(request: Request):
    u = current_user(request)
    return u if u and u["role"] == "postulante" else None


def _open_vacancy(db, vid: int):
    v = db.execute("SELECT v.*, c.name AS company FROM vacancies v JOIN companies c ON c.id=v.company_id "
                   "WHERE v.id=? AND v.status='abierta' AND v.published=1", (vid,)).fetchone()
    if not v or (v["closing_date"] and v["closing_date"] < ranking.today_pe()):
        raise HTTPException(404, "Esta convocatoria no está disponible.")
    return v


# ---------- registro ----------
def _captcha(request: Request) -> str:
    a, b = random.randint(2, 9), random.randint(2, 9)
    request.session["cap"] = a + b
    return f"{a} + {b}"


@router.get("/registro")
def registro_form(request: Request):
    return page(request, "registro.html", cap=_captcha(request), f={})


@router.post("/registro")
async def registro(request: Request):
    form = await request.form()
    name, email, pw = " ".join(str(form.get("name", "")).split())[:80], str(form.get("email", "")).strip().lower()[:120], str(form.get("password", ""))
    f = {"name": name, "email": email}

    def fail(msg):
        request.session["flash"] = msg
        return page(request, "registro.html", cap=_captcha(request), f=f)

    try:
        ok = int(str(form.get("cap", "")).strip()) == request.session.get("cap")
    except ValueError:
        ok = False
    if not ok:
        return fail("La suma no es correcta. Inténtalo de nuevo.")
    if len(name) < 3 or not EMAIL_RE.match(email):
        return fail("Revisa tu nombre y tu correo.")
    if len(pw) < 8:
        return fail("La contraseña debe tener al menos 8 caracteres.")
    with get_db() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return fail("Ya existe una cuenta con ese correo. Ingresa con tu contraseña.")
        uid = db.insert("INSERT INTO users(email,name,role,pw_hash) VALUES(?,?,?,?)", (email, name, "postulante", hash_password(pw)))
        audit(db, uid, "cuenta_postulante_creada", "usuario", uid)
    request.session["uid"] = uid
    return go(request, "/empleos", "¡Cuenta creada! Elige una convocatoria y postula.")


# ---------- convocatorias ----------
@router.get("/empleos")
def empleos(request: Request, q: str = ""):
    sql = ("SELECT v.id, v.title, v.area, v.description, v.min_years, v.closing_date, v.requirements_json, v.must, v.nice, c.name AS company FROM vacancies v "
           "JOIN companies c ON c.id=v.company_id WHERE v.status='abierta' AND v.published=1")
    params: tuple = ()
    if q.strip():
        like = f"%{q.strip().lower()}%"
        sql += " AND (LOWER(v.title) LIKE ? OR LOWER(v.area) LIKE ? OR LOWER(c.name) LIKE ?)"
        params = (like, like, like)
    with get_db() as db:
        ranking.close_expired(db)
        rows = db.execute(sql + " ORDER BY v.id DESC LIMIT 100", params).fetchall()
    cards = [dict(r, chips=[i["name"] for i in reqs.items_from_row(r) if i["mandatory"]][:5],
                  short=(r["description"][:150] + "…") if len(r["description"]) > 150 else r["description"]) for r in rows]
    return page(request, "empleos.html", rows=cards, q=q)


@router.get("/empleos/{vid}")
def empleo(request: Request, vid: int):
    u = _postulante(request)
    with get_db() as db:
        v = _open_vacancy(db, vid)
        applied = db.execute("SELECT id FROM candidates WHERE vacancy_id=? AND user_id=?", (vid, u["id"])).fetchone() if u else None
    d = vacancy_dict(v)
    return page(request, "empleo_detalle.html", v=d, company=v["company"], items=d["items"], kinds=catalog.KINDS, questions=reqs.questions_from_row(v),
                can_apply=bool(u), applied=applied, f={})


@router.post("/empleos/{vid}/postular")
async def postular(request: Request, vid: int):
    u = _postulante(request)
    back = f"/empleos/{vid}"
    if not u:
        return go(request, "/login", "Ingresa con tu cuenta de postulante (o crea una) para postular.")
    form = await request.form()
    g = lambda k, n=200: " ".join(str(form.get(k, "")).split())[:n]  # noqa: E731
    phone, dept, prov, district = g("phone", 12), g("dept", 40), g("prov", 60), g("district", 80)
    exp_role, exp_company, exp_time, exp_desc = g("exp_role", 80), g("exp_company", 80), g("exp_time", 40), str(form.get("exp_desc", "")).strip()[:1200]
    with get_db() as db:
        v = _open_vacancy(db, vid)
    qs = reqs.questions_from_row(v)
    answers = []
    for i, q in enumerate(qs, 1):
        ans = g(f"ans_{i}", 3)
        if ans not in ("Sí", "No"):
            return go(request, back, "Responde todas las preguntas de la convocatoria.")
        answers.append({"text": q["text"], "mandatory": q["mandatory"], "answer": ans})
    if not form.get("adult"):
        return go(request, back, "Debes confirmar que eres mayor de 18 años.")
    if not form.get("consent"):
        return go(request, back, "Debes aceptar el tratamiento de tus datos para postular.")
    if not reqs.valid_phone(phone):
        return go(request, back, "El celular debe tener exactamente 9 dígitos numéricos y empezar con 9.")
    if not geo.valid(dept, prov, district):
        return go(request, back, "Elige tu departamento, tu provincia y tu distrito.")
    if len(exp_role) < 2 or len(exp_company) < 2 or not exp_time or len(exp_desc) < 20:
        return go(request, back, "Cuéntanos tu última experiencia: cargo, empresa, tiempo y una descripción de al menos 20 caracteres.")
    cv = form.get("cv")
    fname = getattr(cv, "filename", "") or ""
    data = await cv.read() if cv else b""
    if not fname.lower().endswith((".pdf", ".docx", ".txt")) or not data or len(data) > MAX_BYTES:
        return go(request, back, "Sube tu CV en PDF, DOCX o TXT (máximo 5 MB).")
    try:
        text = extract_text(fname, data).replace("\x00", "")
        if len(text.strip()) < 30:
            raise ValueError
    except Exception:
        return go(request, back, "No pudimos leer tu CV. Prueba con otro archivo (que no sea una imagen escaneada).")
    digest = hashlib.sha256(data).hexdigest()
    place = geo.label(dept, prov, district)
    experience = f"ÚLTIMA EXPERIENCIA\n{exp_role} en {exp_company} ({exp_time}). {exp_desc}"
    with get_db() as db:
        _open_vacancy(db, vid)
        if db.execute("SELECT 1 FROM candidates WHERE vacancy_id=? AND user_id=?", (vid, u["id"])).fetchone():
            return go(request, back, "Ya postulaste a esta convocatoria. Puedes ver su estado en «Mis postulaciones».")
        if db.execute("SELECT 1 FROM candidates WHERE vacancy_id=? AND cv_hash=?", (vid, digest)).fetchone():
            return go(request, back, "Este mismo archivo ya fue enviado a esta convocatoria.")
        if db.execute("SELECT COUNT(*) AS n FROM candidates WHERE user_id=?", (u["id"],)).fetchone()["n"] >= MAX_PER_USER:
            return go(request, back, f"Alcanzaste el máximo de {MAX_PER_USER} postulaciones.")
        if db.execute("SELECT COUNT(*) AS n FROM candidates WHERE vacancy_id=?", (vid,)).fetchone()["n"] >= MAX_APPLICANTS:
            return go(request, back, "Esta convocatoria ya no recibe más postulaciones.")
        cid = db.insert(
            "INSERT INTO candidates(vacancy_id,filename,redacted_text,applicant_name,applicant_email,applicant_phone,applicant_district,user_id,"
            "exp_role,exp_company,exp_time,exp_description,original_file,original_mime,cv_hash,answers_json,adult_confirmed,tracking_code,consent_at,source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,CURRENT_TIMESTAMP,'postulante')",
            (vid, fname[:120], redact(text) + "\n\n" + redact(experience, strip_first_line=False), u["name"], u["email"], phone, place, u["id"], exp_role, exp_company, exp_time, exp_desc,
             data, getattr(cv, "content_type", None), digest, __import__("json").dumps(answers, ensure_ascii=False), secrets.token_hex(4).upper()))
        audit(db, u["id"], "postulacion_recibida", "candidato", cid, f"vacante {vid}; consentimiento y mayoría de edad confirmados")
    run_agent(vid)  # evaluación automática al recibir la postulación
    return go(request, f"/mis-postulaciones/{cid}/exito")


# ---------- seguimiento ----------
def _mine(db, cid: int, u):
    c = db.execute("SELECT c.*, v.title AS vtitle, co.name AS company FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id "
                   "JOIN companies co ON co.id=v.company_id WHERE c.id=? AND c.user_id=?", (cid, u["id"])).fetchone()
    if not c:
        raise HTTPException(404, "No encontramos esa postulación.")
    return c


@router.get("/mis-postulaciones")
def mis_postulaciones(request: Request):
    u = _postulante(request)
    if not u:
        return go(request, "/login", "Ingresa con tu cuenta de postulante.")
    with get_db() as db:
        rows = db.execute("SELECT c.*, v.title AS vtitle, co.name AS company FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id "
                          "JOIN companies co ON co.id=v.company_id WHERE c.user_id=? ORDER BY c.id DESC", (u["id"],)).fetchall()
    items = []
    for c in rows:
        text, tone, detail = public_status(c)
        items.append({"c": c, "status": text, "tone": tone, "detail": detail})
    return page(request, "mis_postulaciones.html", items=items)


@router.get("/mis-postulaciones/{cid}/exito")
def exito(request: Request, cid: int):
    u = _postulante(request)
    if not u:
        return go(request, "/login", "Ingresa con tu cuenta de postulante.")
    with get_db() as db:
        c = _mine(db, cid, u)
    return page(request, "postulacion_exitosa.html", c=c)


@router.post("/mis-postulaciones/{cid}/eliminar")
def eliminar(request: Request, cid: int):
    u = _postulante(request)
    if not u:
        return go(request, "/login", "Ingresa con tu cuenta de postulante.")
    with get_db() as db:
        c = _mine(db, cid, u)
        db.execute("DELETE FROM candidates WHERE id=?", (c["id"],))
        audit(db, u["id"], "postulacion_eliminada_por_postulante", "candidato", cid)
    return go(request, "/mis-postulaciones", "Tu postulación, tu CV y tus datos fueron eliminados.")

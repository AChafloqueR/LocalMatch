import csv
import io
import json
import os
import secrets

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import llm
from .auth import NeedLogin, current_user, hash_password, require, verify_password
from .config import load_env
from . import public, scenario
from .db import audit, get_db, init_db
from .parsing import extract_text
from .skills.pipeline import run_agent, vacancy_dict
from .skills.redact import redact
from .sus import ITEMS, category, describe, sus_score

load_env()  # carga el .env del proyecto si existe (no pisa variables ya exportadas)

BASE = os.path.dirname(__file__)
app = FastAPI(title="LocalMatch")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"),
    same_site="lax",
    https_only=os.getenv("HTTPS_ONLY", "0") == "1",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}
templates.env.globals["category"] = category

PROFILE = {"reclutador": "Personal de reclutamiento", "jefe": "Jefes de área"}
MAX_FILES, MAX_BYTES = 40, 5_000_000


def task_state(user) -> dict:
    """Tarea del estudio por perfil (RF-24): pasos y si ya se completó."""
    with get_db() as db:
        if user["role"] == "reclutador":
            vac = db.execute("SELECT COUNT(*) AS n FROM vacancies WHERE owner_id=?", (user["id"],)).fetchone()["n"]
            cand = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.owner_id=?", (user["id"],)).fetchone()["n"]
            ran = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.owner_id=? AND c.score IS NOT NULL", (user["id"],)).fetchone()["n"]
            sent = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.owner_id=? AND c.shortlisted=1", (user["id"],)).fetchone()["n"]
            steps = [("Descargar los CV de práctica y crear una vacante", vac > 0), ("Cargar los CV en la vacante", cand > 0),
                     ("Ejecutar el agente (Preseleccionar y ordenar)", ran > 0), ("Enviar al jefe de área al menos un candidato", sent > 0)]
        elif user["role"] == "jefe":
            short = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.boss_id=? AND c.shortlisted=1", (user["id"],)).fetchone()["n"]
            dec = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.boss_id=? AND c.shortlisted=1 AND c.decision IS NOT NULL", (user["id"],)).fetchone()["n"]
            steps = [("Abrir la vacante asignada y revisar la lista corta", short > 0), ("Registrar tu decisión en al menos un candidato", dec > 0)]
        else:
            return {"steps": [], "done": True}
    return {"steps": steps, "done": all(d for _, d in steps)}


def sus_unlocked(user) -> bool:
    return os.getenv("SUS_REQUIRE_TASK", "1") != "1" or task_state(user)["done"]


def bootstrap_admin():
    """Crea el usuario de investigación desde ADMIN_EMAIL / ADMIN_PASSWORD (útil en servidores sin consola)."""
    email, pw = os.getenv("ADMIN_EMAIL", "").strip().lower(), os.getenv("ADMIN_PASSWORD", "")
    if not email or not pw:
        return
    with get_db() as db:
        if not db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            db.execute("INSERT INTO users(email,name,role,pw_hash) VALUES(?,?,?,?)",
                       (email, "Equipo de investigación", "admin", hash_password(pw)))


init_db()
bootstrap_admin()


def page(request: Request, name: str, **ctx):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request, name, {"user": current_user(request), "flash": flash, "provider": llm.provider(), **ctx}
    )


def go(request: Request, url: str, msg: str | None = None):
    if msg:
        request.session["flash"] = msg
    return RedirectResponse(url, status_code=303)


@app.exception_handler(NeedLogin)
async def _need_login(request: Request, exc: NeedLogin):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        request, "error.html", {"user": current_user(request), "flash": None, "provider": llm.provider(),
                                "code": exc.status_code, "detail": exc.detail}, status_code=exc.status_code)


@app.get("/health")
def health():
    return {"ok": True, "llm": llm.provider()}


# ---------- acceso ----------
@app.get("/")
def home(request: Request):
    return go(request, "/dashboard" if current_user(request) else "/empleos")


@app.get("/login")
def login_form(request: Request):
    return page(request, "login.html", error=None)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not u or not verify_password(password, u["pw_hash"]):
        return page(request, "login.html", error="Correo o contraseña incorrectos.")
    request.session["uid"] = u["id"]
    return go(request, "/dashboard")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return go(request, "/login")


@app.get("/dashboard")
def dashboard(request: Request, user=Depends(require())):
    with get_db() as db:
        if user["role"] == "reclutador":
            rows = db.execute(
                "SELECT v.*, (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id) AS n,"
                " (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id AND c.shortlisted=1) AS short"
                " FROM vacancies v WHERE v.company_id=? ORDER BY v.id DESC", (user["company_id"],)).fetchall()
        elif user["role"] == "jefe":
            rows = db.execute(
                "SELECT v.*, (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id AND c.shortlisted=1) AS short,"
                " (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id AND c.shortlisted=1 AND c.decision IS NOT NULL) AS decided"
                " FROM vacancies v WHERE boss_id=? ORDER BY v.id DESC", (user["id"],)).fetchall()
        else:
            rows = []
        sus = db.execute("SELECT 1 FROM sus_responses WHERE user_id=?", (user["id"],)).fetchone()
    task = task_state(user) if user["role"] in ("reclutador", "jefe") else None
    return page(request, "dashboard.html", rows=rows, sus_done=bool(sus), task=task)


# ---------- reclutador: vacantes ----------
@app.get("/vacancies/new")
def vacancy_new(request: Request, user=Depends(require("reclutador"))):
    with get_db() as db:
        bosses = db.execute("SELECT id,name FROM users WHERE role='jefe' AND company_id=? ORDER BY name", (user["company_id"],)).fetchall()
    return page(request, "vacancy_new.html", bosses=bosses)


@app.post("/vacancies/new")
def vacancy_create(request: Request, title: str = Form(...), area: str = Form(...), description: str = Form(...),
                   must: str = Form(""), nice: str = Form(""), min_years: float = Form(0), boss_id: int = Form(...),
                   published: str = Form(""), user=Depends(require("reclutador"))):
    with get_db() as db:
        _check_boss(db, boss_id, user)
        vid = db.insert(
            "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id,company_id,published) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (title.strip(), area.strip(), description.strip(), must, nice, max(min_years, 0), user["id"], boss_id, user["company_id"], 1 if published else 0))
        audit(db, user["id"], "vacante_creada", "vacante", vid, title.strip())
    return go(request, f"/vacancies/{vid}", "Vacante creada. Ahora sube los CV.")


@app.get("/vacancies/{vid}/edit")
def vacancy_edit_form(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        bosses = db.execute("SELECT id,name FROM users WHERE role='jefe' AND company_id=? ORDER BY name", (user["company_id"],)).fetchall()
    return page(request, "vacancy_edit.html", v=v, bosses=bosses)


@app.post("/vacancies/{vid}/edit")
def vacancy_edit(request: Request, vid: int, title: str = Form(...), area: str = Form(...), description: str = Form(...),
                 must: str = Form(""), nice: str = Form(""), min_years: float = Form(0), boss_id: int = Form(...),
                 published: str = Form(""), user=Depends(require("reclutador"))):
    with get_db() as db:
        _own_vacancy(db, vid, user)
        _check_boss(db, boss_id, user)
        db.execute("UPDATE vacancies SET title=?,area=?,description=?,must=?,nice=?,min_years=?,boss_id=?,published=? WHERE id=?",
                   (title.strip(), area.strip(), description.strip(), must, nice, max(min_years, 0), boss_id, 1 if published else 0, vid))
        audit(db, user["id"], "vacante_editada", "vacante", vid, title.strip())
    return go(request, f"/vacancies/{vid}", "Vacante actualizada. Vuelve a ejecutar el agente para recalcular el ranking.")


@app.post("/vacancies/{vid}/toggle-status")
def vacancy_toggle(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        new = "abierta" if v["status"] == "cerrada" else "cerrada"
        db.execute("UPDATE vacancies SET status=? WHERE id=?", (new, vid))
        audit(db, user["id"], "vacante_" + ("cerrada" if new == "cerrada" else "reabierta"), "vacante", vid)
    return go(request, f"/vacancies/{vid}", "Vacante cerrada." if new == "cerrada" else "Vacante reabierta.")


@app.get("/vacancies/{vid}/ranking.csv")
def ranking_csv(vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        rows = db.execute("SELECT * FROM candidates WHERE vacancy_id=? ORDER BY score IS NULL, score DESC, id", (vid,)).fetchall()
        audit(db, user["id"], "ranking_exportado", "vacante", vid, f"{len(rows)} filas")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["posicion", "candidato", "origen", "nombre", "correo", "telefono", "archivo", "puntaje", "requisitos_obligatorios_cumplidos", "faltantes", "anios_experiencia", "formacion", "enviado_al_jefe", "decision_del_jefe"])
    for i, c in enumerate(rows, 1):
        prof = json.loads(c["profile_json"]) if c["profile_json"] else {}
        sc = json.loads(c["breakdown_json"]) if c["breakdown_json"] else {}
        w.writerow([i, f"#{c['id']}", c["source"], c["applicant_name"] or "", c["applicant_email"] or "", c["applicant_phone"] or "", c["filename"], c["score"], ";".join(prof.get("must_found", [])), ";".join(sc.get("must_missing", [])),
                    prof.get("years", ""), prof.get("education", ""), "sí" if c["shortlisted"] else "no", c["decision"] or ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=ranking_vacante_{vid}.csv", "Cache-Control": "no-store"})


@app.get("/task/cvs.zip")
def task_cvs(user=Depends(require("reclutador"))):
    return Response(scenario.cvs_zip(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=CV_de_practica.zip"})


def _own_vacancy(db, vid: int, user):
    """Vacante de la empresa del usuario (multiempresa: nadie ve vacantes de otra empresa)."""
    v = db.execute("SELECT * FROM vacancies WHERE id=?", (vid,)).fetchone()
    if not v or not user["company_id"] or v["company_id"] != user["company_id"]:
        raise HTTPException(404, "Vacante no encontrada.")
    return v


def _check_boss(db, boss_id: int, user):
    ok = db.execute("SELECT 1 FROM users WHERE id=? AND role='jefe' AND company_id=?", (boss_id, user["company_id"])).fetchone()
    if not ok:
        raise HTTPException(400, "El jefe de área debe pertenecer a tu empresa.")


@app.get("/vacancies/{vid}")
def vacancy_detail(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        cands = db.execute(
            "SELECT * FROM candidates WHERE vacancy_id=? ORDER BY score IS NULL, score DESC, id", (vid,)).fetchall()
        boss = db.execute("SELECT name FROM users WHERE id=?", (v["boss_id"],)).fetchone()
    return page(request, "vacancy_detail.html", v=vacancy_dict(v), cands=cands, boss=boss)


@app.post("/vacancies/{vid}/upload")
async def upload(request: Request, vid: int, files: list[UploadFile] = File(...), consent: str = Form(""),
                 user=Depends(require("reclutador"))):
    if not consent:
        return go(request, f"/vacancies/{vid}", "Debes declarar que los CV son sintéticos o que cuentas con el consentimiento de sus titulares.")
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        if v["status"] == "cerrada":
            return go(request, f"/vacancies/{vid}", "La vacante está cerrada. Reábrela para cargar CV.")
        ok = bad = 0
        for f in files[:MAX_FILES]:
            data = await f.read()
            try:
                if not f.filename or len(data) > MAX_BYTES or not f.filename.lower().endswith((".pdf", ".docx", ".txt")):
                    raise ValueError
                text = extract_text(f.filename, data).replace("\x00", "")
                if len(text.strip()) < 30:
                    raise ValueError
            except Exception:
                bad += 1
                continue
            db.execute("INSERT INTO candidates(vacancy_id,filename,redacted_text) VALUES(?,?,?)",
                       (vid, f.filename, redact(text)))
            ok += 1
        audit(db, user["id"], "cv_cargados", "vacante", vid, f"{ok} cargados, {bad} rechazados; declaración de consentimiento aceptada")
    msg = f"{ok} CV cargado(s) y anonimizado(s)." + (f" {bad} no se pudieron leer." if bad else "")
    return go(request, f"/vacancies/{vid}", msg)


@app.post("/vacancies/{vid}/run")
def run(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        if v["status"] == "cerrada":
            return go(request, f"/vacancies/{vid}", "La vacante está cerrada. Reábrela para ejecutar el agente.")
    n = run_agent(vid)
    with get_db() as db:
        audit(db, user["id"], "agente_ejecutado", "vacante", vid, f"{n} candidatos evaluados")
    return go(request, f"/vacancies/{vid}", f"El agente evaluó {n} candidato(s).")


@app.post("/vacancies/{vid}/delete-cvs")
def delete_cvs(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        _own_vacancy(db, vid, user)
        db.execute("DELETE FROM candidates WHERE vacancy_id=?", (vid,))
        audit(db, user["id"], "cv_eliminados_todos", "vacante", vid)
    return go(request, f"/vacancies/{vid}", "Todos los CV de la vacante fueron eliminados.")


def _own_candidate(db, cid: int, user):
    c = db.execute("SELECT c.*, v.company_id AS vac_company FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE c.id=?",
                   (cid,)).fetchone()
    if not c or not user["company_id"] or c["vac_company"] != user["company_id"]:
        raise HTTPException(404, "Candidato no encontrado.")
    return c


@app.post("/candidates/{cid}/shortlist")
def shortlist(request: Request, cid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET shortlisted=? WHERE id=?", (0 if c["shortlisted"] else 1, cid))
        audit(db, user["id"], "candidato_retirado" if c["shortlisted"] else "candidato_enviado", "candidato", cid)
    return go(request, f"/vacancies/{c['vacancy_id']}")


@app.post("/candidates/{cid}/note")
def note(request: Request, cid: int, human_note: str = Form(""), user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET human_note=? WHERE id=?", (human_note.strip()[:500], cid))
        audit(db, user["id"], "nota_manual", "candidato", cid)
    return go(request, f"/vacancies/{c['vacancy_id']}", "Nota guardada.")


@app.post("/candidates/{cid}/delete")
def delete_candidate(request: Request, cid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("DELETE FROM candidates WHERE id=?", (cid,))
        audit(db, user["id"], "cv_eliminado", "candidato", cid)
    return go(request, f"/vacancies/{c['vacancy_id']}", "CV eliminado.")


# ---------- jefe de área ----------
@app.get("/shortlists/{vid}")
def shortlist_view(request: Request, vid: int, user=Depends(require("jefe"))):
    with get_db() as db:
        v = db.execute("SELECT * FROM vacancies WHERE id=? AND boss_id=?", (vid, user["id"])).fetchone()
        if not v:
            raise HTTPException(404, "Vacante no encontrada.")
        cands = db.execute("SELECT * FROM candidates WHERE vacancy_id=? AND shortlisted=1 ORDER BY score DESC",
                           (vid,)).fetchall()
    return page(request, "shortlist.html", v=vacancy_dict(v), cands=cands)


@app.post("/candidates/{cid}/decision")
def decision(request: Request, cid: int, decision: str = Form(...), decision_note: str = Form(""),
             user=Depends(require("jefe"))):
    if decision not in ("Entrevistar", "En espera", "Descartar"):
        raise HTTPException(400, "Decisión no válida.")
    with get_db() as db:
        c = db.execute("SELECT c.vacancy_id FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id "
                       "WHERE c.id=? AND v.boss_id=? AND c.shortlisted=1", (cid, user["id"])).fetchone()
        if not c:
            raise HTTPException(404, "Candidato no encontrado.")
        db.execute("UPDATE candidates SET decision=?, decision_note=? WHERE id=?",
                   (decision, decision_note.strip()[:500], cid))
        audit(db, user["id"], "decision_jefe", "candidato", cid, decision)
    return go(request, f"/shortlists/{c['vacancy_id']}", "Decisión registrada.")


# ---------- evaluación SUS ----------
@app.get("/sus")
def sus_form(request: Request, user=Depends(require("reclutador", "jefe"))):
    with get_db() as db:
        done = db.execute("SELECT * FROM sus_responses WHERE user_id=?", (user["id"],)).fetchone()
    return page(request, "sus.html", items=ITEMS, done=done, profile=PROFILE[user["role"]],
                unlocked=sus_unlocked(user), task=task_state(user))


@app.post("/sus")
async def sus_submit(request: Request, user=Depends(require("reclutador", "jefe"))):
    form = await request.form()
    if not sus_unlocked(user):
        return go(request, "/sus", "Completa primero la tarea para habilitar el cuestionario.")
    try:
        answers = [int(form.get(f"q{i}", "")) for i in range(1, 11)]
        score = sus_score(answers)
    except ValueError:
        return go(request, "/sus", "Responde los 10 ítems antes de enviar.")
    if not form.get("consent"):
        return go(request, "/sus", "Debes aceptar el consentimiento informado.")
    with get_db() as db:
        if db.execute("SELECT 1 FROM sus_responses WHERE user_id=?", (user["id"],)).fetchone():
            return go(request, "/sus", "Ya enviaste tu evaluación. ¡Gracias!")
        db.execute("INSERT INTO sus_responses(user_id,profile,answers,score,experience,comment) VALUES(?,?,?,?,?,?)",
                   (user["id"], PROFILE[user["role"]], json.dumps(answers), score,
                    str(form.get("experience", ""))[:60], str(form.get("comment", ""))[:600]))
    return go(request, "/sus", "¡Gracias! Tu evaluación fue registrada.")


def _sus_rows():
    with get_db() as db:
        return db.execute("SELECT * FROM sus_responses ORDER BY id").fetchall()


@app.get("/admin/sus")
def admin_sus(request: Request, user=Depends(require("admin"))):
    rows = _sus_rows()
    groups = {p: [r["score"] for r in rows if r["profile"] == p] for p in PROFILE.values()}
    stats = {p: describe(s) for p, s in groups.items()}
    return page(request, "admin_sus.html", rows=rows, stats=stats)


@app.get("/admin/sus.csv")
def admin_sus_csv(user=Depends(require("admin"))):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["participante", "perfil", "puntaje_sus", "categoria", "experiencia", *[f"item_{i}" for i in range(1, 11)]])
    for i, r in enumerate(_sus_rows(), 1):
        w.writerow([f"P{i:03d}", r["profile"], r["score"], category(r["score"]), r["experience"], *json.loads(r["answers"])])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sus_respuestas.csv"})


# ---------- administración de cuentas (sin necesidad de consola) ----------
def _user_counts():
    with get_db() as db:
        rows = db.execute("SELECT role, COUNT(*) AS n FROM users WHERE email NOT LIKE ? GROUP BY role", (scenario.OWNER_PATTERN,)).fetchall()
    return {r["role"]: r["n"] for r in rows}


def _companies():
    with get_db() as db:
        return db.execute(
            "SELECT c.id, c.name,"
            " (SELECT COUNT(*) FROM users u WHERE u.company_id=c.id AND u.role='reclutador' AND u.email NOT LIKE ?) AS rec,"
            " (SELECT COUNT(*) FROM users u WHERE u.company_id=c.id AND u.role='jefe') AS jef,"
            " (SELECT COUNT(*) FROM vacancies v WHERE v.company_id=c.id) AS vac"
            " FROM companies c ORDER BY c.name", (scenario.OWNER_PATTERN,)).fetchall()


def _admin_page(request, created=None):
    return page(request, "admin_users.html", counts=_user_counts(), companies=_companies(), created=created)


@app.get("/admin/users")
def admin_users(request: Request, user=Depends(require("admin"))):
    return _admin_page(request)


@app.post("/admin/companies")
def admin_company(request: Request, name: str = Form(...), user=Depends(require("admin"))):
    name = " ".join(name.split())[:80]
    if len(name) < 2:
        raise HTTPException(400, "Escribe el nombre de la empresa.")
    with get_db() as db:
        if db.execute("SELECT 1 FROM companies WHERE name=?", (name,)).fetchone():
            return go(request, "/admin/users", "Esa empresa ya existe.")
        cid = db.insert("INSERT INTO companies(name) VALUES(?)", (name,))
        audit(db, user["id"], "empresa_creada", "empresa", cid, name)
    return go(request, "/admin/users", "Empresa creada. Ahora crea sus cuentas de reclutamiento y jefes de área.")


def _company_or_400(db, role: str, company_id: int | None):
    if role == "admin":
        return None
    if not company_id or not db.execute("SELECT 1 FROM companies WHERE id=?", (company_id,)).fetchone():
        raise HTTPException(400, "Elige la empresa de la cuenta.")
    return company_id


@app.post("/admin/users/one")
def admin_user_one(request: Request, email: str = Form(...), name: str = Form(...), role: str = Form(...),
                   company_id: int | None = Form(None), user=Depends(require("admin"))):
    email = email.strip().lower()
    if role not in ("reclutador", "jefe", "admin") or "@" not in email:
        raise HTTPException(400, "Datos no válidos.")
    pw = secrets.token_urlsafe(9)
    with get_db() as db:
        cid = _company_or_400(db, role, company_id)
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return go(request, "/admin/users", "Ese correo ya existe.")
        db.execute("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)",
                   (email, name.strip()[:80], role, hash_password(pw), cid))
        audit(db, user["id"], "cuenta_creada", "usuario", None, f"{role} · {email}")
    return _admin_page(request, created=(email, pw))


@app.post("/admin/users/bulk")
def admin_users_bulk(role: str = Form(...), count: int = Form(...), company_id: int | None = Form(None), user=Depends(require("admin"))):
    if role not in PROFILE or not 1 <= count <= 100:
        raise HTTPException(400, "Datos no válidos.")
    prefix = "rec" if role == "reclutador" else "jef"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["correo", "contrasena", "rol", "empresa_id"])
    with get_db() as db:
        cid = _company_or_400(db, role, company_id)
        for i in range(1, count + 1):
            email = f"{prefix}{i:02d}-e{cid}@localmatch.local"
            if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                continue
            pw = secrets.token_urlsafe(8)
            db.execute("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)",
                       (email, f"Participante {prefix.upper()}{i:02d} (E{cid})", role, hash_password(pw), cid))
            w.writerow([email, pw, role, cid])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=credenciales_{role}_empresa{cid}.csv",
                             "Cache-Control": "no-store"})


@app.post("/admin/scenario")
def admin_scenario(request: Request, user=Depends(require("admin"))):
    res = scenario.prepare_for_jefes(user["id"])
    msg = (f"Escenario preparado para {res['creadas']} jefe(s) de área: {res['cv_por_vacante']} CV de práctica y una lista corta de {res['lista_corta']}."
           if res["creadas"] else "Todos los jefes de área ya tienen su escenario.")
    if res.get("sin_empresa"):
        msg += f" {res['sin_empresa']} jefe(s) no tienen empresa asignada y se omitieron."
    return go(request, "/admin/users", msg)


@app.get("/admin/audit")
def admin_audit(request: Request, user=Depends(require("admin"))):
    with get_db() as db:
        rows = db.execute("SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200").fetchall()
    return page(request, "admin_audit.html", rows=rows)


app.include_router(public.router)

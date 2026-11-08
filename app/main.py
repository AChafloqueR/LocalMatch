import csv
import io
import json
import os
import re
import secrets

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import llm
from .auth import NeedLogin, current_user, hash_password, require, verify_password
from . import catalog, features, public, ranking, reqs, scenario
from .web import go, own_candidate as _own_candidate, own_vacancy as _own_vacancy, page, templates
from .db import audit, get_db, init_db
from .parsing import extract_text
from .skills.pipeline import run_agent, vacancy_dict
from .skills.redact import redact
from .sus import ITEMS, category, describe, sus_score

BASE = os.path.dirname(__file__)
app = FastAPI(title="LocalMatch")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"),
    same_site="lax",
    https_only=os.getenv("HTTPS_ONLY", "0") == "1",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

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
    if user["role"] == "postulante":
        return go(request, "/empleos")
    metrics = None
    with get_db() as db:
        ranking.close_expired(db)
        if user["role"] == "reclutador":
            metrics = ranking.company_metrics(db, user["company_id"])
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
    return page(request, "dashboard.html", rows=rows, sus_done=bool(sus), task=task, metrics=metrics)


# ---------- reclutador: vacantes ----------
def _form_values(v=None, t=None):
    if v is not None:
        items, qs = reqs.items_from_row(v), reqs.questions_from_row(v)
        return {"title": v["title"], "area": v["area"], "description": v["description"], "min_years": v["min_years"], "boss_id": v["boss_id"],
                "published": bool(v["published"]), "closing_date": v["closing_date"] or "", "top_n": v["top_n"] or 5,
                "rows": reqs.pad_rows(items), "qrows": reqs.pad_questions(qs)}
    if t is not None:
        qs = [{"text": q, "mandatory": m} for q, m in t["questions"]]
        return {"title": t["title"], "area": t["area"], "description": t["description"], "min_years": t["min_years"], "boss_id": None,
                "published": True, "closing_date": "", "top_n": 5, "rows": reqs.pad_rows(t["items"]), "qrows": reqs.pad_questions(qs)}
    return {"title": "", "area": "", "description": "", "min_years": 1, "boss_id": None, "published": True, "closing_date": "", "top_n": 5,
            "rows": reqs.pad_rows([]), "qrows": reqs.pad_questions([])}


def _vacancy_fields(form) -> dict:
    title, area = " ".join(str(form.get("title", "")).split())[:100], " ".join(str(form.get("area", "")).split())[:80]
    description = str(form.get("description", "")).strip()[:3000]
    if not title or not area or not description:
        raise HTTPException(400, "Completa el puesto, el área y la descripción.")
    try:
        boss_id = int(form.get("boss_id", ""))
        min_years = max(float(form.get("min_years", 0) or 0), 0)
        top_n = min(max(int(form.get("top_n", 5) or 5), 3), 10)
    except ValueError:
        raise HTTPException(400, "Revisa los números del formulario.")
    closing = str(form.get("closing_date", "")).strip()
    if closing and not re.match(r"^\d{4}-\d{2}-\d{2}$", closing):
        raise HTTPException(400, "La fecha límite no es válida.")
    items = reqs.items_from_form(form)
    must, nice = reqs.legacy_lists(items)
    return {"title": title, "area": area, "description": description, "boss_id": boss_id, "min_years": min_years, "top_n": top_n,
            "closing": closing or None, "published": 1 if form.get("published") else 0, "items": items, "must": must, "nice": nice,
            "questions": reqs.questions_from_form(form)}


def _bosses(db, user):
    return db.execute("SELECT id,name FROM users WHERE role='jefe' AND company_id=? ORDER BY name", (user["company_id"],)).fetchall()


@app.get("/vacancies/new")
def vacancy_new(request: Request, plantilla: str = "", user=Depends(require("reclutador"))):
    with get_db() as db:
        bosses = _bosses(db, user)
    f = _form_values(t=catalog.template(plantilla))
    return page(request, "vacancy_new.html", bosses=bosses, f=f, plantillas=catalog.TEMPLATES, kinds=catalog.KINDS, plantilla=plantilla)


@app.post("/vacancies/new")
async def vacancy_create(request: Request, user=Depends(require("reclutador"))):
    d = _vacancy_fields(await request.form())
    with get_db() as db:
        _check_boss(db, d["boss_id"], user)
        vid = db.insert(
            "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id,company_id,published,requirements_json,questions_json,closing_date,top_n)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["title"], d["area"], d["description"], d["must"], d["nice"], d["min_years"], user["id"], d["boss_id"], user["company_id"], d["published"],
             json.dumps(d["items"], ensure_ascii=False), json.dumps(d["questions"], ensure_ascii=False), d["closing"], d["top_n"]))
        audit(db, user["id"], "vacante_creada", "vacante", vid, d["title"])
    return go(request, f"/vacancies/{vid}", "Convocatoria creada." + (" Ya aparece en el portal de empleos." if d["published"] else " Ahora sube los CV."))


@app.get("/vacancies/{vid}/edit")
def vacancy_edit_form(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        bosses = _bosses(db, user)
    return page(request, "vacancy_edit.html", v=v, bosses=bosses, f=_form_values(v=v), kinds=catalog.KINDS)


@app.post("/vacancies/{vid}/edit")
async def vacancy_edit(request: Request, vid: int, user=Depends(require("reclutador"))):
    d = _vacancy_fields(await request.form())
    with get_db() as db:
        _own_vacancy(db, vid, user)
        _check_boss(db, d["boss_id"], user)
        db.execute("UPDATE vacancies SET title=?,area=?,description=?,must=?,nice=?,min_years=?,boss_id=?,published=?,requirements_json=?,questions_json=?,closing_date=?,top_n=? WHERE id=?",
                   (d["title"], d["area"], d["description"], d["must"], d["nice"], d["min_years"], d["boss_id"], d["published"],
                    json.dumps(d["items"], ensure_ascii=False), json.dumps(d["questions"], ensure_ascii=False), d["closing"], d["top_n"], vid))
        audit(db, user["id"], "vacante_editada", "vacante", vid, d["title"])
    return go(request, f"/vacancies/{vid}", "Convocatoria actualizada. Vuelve a ejecutar el agente para recalcular el ranking.")


@app.post("/vacancies/{vid}/toggle-status")
def vacancy_toggle(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        new = "abierta" if v["status"] == "cerrada" else "cerrada"
        db.execute("UPDATE vacancies SET status=? WHERE id=?", (new, vid))
        if new == "cerrada":
            ranking.purge_originals(db, vid)
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


def _check_boss(db, boss_id: int, user):
    ok = db.execute("SELECT 1 FROM users WHERE id=? AND role='jefe' AND company_id=?", (boss_id, user["company_id"])).fetchone()
    if not ok:
        raise HTTPException(400, "El jefe de área debe pertenecer a tu empresa.")


@app.get("/vacancies/{vid}")
def vacancy_detail(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        cands = db.execute("SELECT * FROM candidates WHERE vacancy_id=?", (vid,)).fetchall()
        boss = db.execute("SELECT name FROM users WHERE id=?", (v["boss_id"],)).fetchone()
    vd = vacancy_dict(v)
    rows = ranking.decorate(cands, vd)
    return page(request, "vacancy_detail.html", v=vd, cands=rows, boss=boss, n_top=sum(1 for r in rows if r["in_top"]), n_sel=sum(1 for r in rows if r["shortlisted"]))


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
            db.execute("INSERT INTO candidates(vacancy_id,filename,redacted_text,original_file,original_mime,applicant_name,source) VALUES(?,?,?,?,?,?,'reclutamiento')",
                       (vid, f.filename, redact(text), data, f.content_type, os.path.splitext(f.filename)[0][:80]))
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
        cands = db.execute("SELECT * FROM candidates WHERE vacancy_id=? AND shortlisted=1", (vid,)).fetchall()
    vd = vacancy_dict(v)
    return page(request, "shortlist.html", v=vd, cands=ranking.decorate(cands, vd))


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


app.include_router(features.router)

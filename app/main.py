import csv
import io
import json
import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import llm
from .auth import NeedLogin, current_user, require, verify_password
from .db import get_db, init_db
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
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}
templates.env.globals["category"] = category

PROFILE = {"reclutador": "Personal de reclutamiento", "jefe": "Jefes de área"}
MAX_FILES, MAX_BYTES = 40, 5_000_000


init_db()


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
    return go(request, "/dashboard" if current_user(request) else "/login")


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
                " FROM vacancies v WHERE owner_id=? ORDER BY v.id DESC", (user["id"],)).fetchall()
        elif user["role"] == "jefe":
            rows = db.execute(
                "SELECT v.*, (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id AND c.shortlisted=1) AS short,"
                " (SELECT COUNT(*) FROM candidates c WHERE c.vacancy_id=v.id AND c.shortlisted=1 AND c.decision IS NOT NULL) AS decided"
                " FROM vacancies v WHERE boss_id=? ORDER BY v.id DESC", (user["id"],)).fetchall()
        else:
            rows = []
        sus = db.execute("SELECT 1 FROM sus_responses WHERE user_id=?", (user["id"],)).fetchone()
    return page(request, "dashboard.html", rows=rows, sus_done=bool(sus))


# ---------- reclutador: vacantes ----------
@app.get("/vacancies/new")
def vacancy_new(request: Request, user=Depends(require("reclutador"))):
    with get_db() as db:
        bosses = db.execute("SELECT id,name FROM users WHERE role='jefe' ORDER BY name").fetchall()
    return page(request, "vacancy_new.html", bosses=bosses)


@app.post("/vacancies/new")
def vacancy_create(request: Request, title: str = Form(...), area: str = Form(...), description: str = Form(...),
                   must: str = Form(""), nice: str = Form(""), min_years: float = Form(0), boss_id: int = Form(...),
                   user=Depends(require("reclutador"))):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id) VALUES(?,?,?,?,?,?,?,?)",
            (title.strip(), area.strip(), description.strip(), must, nice, max(min_years, 0), user["id"], boss_id))
        vid = cur.lastrowid
    return go(request, f"/vacancies/{vid}", "Vacante creada. Ahora sube los CV.")


def _own_vacancy(db, vid: int, user):
    v = db.execute("SELECT * FROM vacancies WHERE id=?", (vid,)).fetchone()
    if not v or v["owner_id"] != user["id"]:
        raise HTTPException(404, "Vacante no encontrada.")
    return v


@app.get("/vacancies/{vid}")
def vacancy_detail(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        v = _own_vacancy(db, vid, user)
        cands = db.execute(
            "SELECT * FROM candidates WHERE vacancy_id=? ORDER BY score IS NULL, score DESC, id", (vid,)).fetchall()
        boss = db.execute("SELECT name FROM users WHERE id=?", (v["boss_id"],)).fetchone()
    return page(request, "vacancy_detail.html", v=vacancy_dict(v), cands=cands, boss=boss)


@app.post("/vacancies/{vid}/upload")
async def upload(request: Request, vid: int, files: list[UploadFile] = File(...), user=Depends(require("reclutador"))):
    with get_db() as db:
        _own_vacancy(db, vid, user)
        ok = bad = 0
        for f in files[:MAX_FILES]:
            data = await f.read()
            try:
                if not f.filename or len(data) > MAX_BYTES:
                    raise ValueError
                text = extract_text(f.filename, data)
                if len(text.strip()) < 30:
                    raise ValueError
            except Exception:
                bad += 1
                continue
            db.execute("INSERT INTO candidates(vacancy_id,filename,redacted_text) VALUES(?,?,?)",
                       (vid, f.filename, redact(text)))
            ok += 1
    msg = f"{ok} CV cargado(s) y anonimizado(s)." + (f" {bad} no se pudieron leer." if bad else "")
    return go(request, f"/vacancies/{vid}", msg)


@app.post("/vacancies/{vid}/run")
def run(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        _own_vacancy(db, vid, user)
    n = run_agent(vid)
    return go(request, f"/vacancies/{vid}", f"El agente evaluó {n} candidato(s).")


@app.post("/vacancies/{vid}/delete-cvs")
def delete_cvs(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        _own_vacancy(db, vid, user)
        db.execute("DELETE FROM candidates WHERE vacancy_id=?", (vid,))
    return go(request, f"/vacancies/{vid}", "Todos los CV de la vacante fueron eliminados.")


def _own_candidate(db, cid: int, user):
    c = db.execute("SELECT c.*, v.owner_id FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE c.id=?",
                   (cid,)).fetchone()
    if not c or c["owner_id"] != user["id"]:
        raise HTTPException(404, "Candidato no encontrado.")
    return c


@app.post("/candidates/{cid}/shortlist")
def shortlist(request: Request, cid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET shortlisted=? WHERE id=?", (0 if c["shortlisted"] else 1, cid))
    return go(request, f"/vacancies/{c['vacancy_id']}")


@app.post("/candidates/{cid}/note")
def note(request: Request, cid: int, human_note: str = Form(""), user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET human_note=? WHERE id=?", (human_note.strip()[:500], cid))
    return go(request, f"/vacancies/{c['vacancy_id']}", "Nota guardada.")


@app.post("/candidates/{cid}/delete")
def delete_candidate(request: Request, cid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        c = _own_candidate(db, cid, user)
        db.execute("DELETE FROM candidates WHERE id=?", (cid,))
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
    return go(request, f"/shortlists/{c['vacancy_id']}", "Decisión registrada.")


# ---------- evaluación SUS ----------
@app.get("/sus")
def sus_form(request: Request, user=Depends(require("reclutador", "jefe"))):
    with get_db() as db:
        done = db.execute("SELECT * FROM sus_responses WHERE user_id=?", (user["id"],)).fetchone()
    return page(request, "sus.html", items=ITEMS, done=done, profile=PROFILE[user["role"]])


@app.post("/sus")
async def sus_submit(request: Request, user=Depends(require("reclutador", "jefe"))):
    form = await request.form()
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

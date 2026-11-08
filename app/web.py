"""Piezas compartidas por las rutas: plantillas, mensajes, redirecciones y permisos por empresa."""
import json
import os

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import llm
from .auth import current_user
from .sus import category

BASE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}
templates.env.globals["category"] = category


def page(request: Request, name: str, **ctx):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request, name, {"user": current_user(request), "flash": flash, "provider": llm.provider(), **ctx})


def go(request: Request, url: str, msg: str | None = None):
    if msg:
        request.session["flash"] = msg
    return RedirectResponse(url, status_code=303)


def own_vacancy(db, vid: int, user):
    """Vacante de la empresa del usuario (multiempresa: nadie ve vacantes de otra empresa)."""
    v = db.execute("SELECT * FROM vacancies WHERE id=?", (vid,)).fetchone()
    if not v or not user["company_id"] or v["company_id"] != user["company_id"]:
        raise HTTPException(404, "Convocatoria no encontrada.")
    return v


def own_candidate(db, cid: int, user):
    c = db.execute("SELECT c.*, v.company_id AS vac_company FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE c.id=?",
                   (cid,)).fetchone()
    if not c or not user["company_id"] or c["vac_company"] != user["company_id"]:
        raise HTTPException(404, "Candidato no encontrado.")
    return c

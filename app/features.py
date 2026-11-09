"""Funciones del personal de reclutamiento y del jefe de área: top N, descargas, comparador, descarte, entrevistas y rúbrica."""
import csv
import io
import json
import os
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import Response

from . import catalog, ranking
from .auth import hash_password, require
from .db import audit, get_db, get_or_create_company
from .skills.pipeline import vacancy_dict
from .web import go, own_candidate, own_vacancy, page

router = APIRouter()
REASONS = ["No cumple los requisitos excluyentes", "Experiencia insuficiente", "Perfil no alineado al puesto", "Otro motivo"]
RUBRIC = [("tecnico", "Conocimientos técnicos"), ("comunicacion", "Comunicación"), ("ajuste", "Ajuste al puesto"), ("actitud", "Actitud y trabajo en equipo")]


def _load(db, vid):
    v = vacancy_dict(db.execute("SELECT * FROM vacancies WHERE id=?", (vid,)).fetchone())
    rows = ranking.decorate(db.execute("SELECT * FROM candidates WHERE vacancy_id=?", (vid,)).fetchall(), v)
    return v, rows


# ---------- reclutamiento ----------
@router.post("/vacancies/{vid}/send-top")
def send_top(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        own_vacancy(db, vid, user)
        v, rows = _load(db, vid)
        top = [r for r in rows if r["in_top"]]
        if not top:
            return go(request, f"/vacancies/{vid}", "Aún no hay candidatos que cumplan los requisitos excluyentes. Ejecuta el agente primero.")
        boss = db.execute("SELECT name, email FROM users WHERE id=?", (v["boss_id"],)).fetchone()
        who = f"{boss['name']} ({boss['email']})" if boss else "el jefe de área"
        for r in top:
            if not r["shortlisted"]:
                db.execute("UPDATE candidates SET shortlisted=1 WHERE id=?", (r["id"],))
                audit(db, user["id"], "candidato_enviado", "candidato", r["id"], "enviado desde el top del agente")
    return go(request, f"/vacancies/{vid}", f"Se enviaron {len(top)} candidato(s) a {who}. Los verá al ingresar con su cuenta.")


@router.get("/vacancies/{vid}/seleccionados.zip")
def selected_zip(request: Request, vid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        own_vacancy(db, vid, user)
        v, rows = _load(db, vid)
        sel = [r for r in rows if r["shortlisted"]]
        if not sel:
            return go(request, f"/vacancies/{vid}", "Aún no hay candidatos seleccionados para descargar.")
        audit(db, user["id"], "descarga_seleccionados", "vacante", vid, f"{len(sel)} candidatos")
    return Response(ranking.build_zip(sel, v), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=seleccionados_vacante_{vid}.zip", "Cache-Control": "no-store"})


@router.get("/vacancies/{vid}/comparar")
def compare(request: Request, vid: int, ids: list[int] = Query(default=[]), user=Depends(require("reclutador"))):
    with get_db() as db:
        own_vacancy(db, vid, user)
        v, rows = _load(db, vid)
    chosen = [r for r in rows if r["id"] in ids][:4]
    if len(chosen) < 2:
        return go(request, f"/vacancies/{vid}", "Marca entre 2 y 4 candidatos para compararlos.")
    return page(request, "comparar.html", v=v, cands=chosen)


@router.post("/candidates/{cid}/reject")
def reject(request: Request, cid: int, reason: str = Form(...), note: str = Form(""), user=Depends(require("reclutador"))):
    if reason not in REASONS:
        raise HTTPException(400, "Elige un motivo de descarte.")
    text = reason + (f": {note.strip()[:200]}" if note.strip() else "")
    with get_db() as db:
        c = own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET reject_reason=?, shortlisted=0 WHERE id=?", (text, cid))
        audit(db, user["id"], "candidato_descartado", "candidato", cid, text)
    return go(request, f"/vacancies/{c['vacancy_id']}", "Candidato descartado. Quedó registrado el motivo.")


@router.post("/candidates/{cid}/reopen")
def reopen(request: Request, cid: int, user=Depends(require("reclutador"))):
    with get_db() as db:
        c = own_candidate(db, cid, user)
        db.execute("UPDATE candidates SET reject_reason=NULL WHERE id=?", (cid,))
        audit(db, user["id"], "candidato_reabierto", "candidato", cid)
    return go(request, f"/vacancies/{c['vacancy_id']}", "Candidato reabierto.")


# ---------- descarga de CV (reclutamiento o jefe) ----------
@router.get("/candidates/{cid}/cv")
def download_cv(cid: int, user=Depends(require("reclutador", "jefe"))):
    with get_db() as db:
        if user["role"] == "reclutador":
            c = own_candidate(db, cid, user)
        else:
            c = db.execute("SELECT c.* FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE c.id=? AND c.shortlisted=1 AND v.boss_id=?",
                           (cid, user["id"])).fetchone()
            if not c:
                raise HTTPException(404, "Candidato no encontrado.")
        if c["original_file"] is None:
            raise HTTPException(404, "El archivo original ya no está disponible (se elimina al cerrar la convocatoria si el candidato no fue seleccionado).")
        audit(db, user["id"], "cv_descargado", "candidato", cid)
        data, name, mime = bytes(c["original_file"]), c["filename"], c["original_mime"] or "application/octet-stream"
    ext = os.path.splitext(name)[1].lower() or ".pdf"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="CV_{cid}{ext}"', "Cache-Control": "no-store"})


# ---------- jefe de área ----------
def _boss_candidate(db, cid, user):
    c = db.execute("SELECT c.* FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE c.id=? AND c.shortlisted=1 AND v.boss_id=?", (cid, user["id"])).fetchone()
    if not c:
        raise HTTPException(404, "Candidato no encontrado.")
    return c


@router.get("/shortlists/{vid}/cvs.zip")
def boss_zip(request: Request, vid: int, user=Depends(require("jefe"))):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM vacancies WHERE id=? AND boss_id=?", (vid, user["id"])).fetchone():
            raise HTTPException(404, "Convocatoria no encontrada.")
        v, rows = _load(db, vid)
        sel = [r for r in rows if r["shortlisted"]]
        if not sel:
            return go(request, f"/shortlists/{vid}", "Aún no tienes candidatos para descargar.")
        audit(db, user["id"], "descarga_lista_corta", "vacante", vid, f"{len(sel)} candidatos")
    return Response(ranking.build_zip(sel, v), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=lista_corta_vacante_{vid}.zip", "Cache-Control": "no-store"})


@router.post("/candidates/{cid}/interview")
def schedule(request: Request, cid: int, at: str = Form(...), place: str = Form(...), user=Depends(require("jefe"))):
    with get_db() as db:
        c = _boss_candidate(db, cid, user)
        if c["decision"] != "Entrevistar":
            return go(request, "/dashboard", "Primero marca la decisión «Entrevistar».")
        db.execute("UPDATE candidates SET interview_at=?, interview_place=?, interview_status='Programada' WHERE id=?", (at.strip()[:20], place.strip()[:160], cid))
        audit(db, user["id"], "entrevista_programada", "candidato", cid, f"{at} · {place.strip()[:60]}")
    return go(request, "/dashboard", "Entrevista programada.")


@router.post("/candidates/{cid}/interview-done")
def interview_done(request: Request, cid: int, user=Depends(require("jefe"))):
    with get_db() as db:
        c = _boss_candidate(db, cid, user)
        if c["interview_status"] != "Programada":
            return go(request, "/dashboard", "La entrevista aún no está programada.")
        db.execute("UPDATE candidates SET interview_status='Realizada' WHERE id=?", (cid,))
        audit(db, user["id"], "entrevista_realizada", "candidato", cid)
    return go(request, "/dashboard", "Entrevista marcada como realizada. Ya puedes registrar la evaluación.")


@router.post("/candidates/{cid}/rubric")
async def rubric(request: Request, cid: int, user=Depends(require("jefe"))):
    form = await request.form()
    with get_db() as db:
        c = _boss_candidate(db, cid, user)
        if c["interview_status"] != "Realizada":
            return go(request, "/dashboard", "Registra la evaluación después de realizar la entrevista.")
        try:
            scores = {k: min(max(int(form.get(f"r_{k}", "")), 1), 5) for k, _ in RUBRIC}
        except ValueError:
            return go(request, "/dashboard", "Califica los 4 criterios del 1 al 5.")
        final = form.get("final")
        if final not in ("Contratado", "No contratado"):
            return go(request, "/dashboard", "Elige la decisión final.")
        db.execute("UPDATE candidates SET rubric_json=?, rubric_note=?, final_decision=? WHERE id=?",
                   (json.dumps(scores), str(form.get("note", ""))[:400], final, cid))
        audit(db, user["id"], "evaluacion_entrevista", "candidato", cid, final)
    return go(request, "/dashboard", "Evaluación y decisión final registradas.")


# ---------- administración: empresas y convocatorias de ejemplo ----------
DEMO_COMPANIES = [
    ("NTT DATA", "nttdata", ["ing-sistemas", "analista-datos", "asistente-administrativo"]),
    ("FISAC", "fisac", ["asistente-contable", "analista-datos", "asistente-administrativo"]),
    ("TRC", "trc", ["ing-mecanico", "asistente-administrativo", "asesor-comercial"]),
    ("Estudio Jurídico Muñoz", "estudiomunoz", ["practicante-derecho", "asistente-administrativo", "asistente-contable"]),
    ("Backus", "backus", ["ing-mecanico", "analista-datos", "asesor-comercial", "asistente-contable"]),
    ("BRAMOTORS", "bramotors", ["ing-mecanico", "asesor-comercial", "asistente-administrativo", "asistente-contable"]),
]


def create_from_templates(db, company_id: int, owner_id: int, boss_id: int, slugs=None) -> int:
    created = 0
    for t in catalog.TEMPLATES:
        if slugs is not None and t["slug"] not in slugs:
            continue
        if db.execute("SELECT 1 FROM vacancies WHERE company_id=? AND title=?", (company_id, t["title"])).fetchone():
            continue
        must = ", ".join(i["name"] for i in t["items"] if i["mandatory"])
        nice = ", ".join(i["name"] for i in t["items"] if not i["mandatory"])
        qs = [{"text": q, "mandatory": m} for q, m in t["questions"]]
        db.insert(
            "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id,company_id,published,requirements_json,questions_json,top_n)"
            " VALUES(?,?,?,?,?,?,?,?,?,1,?,?,5)",
            (t["title"], t["area"], t["description"], must, nice, t["min_years"], owner_id, boss_id, company_id,
             json.dumps(t["items"], ensure_ascii=False), json.dumps(qs, ensure_ascii=False)))
        created += 1
    return created


@router.post("/admin/companies/{company_id}/demo")
def demo_vacancies(request: Request, company_id: int, user=Depends(require("admin"))):
    with get_db() as db:
        owner = db.execute("SELECT id FROM users WHERE role='reclutador' AND company_id=? AND email NOT LIKE ? ORDER BY id LIMIT 1",
                           (company_id, "escenario-e%@localmatch.local")).fetchone()
        boss = db.execute("SELECT id FROM users WHERE role='jefe' AND company_id=? ORDER BY id LIMIT 1", (company_id,)).fetchone()
        if not owner or not boss:
            return go(request, f"/admin/companies/{company_id}", "La empresa necesita al menos una cuenta de reclutamiento y un jefe de área.")
        created = create_from_templates(db, company_id, owner["id"], boss["id"])
        audit(db, user["id"], "convocatorias_de_ejemplo", "empresa", company_id, f"{created} creadas")
    return go(request, f"/admin/companies/{company_id}", f"Se crearon {created} convocatorias de ejemplo y quedaron publicadas en el portal." if created else "Esa empresa ya tiene las convocatorias de ejemplo.")


@router.post("/admin/demo-empresas")
def demo_empresas(user=Depends(require("admin"))):
    """Registra las empresas de ejemplo con una cuenta de reclutamiento, una de jefe y sus convocatorias. Devuelve las credenciales en un CSV."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["empresa", "rol", "correo", "contrasena"])
    with get_db() as db:
        for name, slug, tpls in DEMO_COMPANIES:
            cid = get_or_create_company(db, name)
            ids = {}
            for role, email, uname in [("reclutador", f"reclutadora.{slug}@localmatch.local", f"Reclutadora {name}"), ("jefe", f"jefe.{slug}@localmatch.local", f"Jefe {name}")]:
                row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                if row:
                    ids[role] = row["id"]
                    continue
                pw = secrets.token_urlsafe(8)
                ids[role] = db.insert("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)", (email, uname, role, hash_password(pw), cid))
                w.writerow([name, role, email, pw])
            create_from_templates(db, cid, ids["reclutador"], ids["jefe"], tpls)
        audit(db, user["id"], "empresas_de_ejemplo", "empresa", None, f"{len(DEMO_COMPANIES)} empresas")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=credenciales_empresas_ejemplo.csv", "Cache-Control": "no-store"})


@router.get("/admin/companies/{company_id}")
def company_detail(request: Request, company_id: int, user=Depends(require("admin"))):
    with get_db() as db:
        c = db.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not c:
            raise HTTPException(404, "Empresa no encontrada.")
        users = db.execute("SELECT id, name, email, role FROM users WHERE company_id=? AND email NOT LIKE ? ORDER BY role, name", (company_id, "escenario-e%@localmatch.local")).fetchall()
        vacs = db.execute("SELECT v.id, v.title, v.status, v.published, v.closing_date, (SELECT COUNT(*) FROM candidates x WHERE x.vacancy_id=v.id) AS n,"
                          " (SELECT COUNT(*) FROM candidates x WHERE x.vacancy_id=v.id AND x.shortlisted=1) AS short FROM vacancies v WHERE v.company_id=? ORDER BY v.id DESC", (company_id,)).fetchall()
    return page(request, "admin_company.html", c=c, users=users, vacs=vacs)

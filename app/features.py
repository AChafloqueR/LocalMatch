"""Funciones del personal de reclutamiento y del jefe de área: top N, descargas, comparador, descarte, entrevistas y rúbrica."""
import json
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import Response

from . import catalog, ranking
from .auth import require
from .db import audit, get_db
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
        for r in top:
            if not r["shortlisted"]:
                db.execute("UPDATE candidates SET shortlisted=1 WHERE id=?", (r["id"],))
                audit(db, user["id"], "candidato_enviado", "candidato", r["id"], "enviado desde el top del agente")
    return go(request, f"/vacancies/{vid}", f"Se enviaron al jefe de área los {len(top)} mejores candidatos.")


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
            return go(request, f"/shortlists/{c['vacancy_id']}", "Primero marca la decisión «Entrevistar».")
        db.execute("UPDATE candidates SET interview_at=?, interview_place=?, interview_status='Programada' WHERE id=?", (at.strip()[:20], place.strip()[:160], cid))
        audit(db, user["id"], "entrevista_programada", "candidato", cid, f"{at} · {place.strip()[:60]}")
    return go(request, f"/shortlists/{c['vacancy_id']}", "Entrevista programada.")


@router.post("/candidates/{cid}/interview-done")
def interview_done(request: Request, cid: int, user=Depends(require("jefe"))):
    with get_db() as db:
        c = _boss_candidate(db, cid, user)
        if c["interview_status"] != "Programada":
            return go(request, f"/shortlists/{c['vacancy_id']}", "La entrevista aún no está programada.")
        db.execute("UPDATE candidates SET interview_status='Realizada' WHERE id=?", (cid,))
        audit(db, user["id"], "entrevista_realizada", "candidato", cid)
    return go(request, f"/shortlists/{c['vacancy_id']}", "Entrevista marcada como realizada. Ya puedes registrar la evaluación.")


@router.post("/candidates/{cid}/rubric")
async def rubric(request: Request, cid: int, user=Depends(require("jefe"))):
    form = await request.form()
    with get_db() as db:
        c = _boss_candidate(db, cid, user)
        if c["interview_status"] != "Realizada":
            return go(request, f"/shortlists/{c['vacancy_id']}", "Registra la evaluación después de realizar la entrevista.")
        try:
            scores = {k: min(max(int(form.get(f"r_{k}", "")), 1), 5) for k, _ in RUBRIC}
        except ValueError:
            return go(request, f"/shortlists/{c['vacancy_id']}", "Califica los 4 criterios del 1 al 5.")
        final = form.get("final")
        if final not in ("Contratado", "No contratado"):
            return go(request, f"/shortlists/{c['vacancy_id']}", "Elige la decisión final.")
        db.execute("UPDATE candidates SET rubric_json=?, rubric_note=?, final_decision=? WHERE id=?",
                   (json.dumps(scores), str(form.get("note", ""))[:400], final, cid))
        audit(db, user["id"], "evaluacion_entrevista", "candidato", cid, final)
    return go(request, f"/shortlists/{c['vacancy_id']}", "Evaluación y decisión final registradas.")


# ---------- administración: convocatorias de ejemplo ----------
@router.post("/admin/companies/{company_id}/demo")
def demo_vacancies(request: Request, company_id: int, user=Depends(require("admin"))):
    import json as _j

    with get_db() as db:
        owner = db.execute("SELECT id FROM users WHERE role='reclutador' AND company_id=? AND email NOT LIKE ? ORDER BY id LIMIT 1",
                           (company_id, "escenario-e%@localmatch.local")).fetchone()
        boss = db.execute("SELECT id FROM users WHERE role='jefe' AND company_id=? ORDER BY id LIMIT 1", (company_id,)).fetchone()
        if not owner or not boss:
            return go(request, "/admin/users", "La empresa necesita al menos una cuenta de reclutamiento y un jefe de área.")
        created = 0
        for t in catalog.TEMPLATES:
            if db.execute("SELECT 1 FROM vacancies WHERE company_id=? AND title=?", (company_id, t["title"])).fetchone():
                continue
            must = ", ".join(i["name"] for i in t["items"] if i["mandatory"])
            nice = ", ".join(i["name"] for i in t["items"] if not i["mandatory"])
            qs = [{"text": q, "mandatory": m} for q, m in t["questions"]]
            vid = db.insert(
                "INSERT INTO vacancies(title,area,description,must,nice,min_years,owner_id,boss_id,company_id,published,requirements_json,questions_json,top_n)"
                " VALUES(?,?,?,?,?,?,?,?,?,1,?,?,5)",
                (t["title"], t["area"], t["description"], must, nice, t["min_years"], owner["id"], boss["id"], company_id,
                 _j.dumps(t["items"], ensure_ascii=False), _j.dumps(qs, ensure_ascii=False)))
            created += 1
        audit(db, user["id"], "convocatorias_de_ejemplo", "empresa", company_id, f"{created} creadas")
    return go(request, "/admin/users", f"Se crearon {created} convocatorias de ejemplo y quedaron publicadas en el portal." if created else "Esa empresa ya tiene las convocatorias de ejemplo.")

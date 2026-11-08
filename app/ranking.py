"""Ranking de una convocatoria: decoración de candidatos, top N, cierre automático, descargas y métricas."""
import datetime as dt
import io
import json
import os
import re
import unicodedata
import zipfile

from .db import audit

MIN_PER_CV = float(os.getenv("MIN_POR_CV", "5"))   # supuesto: minutos de revisión manual por CV


def today_pe() -> str:
    """Fecha de hoy en Perú (UTC-5), en formato AAAA-MM-DD."""
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).strftime("%Y-%m-%d")


def knock_fail(answers: list[dict]) -> bool:
    return any(a.get("mandatory") and a.get("answer") != "Sí" for a in answers)


def decorate(rows, v: dict) -> list[dict]:
    """Agrega a cada candidato su perfil, desglose, respuestas, si cumple los excluyentes y si está en el top N."""
    out = []
    for c in rows:
        d = dict(c)
        d["profile"] = json.loads(c["profile_json"]) if c["profile_json"] else {}
        d["sc"] = json.loads(c["breakdown_json"]) if c["breakdown_json"] else {}
        d["answers"] = json.loads(c["answers_json"]) if c["answers_json"] else []
        d["knock_fail"] = knock_fail(d["answers"])
        d["eligible"] = (c["score"] is not None and d["sc"].get("meets_mandatory", True) and not d["knock_fail"] and not c["reject_reason"])
        d["has_file"] = c["original_file"] is not None if "original_file" in c.keys() else False
        d["rubric"] = json.loads(c["rubric_json"]) if c["rubric_json"] else {}
        d["in_top"] = False
        out.append(d)
    n = int(v.get("top_n") or 5)
    rank = [d for d in sorted(out, key=lambda x: (x["score"] is None, -(x["score"] or 0), x["id"])) if d["eligible"]]
    for d in rank[:n]:
        d["in_top"] = True
    return sorted(out, key=lambda x: (x["score"] is None, -(x["score"] or 0), x["id"]))


def purge_originals(db, vid: int, keep_shortlisted: bool = True) -> int:
    """Borra los archivos originales de una convocatoria (conserva los de la lista corta si se pide)."""
    sql = "UPDATE candidates SET original_file=NULL WHERE vacancy_id=? AND original_file IS NOT NULL"
    if keep_shortlisted:
        sql += " AND shortlisted=0"
    return db.execute(sql, (vid,)).rowcount


def close_expired(db) -> int:
    """Cierra las convocatorias cuya fecha límite ya pasó y borra los archivos originales de quienes no fueron seleccionados."""
    rows = db.execute("SELECT id FROM vacancies WHERE status='abierta' AND closing_date IS NOT NULL AND closing_date<>'' AND closing_date<?",
                      (today_pe(),)).fetchall()
    for r in rows:
        db.execute("UPDATE vacancies SET status='cerrada' WHERE id=?", (r["id"],))
        purge_originals(db, r["id"])
        audit(db, None, "convocatoria_cerrada_por_fecha", "vacante", r["id"])
    return len(rows)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "candidato").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "candidato"


def build_zip(cands: list[dict], v: dict) -> bytes:
    """ZIP con los CV originales de los candidatos indicados y un Excel de resumen."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Posición", "Nombre", "Correo", "Teléfono", "Distrito", "Puntaje", "Cumple excluyentes", "Requisitos cumplidos", "Faltantes",
               "Años de experiencia", "Formación", "Última experiencia", "Respuestas", "Explicación del agente"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, c in enumerate(cands, 1):
            prof, sc = c["profile"], c["sc"]
            ws.append([i, c["applicant_name"] or c["filename"], c["applicant_email"] or "", c["applicant_phone"] or "", c["applicant_district"] or "",
                       c["score"], "Sí" if c["eligible"] else "No", "; ".join(prof.get("must_found", []) + prof.get("nice_found", [])),
                       "; ".join(sc.get("must_missing", [])), prof.get("years", ""), prof.get("education", ""),
                       " · ".join(x for x in [c["exp_role"], c["exp_company"], c["exp_time"]] if x),
                       "; ".join(f"{a['text']} {a['answer']}" for a in c["answers"]), c["explanation"] or ""])
            if c["original_file"] is not None:
                ext = os.path.splitext(c["filename"])[1].lower() or ".pdf"
                z.writestr(f"{i:02d}_{_slug(c['applicant_name'] or c['filename'])}{ext}", bytes(c["original_file"]))
        for col, w in zip("ABCDEFGHIJKLMN", [9, 28, 28, 14, 18, 10, 12, 40, 28, 12, 18, 40, 40, 70]):
            ws.column_dimensions[col].width = w
        xl = io.BytesIO()
        wb.save(xl)
        z.writestr(f"Resumen_{_slug(v['title'])}.xlsx", xl.getvalue())
    return buf.getvalue()


def to_dt(x):
    if isinstance(x, dt.datetime):
        return x
    try:
        return dt.datetime.fromisoformat(str(x).replace("Z", ""))
    except ValueError:
        return None


def company_metrics(db, company_id: int) -> dict:
    """Beneficio medible: cuántos CV llegaron, cuántos se revisan a mano y cuánto tiempo se ahorra (con el supuesto de minutos por CV)."""
    rec = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.company_id=?", (company_id,)).fetchone()["n"]
    ev = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.company_id=? AND c.score IS NOT NULL", (company_id,)).fetchone()["n"]
    sel = db.execute("SELECT COUNT(*) AS n FROM candidates c JOIN vacancies v ON v.id=c.vacancy_id WHERE v.company_id=? AND c.shortlisted=1", (company_id,)).fetchone()["n"]
    manual = rec * MIN_PER_CV
    with_agent = sel * MIN_PER_CV
    days = None
    vs = db.execute("SELECT id FROM vacancies WHERE company_id=?", (company_id,)).fetchall()
    vals = []
    for v in vs:
        first = db.execute("SELECT MIN(created_at) AS t FROM candidates WHERE vacancy_id=?", (v["id"],)).fetchone()["t"]
        sent = db.execute("SELECT MIN(a.created_at) AS t FROM audit_log a JOIN candidates c ON c.id=a.entity_id "
                          "WHERE a.action='candidato_enviado' AND c.vacancy_id=?", (v["id"],)).fetchone()["t"]
        a, b = to_dt(first), to_dt(sent)
        if a and b:
            vals.append(max((b - a).total_seconds() / 86400, 0))
    if vals:
        days = round(sum(vals) / len(vals), 1)
    return {"recibidas": rec, "evaluadas": ev, "seleccionadas": sel, "horas_manual": round(manual / 60, 1), "horas_agente": round(with_agent / 60, 1),
            "horas_ahorro": round(max(manual - with_agent, 0) / 60, 1), "min_por_cv": MIN_PER_CV, "dias_hasta_lista": days}

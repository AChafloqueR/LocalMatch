"""Orquesta las skills del agente: anonimizar -> extraer -> puntuar -> explicar."""
import json

from ..db import get_db
from .explain import explain
from .extract import extract_profile
from .score import score_candidate
from .textutil import split_terms, tfidf_cosine


def vacancy_dict(row) -> dict:
    d = dict(row)
    d["must_list"], d["nice_list"] = split_terms(d["must"]), split_terms(d["nice"])
    return d


def run_agent(vacancy_id: int) -> int:
    with get_db() as db:
        vac = vacancy_dict(db.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone())
        cands = db.execute("SELECT id, redacted_text FROM candidates WHERE vacancy_id=?", (vacancy_id,)).fetchall()
        query = f"{vac['title']} {vac['description']} {vac['must']} {vac['nice']}"
        sims = tfidf_cosine(query, [c["redacted_text"] for c in cands])
        for c, sim in zip(cands, sims):
            prof = extract_profile(c["redacted_text"], vac["must_list"], vac["nice_list"])
            sc = score_candidate(vac, prof, sim)
            db.execute(
                "UPDATE candidates SET profile_json=?, score=?, breakdown_json=?, explanation=? WHERE id=?",
                (json.dumps(prof, ensure_ascii=False), sc["total"], json.dumps(sc, ensure_ascii=False),
                 explain(vac, prof, sc), c["id"]),
            )
        return len(cands)

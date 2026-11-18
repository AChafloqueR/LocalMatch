"""Orquesta las skills del agente: anonimizar -> extraer -> puntuar -> explicar."""
import hashlib
import json
import time
from .. import llm, reqs
from ..db import get_db
from .redact import redact
from .explain import explain
from .extract import extract_profile
from .score import score_candidate
from .textutil import tfidf_cosine

# Cache simple en memoria para evitar reprocesar los mismos CVs en la misma sesión
_cached_profiles: dict = {}


def _content_hash(text: str) -> str:
    """Hash estable del contenido original (antes de redactar)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _cache_key(content_hash: str, items_hash: str) -> str:
    return f"profile:{content_hash}:{items_hash}"


def _is_redacted(text: str) -> bool:
    """Detecta si el texto ya fue anonimizado (busca marcadores)."""
    return "[correo]" in text or "[telefono]" in text or "[documento]" in text or "[dato personal omitido]" in text


def vacancy_dict(row) -> dict:
    d = dict(row)
    d["items"] = reqs.items_from_row(d)
    d["must_list"] = [i["name"] for i in d["items"] if i["mandatory"]]
    d["nice_list"] = [i["name"] for i in d["items"] if not i["mandatory"]]
    return d


def _items_hash(items: list) -> str:
    """Hash simple de los items para detectar cambios de vacante."""
    return "|".join(sorted(i["name"] for i in items))


def run_agent(vacancy_id: int) -> dict:
    """Ejecutar agente de preselección y ranking.
    
    Returns dict con reporte: {n_candidates, n_processed, skipped_reasons}
    """
    start = time.time()
    with get_db() as db:
        vac = vacancy_dict(db.execute("SELECT * FROM vacancies WHERE id=?", (vacancy_id,)).fetchone())
        items_h = _items_hash(vac["items"])
        # Traer también cv_hash y original_file para hash estable
        cands = db.execute(
            "SELECT id, redacted_text, filename, original_file, cv_hash FROM candidates WHERE vacancy_id=?",
            (vacancy_id,)
        ).fetchall()
        
        redacted_texts = []
        content_hashes = []
        
        for c in cands:
            raw = c["redacted_text"]
            
            # Hash estable: usa cv_hash si existe, sino hash del texto crudo actual
            if c["cv_hash"]:
                chash = c["cv_hash"][:16]
            else:
                chash = _content_hash(raw)
                # Guardar hash para próximas corridas (evita recalcular)
                db.execute("UPDATE candidates SET cv_hash=? WHERE id=?", (chash, c["id"]))
            content_hashes.append(chash)
            
            # Redactar solo si no está ya redactado
            if _is_redacted(raw):
                redacted = raw
            else:
                redacted = redact(raw)
                db.execute("UPDATE candidates SET redacted_text=? WHERE id=?", (redacted, c["id"]))
            redacted_texts.append(redacted)
        
        # Construir query TF-IDF una sola vez por vacante
        query = f"{vac['title']} {vac['description']} " + " ".join(i["name"] for i in vac["items"])
        sims = tfidf_cosine(query, redacted_texts)
        
        n_processed = 0
        n_candidates = len(cands)
        skipped = []
        
        for c, sim, chash in zip(cands, sims, content_hashes):
            c_key = _cache_key(chash, items_h)
            
            # Reutilizar perfil en caché si el contenido original e items son iguales
            if c_key in _cached_profiles:
                prof = _cached_profiles[c_key]
                use_cache = True
            else:
                prof = extract_profile(redacted_texts[n_processed], vac["items"], use_llm=llm.provider() != "mock")
                _cached_profiles[c_key] = prof
                use_cache = False
            
            sc = score_candidate(vac, prof, sim)
            
            db.execute(
                "UPDATE candidates SET profile_json=?, score=?, breakdown_json=?, explanation=? WHERE id=?",
                (json.dumps(prof, ensure_ascii=False), sc["total"], json.dumps(sc, ensure_ascii=False),
                 explain(vac, prof, sc), c["id"]),
            )
            n_processed += 1
        
        elapsed = time.time() - start
        
        return {
            "n_candidates": n_candidates,
            "n_processed": n_processed,
            "elapsed_seconds": round(elapsed, 2),
            "used_cache": len(_cached_profiles),
            "skipped": skipped,
        }


def clear_profile_cache() -> None:
    """Limpiar cache de perfiles (útil después de cambios de requisitos)."""
    global _cached_profiles
    _cached_profiles = {}


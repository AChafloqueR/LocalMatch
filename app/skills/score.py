"""Skill 3 · Puntuar: puntaje transparente 0-100 (el LLM no decide el puntaje)."""
WEIGHTS = {"must": 0.50, "nice": 0.15, "exp": 0.20, "sem": 0.15}


def _coverage(items: list[dict], found: list[str]) -> float:
    total = sum(i["weight"] for i in items)
    if not total:
        return 1.0
    return sum(i["weight"] for i in items if i["name"] in found) / total


def score_candidate(vac: dict, profile: dict, semantic: float) -> dict:
    """Calcular puntuación 0-100 para un candidato.
    
    Fórmula determinista: no usa LLM. Perfecto para 8GB VRAM.
    
    Args:
        vac: Datos de la vacante
        profile: Perfil extraído del CV
        semantic: Similitud semántica TF-IDF (0-1)
    """
    items = vac["items"]
    must_items = [i for i in items if i["mandatory"]]
    nice_items = [i for i in items if not i["mandatory"]]
    must_cov = _coverage(must_items, profile["must_found"])
    nice_cov = _coverage(nice_items, profile["nice_found"])
    
    # Experiencia: normalizada pero con teto suave para evitar división por cero
    min_years = float(vac.get("min_years") or 0)
    if min_years > 0:
        exp = min(profile["years"] / min_years, 1.0)
    elif profile["years"] >= min_years:  # min_years == 0 y tiene experiencia
        exp = min(profile["years"] / 40, 1.0)  # Asumir max 40 años
    else:
        exp = 0.0
    
    # Semántica: 0.35 es el umbral TF-IDF donde la coincidencia es alta
    # Con 8GB VRAM usamos este valor fijo en lugar de modelos de embedding pesados
    sem = min(semantic / 0.35, 1.0) if semantic else 0.0
    
    parts = {"must": must_cov, "nice": nice_cov, "exp": exp, "sem": sem}
    total = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()), 1)
    missing = [i["name"] for i in must_items if i["name"] not in profile["must_found"]]
    return {
        "total": total,
        "parts": {k: round(v * 100, 1) for k, v in parts.items()},
        "weights": WEIGHTS,
        "must_missing": missing,
        "meets_mandatory": not missing,
        "semantic_raw": round(semantic, 3),
        "exp_years": round(profile["years"], 1) if profile["years"] else 0.0,
    }

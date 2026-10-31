"""Skill 3 · Puntuar: puntaje transparente 0-100 (el LLM no decide el puntaje)."""
WEIGHTS = {"must": 0.50, "nice": 0.15, "exp": 0.20, "sem": 0.15}


def score_candidate(vac: dict, profile: dict, semantic: float) -> dict:
    must, nice = vac["must_list"], vac["nice_list"]
    must_cov = len(profile["must_found"]) / len(must) if must else 1.0
    nice_cov = len(profile["nice_found"]) / len(nice) if nice else 1.0
    min_years = float(vac.get("min_years") or 0)
    exp = min(profile["years"] / min_years, 1.0) if min_years > 0 else 1.0
    sem = min(semantic / 0.35, 1.0)  # 0.35 de coseno TF-IDF ~ coincidencia alta
    parts = {"must": must_cov, "nice": nice_cov, "exp": exp, "sem": sem}
    total = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()), 1)
    return {
        "total": total,
        "parts": {k: round(v * 100, 1) for k, v in parts.items()},
        "weights": WEIGHTS,
        "must_missing": [t for t in must if t not in profile["must_found"]],
        "semantic_raw": round(semantic, 3),
    }

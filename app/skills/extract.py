"""Skill 2 · Extraer perfil: competencias, experiencia y formación del CV."""
import datetime
import re

from .. import llm
from .textutil import has_term, norm

EDU = [
    ("doctorad", "Doctorado"), ("maestr", "Maestría"), ("ingenier", "Ingeniería"),
    ("licenciad", "Licenciatura"), ("bachiller", "Bachiller"), ("tecnic", "Técnico"),
    ("universit", "Universitario"),
]


def years_of_experience(text: str) -> tuple[float, str]:
    n = norm(text)
    m = [int(x) for x in re.findall(r"(\d{1,2})\s*\+?\s*(?:anos|years)", n)]
    if m:
        return float(max(m)), "declarada"
    now = datetime.date.today().year
    ys = [int(y) for y in re.findall(r"\b(19[9]\d|20[0-4]\d)\b", text) if int(y) <= now]
    if len(ys) >= 2:
        return float(min(max(ys) - min(ys), 40)), "estimada por fechas"
    return 0.0, "no detectada"


def education(text: str) -> str:
    n = norm(text)
    for key, label in EDU:
        if key in n:
            return label
    return "No detectada"


def snippet(text: str, term: str, width: int = 70) -> str:
    n = norm(text)
    i = n.find(norm(term))
    if i < 0:
        return ""
    a, b = max(0, i - width // 2), min(len(text), i + len(term) + width // 2)
    return "…" + " ".join(text[a:b].split()) + "…"


def matched_term(n: str, item: dict) -> str | None:
    """Devuelve el término (nombre o sinónimo) del requisito que aparece en el texto normalizado."""
    for t in [item["name"], *item.get("synonyms", [])]:
        if has_term(n, t):
            return t
    return None


def extract_profile(text: str, items: list[dict], use_llm: bool | None = None) -> dict:
    """Extraer perfil de CV.
    
    Args:
        text: Texto del CV anonimizado
        items: Requisitos de la vacante
        use_llm: Si usar LLM. None = auto (usar si modelo disponible y rápido)
    """
    n = norm(text)
    hits = {it["name"]: matched_term(n, it) for it in items}
    must = [i["name"] for i in items if i["mandatory"]]
    nice = [i["name"] for i in items if not i["mandatory"]]
    years, how = years_of_experience(text)
    
    # Perfil base con reglas (regex)
    profile = {
        "must_found": [m for m in must if hits[m]],
        "nice_found": [m for m in nice if hits[m]],
        "years": years,
        "years_how": how,
        "education": education(text),
        "method": "reglas",
    }
    
    # Usar LLM solo si está explícitamente pedido y no es mock
    if use_llm is None:
        use_llm = llm.provider() != "mock" and llm.complete("Resume este texto en 3 palabras clave máximo.") is not None
    
    if use_llm:
        data = llm.complete_json(
            f"REQUISITOS OBLIGATORIOS: {must}\nREQUISITOS DESEABLES: {nice}\n\nCV:\n{text[:5000]}",
            "Eres un asistente de selección de personal. Lee el CV anonimizado y responde SOLO un JSON con:\n"
            '{"must_found": [...], "nice_found": [...], "years": número, "education": "texto"}\n'
            "Solo incluye requisitos de la lista que el CV evidencie claramente. Responde únicamente con JSON válido."
        )
        if data and isinstance(data.get("years"), (int, float)) and data["years"] > 0:
            years = float(data["years"])
            how = "interpretada por modelo"
        if data:
            # Merge LLM results with regex results (union)
            profile["must_found"] = sorted(set(profile["must_found"]) | set([t for t in data.get("must_found", []) if t in must]))
            profile["nice_found"] = sorted(set(profile["nice_found"]) | set([t for t in data.get("nice_found", []) if t in nice]))
            profile["years"] = years
            profile["years_how"] = how
            profile["education"] = (str(data.get("education"))[:60] if data.get("education") else "")
            profile["method"] = f"LLM ({llm.provider()}) + reglas"
        else:
            profile["method"] = "reglas (fallback LLM fallido)"
    
    profile["evidence"] = {t: snippet(text, hits.get(t) or t) for t in profile["must_found"] + profile["nice_found"]}
    return profile

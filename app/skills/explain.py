"""Skill 4 · Explicar: justificación en lenguaje claro para el jefe de área."""
from .. import llm


def explain(vac: dict, profile: dict, sc: dict) -> str:
    must_n = len(vac["must_list"])
    base = (
        f"Cumple {len(profile['must_found'])} de {must_n} requisitos obligatorios"
        + (f" ({', '.join(profile['must_found'])})" if profile["must_found"] else "")
        + ". "
    )
    if sc["must_missing"]:
        base += f"No se evidenció: {', '.join(sc['must_missing'])}. "
    if profile["nice_found"]:
        base += f"Aporta además: {', '.join(profile['nice_found'])}. "
    mn = vac.get("min_years") or 0
    base += f"Experiencia {profile['years_how']}: {profile['years']:.0f} año(s)" + (f" (mínimo pedido: {mn:g})." if mn else ".")
    base += f" Formación: {profile['education']}."
    if llm.provider() != "mock":
        text = llm.complete(
            "Redacta en español, en 2 o 3 oraciones, por qué este candidato obtuvo el puntaje indicado. "
            "Usa solo los datos dados, sin inventar ni mencionar género, edad o nombre.\n"
            f"Puesto: {vac['title']}\nPuntaje: {sc['total']}/100\nDatos: {base}",
            system="Eres un asistente claro y neutral para jefes de área.",
        )
        if text:
            return text.strip()
    return base

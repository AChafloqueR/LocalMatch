"""Requisitos de una convocatoria: herramientas, formación, certificaciones e idiomas, con peso, carácter excluyente y sinónimos."""
import json
import re

from .catalog import KINDS
from .skills.textutil import split_terms


MAX_ITEMS, MAX_QUESTIONS = 10, 3
def valid_phone(s: str) -> bool:
    """Celular peruano: exactamente 9 dígitos y empieza con 9."""
    return bool(re.compile(r"^9\d{8}$").match(s or ""))


def items_from_row(v) -> list[dict]:
    """Requisitos de la vacante; si es una vacante antigua, se derivan de las listas de obligatorios y deseables."""
    if v["requirements_json"]:
        return json.loads(v["requirements_json"])
    out = [{"name": n, "kind": "herramienta", "weight": 3, "mandatory": True, "synonyms": []} for n in split_terms(v["must"])]
    out += [{"name": n, "kind": "herramienta", "weight": 2, "mandatory": False, "synonyms": []} for n in split_terms(v["nice"])]
    return out


def questions_from_row(v) -> list[dict]:
    return json.loads(v["questions_json"]) if v["questions_json"] else []


def items_from_form(form) -> list[dict]:
    """Lee todos los campos rq_name_*, rq_kind_*, rq_weight_*, rq_mand_*, rq_syn_* del formulario.
    
    Soporta campos dinámicos (más de 10) y mantiene compatibilidad con el formulario anterior
    que usaba los campos must/nice.
    """
    items = []
    # Leer todos los campos de requisitos (rq_name_N donde N puede ser cualquier número)
    # Buscamos patrones como rq_name_1, rq_name_2, etc.
    i = 1
    while True:
        name = " ".join(str(form.get(f"rq_name_{i}", "")).split())[:60]
        if not name and i > 1:
            # Si ya no hay nombre y no es el primero, parar
            break
        if name:
            kind = form.get(f"rq_kind_{i}", "herramienta")
            try:
                weight = min(max(int(form.get(f"rq_weight_{i}", 3)), 1), 5)
            except ValueError:
                weight = 3
            items.append({
                "name": name,
                "kind": kind if kind in KINDS else "herramienta",
                "weight": weight,
                "mandatory": bool(form.get(f"rq_mand_{i}")),
                "synonyms": [s.strip()[:40] for s in str(form.get(f"rq_syn_{i}", "")).split(",") if s.strip()][:6]
            })
        i += 1

    # Si no hay items, intentar con los campos antiguos must/nice
    if not items:
        must = str(form.get("must", ""))
        nice = str(form.get("nice", ""))
        if must or nice:
            items = [{"name": n, "kind": "herramienta", "weight": 3, "mandatory": True, "synonyms": []} for n in split_terms(must)]
            items += [{"name": n, "kind": "herramienta", "weight": 2, "mandatory": False, "synonyms": []} for n in split_terms(nice)]

    return items


def questions_from_form(form) -> list[dict]:
    """Lee todos los campos q_text_* del formulario, soportando campos dinámicos."""
    out = []
    i = 1
    while True:
        t = " ".join(str(form.get(f"q_text_{i}", "")).split())[:120]
        if not t and i > 1:
            break
        if t:
            out.append({"text": t, "mandatory": bool(form.get(f"q_mand_{i}"))})
        i += 1

    return out


def legacy_lists(items: list[dict]) -> tuple[str, str]:
    """Mantiene las columnas must y nice sincronizadas con los requisitos."""
    return ", ".join(i["name"] for i in items if i["mandatory"]), ", ".join(i["name"] for i in items if not i["mandatory"])


def pad_rows(items: list[dict]) -> list[dict]:
    """Ajusta la lista de items a como máximo 10 para el template, agregando campos vacíos."""
    rows = list(items)[:MAX_ITEMS]
    while len(rows) < MAX_ITEMS:
        rows.append({"name": "", "kind": "herramienta", "weight": 3, "mandatory": False, "synonyms": []})
    return rows


def pad_questions(qs: list[dict]) -> list[dict]:
    """Ajusta la lista de preguntas a como máximo 3 para el template, agregando campos vacíos."""
    rows = list(qs)[:MAX_QUESTIONS]
    while len(rows) < MAX_QUESTIONS:
        rows.append({"text": "", "mandatory": False})
    return rows
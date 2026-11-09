"""Departamentos, provincias y distritos del Perú (UBIGEO, dominio público CC0)."""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "static", "ubigeo.json")
DATA = json.load(open(_PATH, encoding="utf-8"))
_INDEX = {d["n"]: {p["n"]: set(p["d"]) for p in d["p"]} for d in DATA}


def valid(dept: str, prov: str, dist: str) -> bool:
    return dist in _INDEX.get(dept, {}).get(prov, set())


def label(dept: str, prov: str, dist: str) -> str:
    return f"{dist}, {prov}, {dept}"

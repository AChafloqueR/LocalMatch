import statistics

ITEMS = [
    "Creo que me gustaría utilizar este sistema con frecuencia.",
    "Encontré el sistema innecesariamente complejo.",
    "Pensé que el sistema era fácil de usar.",
    "Creo que necesitaría el apoyo de un técnico para poder utilizar este sistema.",
    "Encontré que las diversas funciones de este sistema estaban bien integradas.",
    "Pensé que había demasiada inconsistencia en este sistema.",
    "Imagino que la mayoría de las personas aprendería a utilizar este sistema rápidamente.",
    "Encontré el sistema muy incómodo de usar.",
    "Me sentí muy seguro(a) utilizando el sistema.",
    "Necesité aprender muchas cosas antes de poder continuar con este sistema.",
]


def sus_score(answers: list[int]) -> float:
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        raise ValueError("El SUS requiere 10 respuestas entre 1 y 5.")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))  # ítems 1,3,5,7,9 son índices pares
    return total * 2.5


def category(score: float) -> str:
    if score > 80.3:
        return "Excelente"
    if score >= 68:
        return "Bueno"
    if score >= 51:
        return "Marginal"
    return "No aceptable"


def describe(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {
        "n": len(scores),
        "mean": round(statistics.mean(scores), 1),
        "sd": round(statistics.stdev(scores), 1) if len(scores) > 1 else 0.0,
        "min": min(scores),
        "max": max(scores),
    }

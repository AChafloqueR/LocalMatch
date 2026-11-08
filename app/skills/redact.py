"""Skill 1 · Anonimizar: quita datos que no deben influir en la preselección."""
import re

PATTERNS = [
    (r"[\w.+-]+@[\w-]+\.[\w.-]+", "[correo]"),
    (r"(?<!\d)(?:\+?51[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?!\d)", "[telefono]"),
    (r"(?<!\d)\d{8}(?!\d)", "[documento]"),
    (r"(?i)https?://\S+|www\.\S+", "[enlace]"),
]
SENSITIVE_LINE = re.compile(
    r"(?i)^\s*(edad|sexo|genero|género|estado civil|fecha de nacimiento|nacionalidad|dni|religi[oó]n)\b.*$", re.M
)


def redact(text: str, strip_first_line: bool = True) -> str:
    lines = text.strip().splitlines()
    # El nombre suele estar en la primera línea: se elimina si parece un nombre.
    if lines and strip_first_line:
        first = lines[0].strip()
        if 0 < len(first) <= 45 and not re.search(r"\d|@", first) and len(first.split()) <= 5:
            lines = lines[1:]
    out = "\n".join(lines)
    out = SENSITIVE_LINE.sub("[dato personal omitido]", out)
    for pat, repl in PATTERNS:
        out = re.sub(pat, repl, out)
    return out

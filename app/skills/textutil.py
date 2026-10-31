import math
import re
import unicodedata
from collections import Counter


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def split_terms(raw: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\n;]+", raw or "") if t.strip()]


def has_term(norm_text: str, term: str) -> bool:
    t = re.escape(norm(term).strip())
    return re.search(rf"(?<![a-z0-9]){t}(?![a-z0-9])", norm_text) is not None


STOP = set("""de la el en y a los las del se por con para un una que es al lo su sus como mas o e
este esta estos estas ha han ser son fue muy sin sobre entre tambien the and of to in for with""".split())


def tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+#.]{2,}", norm(s)) if w not in STOP]


def tfidf_cosine(query: str, docs: list[str]) -> list[float]:
    """Similitud coseno TF-IDF entre `query` y cada documento (sin librerías externas)."""
    corpus = [tokens(query)] + [tokens(d) for d in docs]
    n = len(corpus)
    df = Counter()
    for toks in corpus:
        df.update(set(toks))
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}

    def vec(toks):
        tf = Counter(toks)
        return {w: (c / max(len(toks), 1)) * idf[w] for w, c in tf.items()}

    def cos(a, b):
        dot = sum(a[w] * b.get(w, 0) for w in a)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    q = vec(corpus[0])
    return [cos(q, vec(t)) for t in corpus[1:]]

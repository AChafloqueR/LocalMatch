import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.sus import category, sus_score


def test_sus_ejemplo_de_la_diapositiva():
    # Diapositiva del curso: suma 31 -> 31 x 2.5 = 77.5 puntos
    assert sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 1]) == 77.5
    assert sus_score([5, 1] * 5) == 100.0
    assert sus_score([1, 5] * 5) == 0.0
    assert sus_score([4, 3, 4, 3, 4, 3, 4, 3, 4, 3]) == 62.5


def test_categorias():
    assert category(85) == "Excelente" and category(75) == "Bueno"
    assert category(60) == "Marginal" and category(40) == "No aceptable"


def test_sus_valida_entrada():
    with pytest.raises(ValueError):
        sus_score([1, 2, 3])


@pytest.fixture()
def client(monkeypatch):
    # Con DATABASE_URL usa PostgreSQL (CI); si no, un SQLite temporal.
    if not os.getenv("DATABASE_URL"):
        monkeypatch.setenv("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from app.auth import hash_password
    from app.db import get_db, init_db, reset_db
    from app.main import app

    init_db()
    reset_db()
    with get_db() as db:
        for e, n, r in [("r@t.l", "Rosa Rec", "reclutador"), ("j@t.l", "Julio Jefe", "jefe"), ("a@t.l", "Admin", "admin")]:
            db.execute("INSERT INTO users(email,name,role,pw_hash) VALUES(?,?,?,?)", (e, n, r, hash_password("pw12345")))
    return TestClient(app)


def login(c, email):
    r = c.post("/login", data={"email": email, "password": "pw12345"}, follow_redirects=False)
    assert r.status_code == 303


def test_flujo_completo(client):
    c = client
    login(c, "r@t.l")
    boss_id = 2
    r = c.post("/vacancies/new", data=dict(title="Analista", area="Ops", description="Reportes de ventas",
                                           must="SQL, Excel, Power BI", nice="Python", min_years=1, boss_id=boss_id),
               follow_redirects=False)
    vid = int(r.headers["location"].split("/")[-1])
    files = []
    for f in sorted(os.listdir("samples")):
        files.append(("files", (f, open(f"samples/{f}", "rb"), "text/plain")))
    assert c.post(f"/vacancies/{vid}/upload", files=files, follow_redirects=False).status_code == 303
    assert c.post(f"/vacancies/{vid}/run", follow_redirects=False).status_code == 303

    from app.db import get_db
    with get_db() as db:
        rows = db.execute("SELECT filename,score,redacted_text FROM candidates ORDER BY score DESC").fetchall()
    assert rows[0]["filename"] in ("cv_ana.txt", "cv_mia.txt")      # los que cumplen SQL+Excel+Power BI
    assert rows[-1]["filename"] in ("cv_jorge.txt", "cv_luis.txt")  # los menos afines
    assert all("@" not in r["redacted_text"] and "987 654" not in r["redacted_text"] for r in rows)
    assert "Ana Torres" not in "".join(r["redacted_text"] for r in rows)  # nombre omitido

    page = c.get(f"/vacancies/{vid}")
    assert page.status_code == 200 and "Candidato #" in page.text

    with get_db() as db:
        cid = db.execute("SELECT id FROM candidates ORDER BY score DESC LIMIT 1").fetchone()["id"]
    c.post(f"/candidates/{cid}/shortlist")

    # el jefe solo ve lo enviado y decide
    c.post("/logout")
    login(c, "j@t.l")
    s = c.get(f"/shortlists/{vid}")
    assert s.status_code == 200 and f"Candidato #{cid}" in s.text and "cv_" not in s.text  # anonimizado
    assert c.post(f"/candidates/{cid}/decision", data={"decision": "Entrevistar"}, follow_redirects=False).status_code == 303
    assert c.get("/vacancies/new").status_code == 403  # perfiles diferenciados


def test_sus_y_admin(client):
    c = client
    login(c, "r@t.l")
    data = {f"q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
    c.post("/sus", data=data)                       # sin consentimiento: no guarda
    assert c.post("/sus", data={**data, "consent": "1"}, follow_redirects=False).status_code == 303
    c.post("/sus", data={**data, "consent": "1"})   # duplicado: ignorado
    c.post("/logout")
    login(c, "a@t.l")
    csv = c.get("/admin/sus.csv").text
    assert csv.count("\n") == 2 and "Personal de reclutamiento" in csv and "P001" in csv
    assert "75.0" in csv
    assert c.get("/admin/sus").status_code == 200


def test_acceso_sin_login(client):
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_admin_crea_participantes(client):
    c = client
    login(c, "a@t.l")
    r = c.post("/admin/users/bulk", data={"role": "jefe", "count": 3})
    assert r.status_code == 200 and r.text.count("\n") == 4 and "jef01@localmatch.local" in r.text
    again = c.post("/admin/users/bulk", data={"role": "jefe", "count": 3})
    assert again.text.count("\n") == 1  # ya existían: solo el encabezado
    one = c.post("/admin/users/one", data={"email": "x@y.z", "name": "Ana", "role": "reclutador"})
    assert one.status_code == 200 and "Cuenta creada" in one.text
    c.post("/logout")
    login(c, "r@t.l")
    assert c.get("/admin/users").status_code == 403

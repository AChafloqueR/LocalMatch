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
        cid = db.insert("INSERT INTO companies(name) VALUES(?)", ("Empresa Test",))
        for e, n, r in [("r@t.l", "Rosa Rec", "reclutador"), ("j@t.l", "Julio Jefe", "jefe"), ("a@t.l", "Admin", "admin")]:
            db.execute("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)",
                       (e, n, r, hash_password("pw12345"), None if r == "admin" else cid))
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
    assert c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"}, follow_redirects=False).status_code == 303
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


def test_sus_y_admin(client, monkeypatch):
    monkeypatch.setenv("SUS_REQUIRE_TASK", "0")
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
    r = c.post("/admin/users/bulk", data={"role": "jefe", "count": 3, "company_id": 1})
    assert r.status_code == 200 and r.text.count("\n") == 4 and "jef01-e1@localmatch.local" in r.text
    again = c.post("/admin/users/bulk", data={"role": "jefe", "count": 3, "company_id": 1})
    assert again.text.count("\n") == 1  # ya existían: solo el encabezado
    one = c.post("/admin/users/one", data={"email": "x@y.z", "name": "Ana", "role": "reclutador", "company_id": 1})
    assert one.status_code == 200 and "Cuenta creada" in one.text
    c.post("/logout")
    login(c, "r@t.l")
    assert c.get("/admin/users").status_code == 403


def _nueva_vacante(c, boss_id=2, published=False):
    data = dict(title="Analista", area="Ops", description="Reportes de ventas", must="SQL, Excel, Power BI", nice="Python", min_years=1, boss_id=boss_id)
    if published:
        data["published"] = "1"
    r = c.post("/vacancies/new", data=data, follow_redirects=False)
    return int(r.headers["location"].split("/")[-1])


def _subir(c, vid, consent=True, n=3):
    files = [("files", (f"cv{i}.txt", f"Persona {i}\nAnalista con SQL y Excel {i} anos de experiencia en reportes de ventas.".encode(), "text/plain")) for i in range(n)]
    return c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"} if consent else {}, follow_redirects=True)


def test_consentimiento_obligatorio(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c)
    page = _subir(c, vid, consent=False)
    assert "Debes declarar" in page.text
    from app.db import get_db
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"] == 0
    assert "3 CV cargado" in _subir(c, vid).text


def test_editar_y_cerrar_vacante(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c)
    c.post(f"/vacancies/{vid}/edit", data=dict(title="Analista Senior", area="Ops", description="x", must="SQL", nice="", min_years=2, boss_id=2))
    assert "Analista Senior" in c.get(f"/vacancies/{vid}").text
    c.post(f"/vacancies/{vid}/toggle-status")
    assert "Cerrada" in c.get(f"/vacancies/{vid}").text
    assert "vacante está cerrada" in _subir(c, vid).text
    c.post(f"/vacancies/{vid}/toggle-status")
    assert "3 CV cargado" in _subir(c, vid).text


def test_exportar_ranking_csv(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c); _subir(c, vid)
    c.post(f"/vacancies/{vid}/run")
    r = c.get(f"/vacancies/{vid}/ranking.csv")
    assert r.status_code == 200 and r.text.startswith("posicion,candidato") and r.text.count("\n") == 4


def _tarea_reclutamiento(c, vid):
    _subir(c, vid); c.post(f"/vacancies/{vid}/run")
    from app.db import get_db
    with get_db() as db:
        cid = db.execute("SELECT id FROM candidates ORDER BY score DESC LIMIT 1").fetchone()["id"]
    c.post(f"/candidates/{cid}/shortlist")


def test_tarea_guiada_habilita_el_sus(client):
    c = client; login(c, "r@t.l")
    data = {f"q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
    assert "Primero completa tu tarea" in c.get("/sus").text
    c.post("/sus", data={**data, "consent": "1"})            # bloqueado: no registra
    from app.db import get_db
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sus_responses").fetchone()["n"] == 0
    vid = _nueva_vacante(c); _tarea_reclutamiento(c, vid)
    assert "Primero completa tu tarea" not in c.get("/sus").text
    c.post("/sus", data={**data, "consent": "1"})
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sus_responses").fetchone()["n"] == 1


def test_escenario_para_jefes(client):
    c = client; login(c, "a@t.l")
    page = c.post("/admin/scenario", follow_redirects=True)
    assert "Escenario preparado para 1 jefe" in page.text
    assert "Todos los jefes de área ya tienen su escenario" in c.post("/admin/scenario", follow_redirects=True).text
    c.post("/logout"); login(c, "j@t.l")
    dash = c.get("/dashboard").text
    assert "tarea del estudio" in dash.lower()
    from app.db import get_db
    with get_db() as db:
        v = db.execute("SELECT id FROM vacancies WHERE boss_id=2").fetchone()["id"]
        cid = db.execute("SELECT id FROM candidates WHERE vacancy_id=? AND shortlisted=1 ORDER BY score DESC", (v,)).fetchall()
    assert len(cid) == 5
    assert "Primero completa tu tarea" in c.get("/sus").text
    c.post(f"/candidates/{cid[0]['id']}/decision", data={"decision": "Entrevistar"})
    assert "Primero completa tu tarea" not in c.get("/sus").text


def test_auditoria_registra_acciones(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c); _subir(c, vid); c.post(f"/vacancies/{vid}/run")
    c.post("/logout"); login(c, "a@t.l")
    t = c.get("/admin/audit").text
    for accion in ("vacante_creada", "cv_cargados", "agente_ejecutado"):
        assert accion in t
    c.post("/logout"); login(c, "r@t.l")
    assert c.get("/admin/audit").status_code == 403


def test_rechaza_archivos_que_no_son_cv(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c)
    files = [("files", ("foto.png", b"\x89PNG\r\n" + b"x" * 200, "image/png")),
             ("files", ("cv.txt", b"Ana Perez\nAnalista con SQL y Excel. 3 anos de experiencia en reportes de ventas.", "text/plain"))]
    page = c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"}, follow_redirects=True)
    assert "1 CV cargado" in page.text and "1 no se pudieron leer" in page.text


CV_TXT = "Ana Perez\nAnalista de datos con SQL, Excel y Power BI. 4 anos de experiencia en reportes de ventas. Python.".encode()


def _postular(c, vid, email="ana@x.com", consent=True, fname="cv.txt", content=CV_TXT):
    data = {"name": "Ana Perez Soto", "email": email, "phone": "987654321"}
    if consent:
        data["consent"] = "1"
    return c.post(f"/empleos/{vid}/postular", data=data, files={"cv": (fname, content, "text/plain")}, follow_redirects=False)


def test_multiempresa_aislamiento(client):
    c = client
    from app.auth import hash_password
    from app.db import get_db
    with get_db() as db:
        c2 = db.insert("INSERT INTO companies(name) VALUES(?)", ("Otra Empresa",))
        db.execute("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)", ("r2@t.l", "Rec Dos", "reclutador", hash_password("pw12345"), c2))
    login(c, "r@t.l"); vid = _nueva_vacante(c); _subir(c, vid)
    c.post("/logout"); login(c, "r2@t.l")
    assert c.get(f"/vacancies/{vid}").status_code == 404           # no ve vacantes de otra empresa
    assert "Analista" not in c.get("/dashboard").text
    r = c.post("/vacancies/new", data=dict(title="X", area="Y", description="Z", must="SQL", nice="", min_years=0, boss_id=2))
    assert r.status_code == 400                                       # no puede asignar un jefe de otra empresa
    assert c.post("/candidates/1/delete").status_code == 404


def test_vacante_no_publicada_no_aparece_en_el_portal(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c)
    c.post("/logout")
    assert "Analista" not in c.get("/empleos").text
    assert c.get(f"/empleos/{vid}").status_code == 404


def test_flujo_del_postulante(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c, published=True)
    c.post("/logout")
    assert "Analista" in c.get("/empleos").text and c.get(f"/empleos/{vid}").status_code == 200
    r = _postular(c, vid, consent=False)
    assert r.status_code == 303 and r.headers["location"] == f"/empleos/{vid}"
    from app.db import get_db
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"] == 0
    r = _postular(c, vid)
    code = r.headers["location"].split("/")[-1]
    assert len(code) == 8
    estado = c.get(f"/postulacion/{code}").text
    assert "Evaluada por el equipo de selección" in estado and "Empresa Test" in estado
    assert "Puntaje" not in estado and "puntaje" not in estado
    # reclutamiento ve el contacto desde el inicio
    c.post("/login", data={"email": "r@t.l", "password": "pw12345"})
    page = c.get(f"/vacancies/{vid}").text
    assert "Ana Perez Soto" in page and "ana@x.com" in page and "987654321" in page and code in page
    with get_db() as db:
        row = db.execute("SELECT id, redacted_text, applicant_name FROM candidates").fetchone()
    assert "Ana Perez Soto" not in row["redacted_text"] and "Perez" not in row["redacted_text"]   # el texto evaluado va anonimizado
    c.post(f"/candidates/{row['id']}/shortlist")
    c.post("/logout"); login(c, "j@t.l")
    jefe = c.get(f"/shortlists/{vid}").text
    assert f"Candidato #{row['id']}" in jefe and "Ana Perez" not in jefe and "ana@x.com" not in jefe and "987654321" not in jefe
    c.post(f"/candidates/{row['id']}/decision", data={"decision": "Entrevistar"})
    c.post("/logout")
    assert "Seleccionado para entrevista" in c.get(f"/postulacion/{code}").text
    assert c.post(f"/postulacion/{code}/eliminar", follow_redirects=False).status_code == 303
    assert c.get(f"/postulacion/{code}").status_code == 404


def test_postulacion_duplicada_formato_y_vacante_cerrada(client):
    c = client; login(c, "r@t.l"); vid = _nueva_vacante(c, published=True); c.post("/logout")
    assert _postular(c, vid).status_code == 303
    dup = _postular(c, vid)
    from app.db import get_db
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"] == 1
    assert c.get("/empleos/%d" % vid).status_code == 200
    _postular(c, vid, email="b@x.com", fname="foto.png", content=b"\x89PNG" + b"x" * 100)
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"] == 1
    login(c, "r@t.l"); c.post(f"/vacancies/{vid}/toggle-status"); c.post("/logout")
    assert c.get(f"/empleos/{vid}").status_code == 404
    assert _postular(c, vid, email="c@x.com").status_code in (303, 404)


def test_consulta_de_codigo_inexistente(client):
    assert client.get("/postulacion/ZZZZZZZZ").status_code == 404
    assert client.get("/postulacion?code=zzzzzzzz", follow_redirects=False).headers["location"] == "/postulacion/ZZZZZZZZ"
    assert client.get("/", follow_redirects=False).headers["location"] == "/empleos"

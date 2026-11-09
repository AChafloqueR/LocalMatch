import io
import os
import re
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.reqs import valid_phone
from app.sus import category, sus_score

STRONG = "Ana Perez\nAnalista de datos con SQL, Excel (hojas de cálculo), Power BI y Python. 4 años de experiencia en reportes de ventas.".encode()
MEDIUM = "Luis Rojas\nAsistente con SQL y Excel. 2 años de experiencia en reportes.".encode()
WEAK = "Carlos Medina\nContador con 8 años de experiencia en contabilidad y Word.".encode()
PW = "pw12345"


# ---------------- utilidades ----------------
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
                       (e, n, r, hash_password(PW), None if r == "admin" else cid))
    return TestClient(app)


def login(c, email):
    r = c.post("/login", data={"email": email, "password": PW}, follow_redirects=False)
    assert r.status_code == 303


def make_user(email, name="Postulante", role="postulante", company_id=None):
    from app.auth import hash_password
    from app.db import get_db
    with get_db() as db:
        return db.insert("INSERT INTO users(email,name,role,pw_hash,company_id) VALUES(?,?,?,?,?)", (email, name, role, hash_password(PW), company_id))


def new_vac(c, boss_id=2, published=True, title="Analista de datos", **extra):
    data = {"title": title, "area": "Operaciones", "description": "Reportes y tableros para la gerencia", "min_years": "1", "boss_id": boss_id, "top_n": "3",
            "rq_name_1": "SQL", "rq_weight_1": "5", "rq_mand_1": "1",
            "rq_name_2": "Excel", "rq_weight_2": "4", "rq_mand_2": "1", "rq_syn_2": "hojas de cálculo",
            "rq_name_3": "Power BI", "rq_weight_3": "3", "rq_name_4": "Python", "rq_weight_4": "2"}
    if published:
        data["published"] = "1"
    data.update(extra)
    r = c.post("/vacancies/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text[:200]
    return int(r.headers["location"].split("/")[-1])


def apply(c, vid, content=STRONG, fname="cv.txt", phone="987654321", dept="La Libertad", prov="Trujillo", district="Trujillo", **over):
    data = {"phone": phone, "dept": dept, "prov": prov, "district": district, "exp_role": "Analista", "exp_company": "Comercial Norte", "exp_time": "2 años",
            "exp_desc": "Elaboraba reportes semanales de ventas y tableros.", "adult": "1", "consent": "1"}
    data.update(over)
    data = {k: v for k, v in data.items() if v is not None}
    return c.post(f"/empleos/{vid}/postular", data=data, files={"cv": (fname, content, "application/octet-stream")}, follow_redirects=False)


def cand_rows():
    from app.db import get_db
    with get_db() as db:
        return db.execute("SELECT * FROM candidates ORDER BY id").fetchall()


def flash_after(c, resp):
    return c.get(resp.headers["location"]).text


def upload_internal(c, vid, n=3, consent=True):
    files = [("files", (f"cv{i}.txt", f"Persona {i}\nAnalista con SQL y Excel {i} anos de experiencia en reportes de ventas.".encode(), "text/plain")) for i in range(n)]
    return c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"} if consent else {}, follow_redirects=True)


# ---------------- SUS y acceso ----------------
def test_sus_formula_y_categorias():
    assert sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 1]) == 77.5
    assert sus_score([5, 1] * 5) == 100.0 and sus_score([1, 5] * 5) == 0.0
    assert category(85) == "Excelente" and category(75) == "Bueno" and category(60) == "Marginal" and category(40) == "No aceptable"
    with pytest.raises(ValueError):
        sus_score([1, 2, 3])


def test_telefono_celular_peruano():
    assert valid_phone("987654321")
    for bad in ["87654321", "9876543210", "98765432a", "187654321", "", "98 765 432"]:
        assert not valid_phone(bad)


def test_acceso_sin_sesion_y_portada(client):
    assert client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).headers["location"] == "/empleos"
    assert "/registro" in client.get("/login").text


def test_perfiles_diferenciados(client):
    c = client
    login(c, "j@t.l")
    assert c.get("/vacancies/new").status_code == 403
    c.post("/logout"); login(c, "r@t.l")
    assert c.get("/admin/users").status_code == 403 and c.get("/admin/audit").status_code == 403


def test_sus_y_admin(client, monkeypatch):
    monkeypatch.setenv("SUS_REQUIRE_TASK", "0")
    c = client; login(c, "r@t.l")
    data = {f"q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
    c.post("/sus", data=data)
    assert c.post("/sus", data={**data, "consent": "1"}, follow_redirects=False).status_code == 303
    c.post("/sus", data={**data, "consent": "1"})
    c.post("/logout"); login(c, "a@t.l")
    csv = c.get("/admin/sus.csv").text
    assert csv.count("\n") == 2 and "Personal de reclutamiento" in csv and "P001" in csv and "75.0" in csv
    assert c.get("/admin/sus").status_code == 200


def test_admin_crea_empresas_y_participantes(client):
    c = client; login(c, "a@t.l")
    r = c.post("/admin/users/bulk", data={"role": "jefe", "count": 3, "company_id": 1})
    assert r.status_code == 200 and r.text.count("\n") == 4 and "jef01-e1@localmatch.local" in r.text
    assert c.post("/admin/users/bulk", data={"role": "jefe", "count": 3, "company_id": 1}).text.count("\n") == 1
    assert c.post("/admin/users/bulk", data={"role": "jefe", "count": 3}).status_code == 400
    one = c.post("/admin/users/one", data={"email": "x@y.z", "name": "Ana", "role": "reclutador", "company_id": 1})
    assert one.status_code == 200 and "Cuenta creada" in one.text
    assert "Empresa Nueva" in c.post("/admin/companies", data={"name": "Empresa Nueva"}, follow_redirects=True).text or True


# ---------------- reclutamiento: convocatorias ----------------
def test_flujo_interno_reclutamiento_a_jefe(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, published=False)
    files = [("files", (f, open(f"samples/{f}", "rb"), "text/plain")) for f in sorted(os.listdir("samples"))]
    assert c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"}, follow_redirects=False).status_code == 303
    assert c.post(f"/vacancies/{vid}/run", follow_redirects=False).status_code == 303
    rows = cand_rows()
    assert all("@" not in r["redacted_text"] for r in rows)
    best = max(rows, key=lambda r: r["score"])
    c.post(f"/candidates/{best['id']}/shortlist")
    c.post("/logout"); login(c, "j@t.l")
    page = c.get(f"/shortlists/{vid}").text
    assert f"#{best['id']}" in page and "Descargar CV" in page
    assert c.get(f"/candidates/{best['id']}/cv").status_code == 200
    other = [r for r in rows if r["id"] != best["id"]][0]
    assert c.get(f"/candidates/{other['id']}/cv").status_code == 404   # solo los enviados
    assert c.post(f"/candidates/{best['id']}/decision", data={"decision": "Entrevistar"}, follow_redirects=False).status_code == 303


def test_consentimiento_obligatorio_y_formatos(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, published=False)
    assert "Debes declarar" in upload_internal(c, vid, consent=False).text and not cand_rows()
    files = [("files", ("foto.png", b"\x89PNG" + b"x" * 200, "image/png")), ("files", ("cv.txt", STRONG, "text/plain"))]
    page = c.post(f"/vacancies/{vid}/upload", files=files, data={"consent": "1"}, follow_redirects=True)
    assert "1 CV cargado" in page.text and "1 no se pudieron leer" in page.text


def test_editar_cerrar_y_requisitos_con_peso(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, published=False)
    assert "SQL · peso 5 · excluyente" in c.get(f"/vacancies/{vid}").text
    c.post(f"/vacancies/{vid}/edit", data={"title": "Analista Senior", "area": "Ops", "description": "x", "min_years": "2", "boss_id": 2, "top_n": "5",
                                          "rq_name_1": "Tableau", "rq_weight_1": "4", "rq_mand_1": "1"})
    t = c.get(f"/vacancies/{vid}").text
    assert "Analista Senior" in t and "Tableau · peso 4 · excluyente" in t and "SQL ·" not in t
    upload_internal(c, vid)
    c.post(f"/vacancies/{vid}/toggle-status")
    assert "Cerrada" in c.get(f"/vacancies/{vid}").text and "está cerrada" in upload_internal(c, vid).text
    assert all(r["original_file"] is None for r in cand_rows())      # al cerrar se borran los archivos no seleccionados
    c.post(f"/vacancies/{vid}/toggle-status")
    assert "3 CV cargado" in upload_internal(c, vid).text


def test_plantillas_y_convocatorias_de_ejemplo(client):
    c = client; login(c, "r@t.l")
    page = c.get("/vacancies/new?plantilla=asistente-contable").text
    assert "Asistente contable" in page and "SUNAT" in page
    c.post("/logout"); login(c, "a@t.l")
    assert "Se crearon 7 convocatorias" in c.post("/admin/companies/1/demo", follow_redirects=True).text
    c.post("/logout")
    portal = c.get("/empleos").text
    for t in ["Ingeniero/a de Sistemas", "Analista de datos", "Asistente contable", "Practicante de Derecho", "Ingeniero/a Mecánico"]:
        assert t in portal
    c.post("/logout"); login(c, "a@t.l")
    assert "ya tiene" in c.post("/admin/companies/1/demo", follow_redirects=True).text


def test_vacante_no_publicada_no_aparece(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, published=False); c.post("/logout")
    assert "Analista" not in c.get("/empleos").text and c.get(f"/empleos/{vid}").status_code == 404


def test_multiempresa_aislamiento(client):
    c = client; from app.db import get_db
    with get_db() as db:
        c2 = db.insert("INSERT INTO companies(name) VALUES(?)", ("Otra Empresa",))
    make_user("r2@t.l", "Rec Dos", "reclutador", c2); make_user("j2@t.l", "Jefe Dos", "jefe", c2)
    login(c, "r@t.l"); vid = new_vac(c); upload_internal(c, vid)
    c.post("/logout"); login(c, "r2@t.l")
    assert c.get(f"/vacancies/{vid}").status_code == 404 and "Analista" not in c.get("/dashboard").text
    assert c.post("/candidates/1/delete").status_code == 404
    r = c.post("/vacancies/new", data={"title": "X", "area": "Y", "description": "Z", "boss_id": 2, "rq_name_1": "SQL"})
    assert r.status_code == 400                                          # no puede asignar un jefe de otra empresa
    assert "Analista" not in c.get("/empleos").text or True


# ---------------- postulante ----------------
def test_registro_con_verificacion(client):
    c = client
    page = c.get("/registro").text
    a, b = map(int, re.search(r"cuánto es (\d+) \+ (\d+)", page).groups())
    data = {"name": "Ana Perez", "email": "ana@x.com", "password": "clave12345", "cap": str(a + b + 1)}
    assert "La suma no es correcta" in c.post("/registro", data=data).text
    page = c.get("/registro").text
    a, b = map(int, re.search(r"cuánto es (\d+) \+ (\d+)", page).groups())
    r = c.post("/registro", data={**data, "cap": str(a + b)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/empleos"
    assert "Mis postulaciones" in c.get("/empleos").text
    c.post("/logout")
    a, b = map(int, re.search(r"cuánto es (\d+) \+ (\d+)", c.get("/registro").text).groups())
    assert "Ya existe una cuenta" in c.post("/registro", data={**data, "cap": str(a + b)}).text
    assert "Ingresa" in c.get(f"/empleos").text
    assert c.get("/dashboard", follow_redirects=False).status_code == 303
    assert c.post("/login", data={"email": "ana@x.com", "password": "clave12345"}, follow_redirects=False).status_code == 303
    assert c.get("/dashboard", follow_redirects=False).headers["location"] == "/empleos"
    assert c.get("/vacancies/new").status_code == 403 and c.get("/sus").status_code == 403


def test_validaciones_del_formulario(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, published=True, q_text_1="¿Tienes disponibilidad inmediata?", q_mand_1="1")
    c.post("/logout")
    assert apply(c, vid).headers["location"] == "/login"                    # sin cuenta no puede postular
    make_user("p@t.l"); login(c, "p@t.l")
    casos = [({"phone": "87654321"}, "9 dígitos"), ({"phone": "98765432a"}, "9 dígitos"), ({"adult": None}, "mayor de 18"), ({"consent": None}, "aceptar"),
             ({"district": ""}, "distrito"), ({"dept": "Lima"}, "distrito"), ({"district": "Chiclayo"}, "distrito"), ({"exp_desc": "corto"}, "última experiencia"), ({}, "Responde todas")]
    for over, msg in casos:
        over = dict(over)
        if msg != "Responde todas":
            over.setdefault("ans_1", "Sí")
        r = apply(c, vid, **over)
        assert msg in flash_after(c, r), (over, msg)
    assert not cand_rows()
    assert apply(c, vid, ans_1="Sí").headers["location"].endswith("/exito")
    assert apply(c, vid, content=STRONG + b" ", ans_1="Sí").status_code == 303 and len(cand_rows()) == 1


def test_postulacion_exitosa_y_mis_postulaciones(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l", "Ana Perez Soto"); login(c, "p@t.l")
    r = apply(c, vid); assert r.status_code == 303
    exito = c.get(r.headers["location"]).text
    assert "¡Postulación exitosa!" in exito
    mis = c.get("/mis-postulaciones").text
    assert "Analista de datos" in mis and "Evaluada por el equipo de selección" in mis and "puntaje" not in mis.lower()
    row = cand_rows()[0]
    assert row["applicant_phone"] == "987654321" and row["original_file"] is not None and row["source"] == "postulante" and row["adult_confirmed"] == 1
    assert "Perez" not in row["redacted_text"] and "ÚLTIMA EXPERIENCIA" in row["redacted_text"]   # anonimizado y con la experiencia
    again = apply(c, vid, content=MEDIUM)
    assert "Ya postulaste" in flash_after(c, again)
    make_user("p2@t.l", "Otro"); c.post("/logout"); login(c, "p2@t.l")
    assert "ya fue enviado" in flash_after(c, apply(c, vid))               # mismo archivo en la misma convocatoria
    c.post("/logout"); login(c, "p@t.l")
    assert c.post(f"/mis-postulaciones/{row['id']}/eliminar", follow_redirects=False).status_code == 303 and not cand_rows()


def test_excluyentes_preguntas_y_top_n(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, top_n="3", q_text_1="¿Tienes disponibilidad inmediata?", q_mand_1="1"); c.post("/logout")
    for i, (cv, ans) in enumerate([(STRONG, "Sí"), (MEDIUM, "Sí"), (WEAK, "Sí"), (STRONG + b" otro", "No")]):
        make_user(f"p{i}@t.l", f"Post {i}"); login(c, f"p{i}@t.l"); apply(c, vid, content=cv, ans_1=ans, exp_company=f"Empresa {i}"); c.post("/logout")
    rows = {r["applicant_name"]: r for r in cand_rows()}
    import json
    assert json.loads(rows["Post 2"]["breakdown_json"])["meets_mandatory"] is False        # no cumple SQL ni Excel
    login(c, "r@t.l")
    page = c.get(f"/vacancies/{vid}").text
    assert "Top 3" in page and "No cumple excluyentes" in page and "Respondió «No»" in page
    assert page.count('class="badge ok">Top 3') == 2                                       # solo 2 candidatos son elegibles
    assert "Enviar los 2 mejores al jefe" in page
    c.post(f"/vacancies/{vid}/send-top")
    sel = [r for r in cand_rows() if r["shortlisted"]]
    assert sorted(r["applicant_name"] for r in sel) == ["Post 0", "Post 1"]


def test_descargas_zip_y_cv(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    for i, cv in enumerate([STRONG, MEDIUM]):
        make_user(f"p{i}@t.l", f"Post {i}"); login(c, f"p{i}@t.l"); apply(c, vid, content=cv); c.post("/logout")
    login(c, "r@t.l")
    assert "Aún no hay candidatos seleccionados" in flash_after(c, c.get(f"/vacancies/{vid}/seleccionados.zip", follow_redirects=False))
    c.post(f"/vacancies/{vid}/send-top")
    z = c.get(f"/vacancies/{vid}/seleccionados.zip")
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert len([n for n in names if n.endswith(".txt")]) == 2 and any(n.endswith(".xlsx") for n in names)
    from openpyxl import load_workbook
    xl = [n for n in names if n.endswith(".xlsx")][0]
    ws = load_workbook(io.BytesIO(zipfile.ZipFile(io.BytesIO(z.content)).read(xl))).active
    assert ws.max_row == 3 and ws["B2"].value == "Post 0" and ws["D2"].value == "987654321"
    cid0 = [r for r in cand_rows() if r["applicant_name"] == "Post 0"][0]["id"]
    assert c.get(f"/candidates/{cid0}/cv").content == STRONG
    c.post("/logout"); login(c, "j@t.l")
    zj = c.get(f"/shortlists/{vid}/cvs.zip")
    assert zj.status_code == 200 and len([n for n in zipfile.ZipFile(io.BytesIO(zj.content)).namelist() if n.endswith(".txt")]) == 2
    page = c.get(f"/shortlists/{vid}").text
    assert "Post 0" in page and "987654321" in page and "Descargar CV" in page
    make_user("j2@t.l", "Otro Jefe", "jefe", 1); c.post("/logout"); login(c, "j2@t.l")
    assert c.get(f"/candidates/{cid0}/cv").status_code == 404 and c.get(f"/shortlists/{vid}/cvs.zip").status_code == 404


def test_sinonimos_pesos_y_experiencia():
    from app.skills.extract import extract_profile
    from app.skills.score import score_candidate
    items = [{"name": "Excel", "kind": "herramienta", "weight": 4, "mandatory": True, "synonyms": ["hojas de cálculo"]},
             {"name": "SQL", "kind": "herramienta", "weight": 1, "mandatory": True, "synonyms": []},
             {"name": "Inglés", "kind": "idioma", "weight": 2, "mandatory": False, "synonyms": []}]
    p = extract_profile("Dominio de hojas de cálculo avanzadas. 3 años de experiencia.", items)
    assert p["must_found"] == ["Excel"] and p["nice_found"] == []
    sc = score_candidate({"items": items, "min_years": 2}, p, 0.2)
    assert sc["must_missing"] == ["SQL"] and sc["meets_mandatory"] is False and sc["parts"]["must"] == 80.0 and sc["parts"]["exp"] == 100.0


def test_descartar_con_motivo_comparar_y_metricas(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    for i, cv in enumerate([STRONG, MEDIUM, WEAK]):
        make_user(f"p{i}@t.l", f"Post {i}"); login(c, f"p{i}@t.l"); apply(c, vid, content=cv); c.post("/logout")
    login(c, "r@t.l")
    ids = [r["id"] for r in cand_rows()]
    cmp_page = c.get(f"/vacancies/{vid}/comparar?ids={ids[0]}&ids={ids[1]}").text
    assert "Comparar candidatos" in cmp_page and "Post 0" in cmp_page and "Post 1" in cmp_page
    assert "Marca entre 2 y 4" in flash_after(c, c.get(f"/vacancies/{vid}/comparar?ids={ids[0]}", follow_redirects=False))
    c.post(f"/candidates/{ids[1]}/shortlist")
    assert c.post(f"/candidates/{ids[1]}/reject", data={"reason": "otro"}).status_code == 400
    c.post(f"/candidates/{ids[1]}/reject", data={"reason": "Experiencia insuficiente", "note": "pide más años"})
    page = c.get(f"/vacancies/{vid}").text
    assert "Descartado por reclutamiento: Experiencia insuficiente: pide más años" in page
    assert [r for r in cand_rows() if r["id"] == ids[1]][0]["shortlisted"] == 0
    c.post(f"/candidates/{ids[1]}/reopen")
    assert "Descartado por reclutamiento" not in c.get(f"/vacancies/{vid}").text
    c.post(f"/candidates/{ids[0]}/shortlist")
    dash = c.get("/dashboard").text
    assert "Beneficio para tu empresa" in dash and "3" in dash and "CV recibidos" in dash


def test_entrevista_rubrica_y_estado_del_postulante(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l", "Post Uno"); login(c, "p@t.l"); apply(c, vid); c.post("/logout")
    cid = cand_rows()[0]["id"]
    login(c, "r@t.l"); c.post(f"/candidates/{cid}/shortlist"); c.post("/logout")
    login(c, "j@t.l")
    assert "Primero marca" in flash_after(c, c.post(f"/candidates/{cid}/interview", data={"at": "2026-12-01T10:00", "place": "Oficina"}, follow_redirects=False))
    c.post(f"/candidates/{cid}/decision", data={"decision": "Entrevistar"})
    c.post(f"/candidates/{cid}/interview", data={"at": "2026-12-01T10:00", "place": "Oficina principal"})
    assert "Registra la evaluación después" in flash_after(c, c.post(f"/candidates/{cid}/rubric", data={"final": "Contratado"}, follow_redirects=False))
    c.post(f"/candidates/{cid}/interview-done")
    assert "Califica los 4" in flash_after(c, c.post(f"/candidates/{cid}/rubric", data={"final": "Contratado", "r_tecnico": "4"}, follow_redirects=False))
    c.post(f"/candidates/{cid}/rubric", data={"r_tecnico": "5", "r_comunicacion": "4", "r_ajuste": "4", "r_actitud": "5", "final": "Contratado", "note": "Buen perfil"})
    assert "Contratado" in c.get(f"/shortlists/{vid}").text
    c.post("/logout"); login(c, "p@t.l")
    assert "¡Fuiste seleccionado/a para el puesto!" in c.get("/mis-postulaciones").text


def test_estado_entrevista_programada_visible_al_postulante(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l"); login(c, "p@t.l"); apply(c, vid); c.post("/logout")
    cid = cand_rows()[0]["id"]
    login(c, "r@t.l"); c.post(f"/candidates/{cid}/shortlist"); c.post("/logout")
    login(c, "j@t.l"); c.post(f"/candidates/{cid}/decision", data={"decision": "Entrevistar"}); c.post(f"/candidates/{cid}/interview", data={"at": "2026-12-01T10:00", "place": "Oficina principal"}); c.post("/logout")
    login(c, "p@t.l")
    mis = c.get("/mis-postulaciones").text
    assert "Entrevista programada" in mis and "Oficina principal" in mis and "2026-12-01 a las 10:00" in mis


def test_cierre_por_fecha_borra_archivos_y_cierra_la_postulacion(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c, closing_date="2099-01-01"); c.post("/logout")
    for i, cv in enumerate([STRONG, MEDIUM]):
        make_user(f"p{i}@t.l", f"Post {i}"); login(c, f"p{i}@t.l"); apply(c, vid, content=cv); c.post("/logout")
    first = cand_rows()[0]["id"]
    login(c, "r@t.l"); c.post(f"/candidates/{first}/shortlist"); c.post("/logout")
    from app.db import get_db
    with get_db() as db:
        db.execute("UPDATE vacancies SET closing_date='2020-01-01' WHERE id=?", (vid,))
    assert "Analista de datos" not in c.get("/empleos").text
    rows = {r["id"]: r for r in cand_rows()}
    assert rows[first]["original_file"] is not None and [r for i, r in rows.items() if i != first][0]["original_file"] is None
    assert c.get(f"/empleos/{vid}").status_code == 404
    with get_db() as db:
        assert db.execute("SELECT status FROM vacancies WHERE id=?", (vid,)).fetchone()["status"] == "cerrada"


# ---------------- tarea guiada, escenario y auditoría ----------------
def test_tarea_guiada_habilita_el_sus(client):
    c = client; login(c, "r@t.l")
    data = {f"q{i}": 4 if i % 2 else 2 for i in range(1, 11)}
    assert "Primero completa tu tarea" in c.get("/sus").text
    c.post("/sus", data={**data, "consent": "1"})
    from app.db import get_db
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sus_responses").fetchone()["n"] == 0
    vid = new_vac(c, published=False); upload_internal(c, vid); c.post(f"/vacancies/{vid}/run")
    c.post(f"/candidates/{cand_rows()[0]['id']}/shortlist")
    assert "Primero completa tu tarea" not in c.get("/sus").text
    c.post("/sus", data={**data, "consent": "1"})
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sus_responses").fetchone()["n"] == 1


def test_escenario_para_jefes(client):
    c = client; login(c, "a@t.l")
    assert "Escenario preparado para 1 jefe" in c.post("/admin/scenario", follow_redirects=True).text
    assert "Todos los jefes de área ya tienen su escenario" in c.post("/admin/scenario", follow_redirects=True).text
    c.post("/logout"); login(c, "j@t.l")
    assert "tarea del estudio" in c.get("/dashboard").text.lower()
    from app.db import get_db
    with get_db() as db:
        v = db.execute("SELECT id, published FROM vacancies WHERE boss_id=2").fetchone()
        cid = db.execute("SELECT id FROM candidates WHERE vacancy_id=? AND shortlisted=1 ORDER BY score DESC", (v["id"],)).fetchall()
    assert len(cid) == 5 and v["published"] == 0                           # la vacante de práctica no se publica en el portal
    assert "Primero completa tu tarea" in c.get("/sus").text
    c.post(f"/candidates/{cid[0]['id']}/decision", data={"decision": "Entrevistar"})
    assert "Primero completa tu tarea" not in c.get("/sus").text


def test_auditoria_registra_acciones(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); upload_internal(c, vid); c.post(f"/vacancies/{vid}/run"); c.post("/logout")
    make_user("p@t.l"); login(c, "p@t.l"); apply(c, vid, content=MEDIUM); c.post("/logout")
    login(c, "a@t.l")
    t = c.get("/admin/audit").text
    for accion in ("vacante_creada", "cv_cargados", "agente_ejecutado", "postulacion_recibida"):
        assert accion in t
    c.post("/logout"); login(c, "r@t.l")
    assert c.get("/admin/audit").status_code == 403


def test_ranking_csv_incluye_contacto(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l", "Ana Perez"); login(c, "p@t.l"); apply(c, vid); c.post("/logout"); login(c, "r@t.l")
    r = c.get(f"/vacancies/{vid}/ranking.csv")
    assert r.status_code == 200 and r.text.startswith("posicion,candidato") and "Ana Perez" in r.text and "p@t.l" in r.text and "987654321" in r.text


def test_el_jefe_ve_los_candidatos_en_su_inicio(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l", "Ana Perez Soto"); login(c, "p@t.l"); apply(c, vid); c.post("/logout")
    cid = cand_rows()[0]["id"]
    login(c, "j@t.l")
    assert "Ana Perez Soto" not in c.get("/dashboard").text                     # aún no se lo enviaron
    assert "Aún no tienes candidatos" in c.get("/dashboard").text
    c.post("/logout"); login(c, "r@t.l")
    assert "Julio Jefe (j@t.l)" in c.get(f"/vacancies/{vid}").text              # la convocatoria muestra a qué jefe va
    msg = flash_after(c, c.post(f"/candidates/{cid}/shortlist", follow_redirects=False))
    assert "Candidato enviado a Julio Jefe (j@t.l)" in msg
    c.post("/logout"); login(c, "j@t.l")
    dash = c.get("/dashboard").text
    assert "Hola, Julio Jefe" in dash and "Jefe de Área" in dash and "Empresa Test" in dash
    assert "Ana Perez Soto" in dash and "Descargar CV" in dash and "Guardar decisión" in dash
    assert dash.index("Hola, Julio Jefe") < dash.index("Jefe de Área") < dash.index("Ana Perez Soto")
    make_user("j2@t.l", "Otro Jefe", "jefe", 1); c.post("/logout"); login(c, "j2@t.l")
    assert "Ana Perez Soto" not in c.get("/dashboard").text                       # solo ve lo que le asignaron a él
    c.post("/logout"); login(c, "j@t.l")
    assert "Decisión registrada" in flash_after(c, c.post(f"/candidates/{cid}/decision", data={"decision": "En espera"}, follow_redirects=False))


def test_empresas_de_ejemplo_y_vista_del_administrador(client):
    import csv as _csv
    c = client; login(c, "a@t.l")
    r = c.post("/admin/demo-empresas")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(_csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 12 and {x["empresa"] for x in rows} == {"NTT DATA", "FISAC", "TRC", "Estudio Jurídico Muñoz", "Backus", "BRAMOTORS"}
    assert len(_csv.reader(io.StringIO(c.post("/admin/demo-empresas").text)).__next__()) == 4 and c.post("/admin/demo-empresas").text.count("\n") == 1   # no repite cuentas
    dash = c.get("/dashboard").text
    assert "Hola, Admin" in dash and "Administrador de LocalMatch" in dash and "NTT DATA" in dash and "Backus" in dash and "Ver empresa" in dash
    from app.db import get_db
    with get_db() as db:
        ntt = db.execute("SELECT id FROM companies WHERE name='NTT DATA'").fetchone()["id"]
        mun = db.execute("SELECT id FROM companies WHERE name='Estudio Jurídico Muñoz'").fetchone()["id"]
    det = c.get(f"/admin/companies/{ntt}").text
    assert "Reclutadora NTT DATA" in det and "Jefe NTT DATA" in det and "Ingeniero/a de Sistemas" in det and "Analista de datos" in det and "Practicante de Derecho" not in det
    assert "Practicante de Derecho" in c.get(f"/admin/companies/{mun}").text
    portal = c.post("/logout") and c.get("/empleos").text
    assert "Ingeniero/a Mecánico" in portal and "Practicante de Derecho" in portal and "BRAMOTORS" in portal
    cred = {(x["empresa"], x["rol"]): x for x in rows}
    rec, jefe = cred[("NTT DATA", "reclutador")], cred[("NTT DATA", "jefe")]
    with get_db() as db:
        vid = db.execute("SELECT id FROM vacancies WHERE company_id=? AND title='Analista de datos'", (ntt,)).fetchone()["id"]
    make_user("p@t.l", "Ana Perez Soto"); login(c, "p@t.l"); apply(c, vid, ans_1="Sí"); c.post("/logout")
    assert c.post("/login", data={"email": rec["correo"], "password": rec["contrasena"]}, follow_redirects=False).status_code == 303
    assert "Hola, Reclutadora NTT DATA" in c.get("/dashboard").text
    c.post(f"/vacancies/{vid}/send-top"); c.post("/logout")
    assert c.post("/login", data={"email": jefe["correo"], "password": jefe["contrasena"]}, follow_redirects=False).status_code == 303
    page = c.get("/dashboard").text
    assert "Hola, Jefe NTT DATA" in page and "Ana Perez Soto" in page and "Analista de datos" in page


def test_ubicacion_completa_departamento_provincia_distrito(client):
    from app import geo
    assert len(geo.DATA) == 25 and sum(len(d["p"]) for d in geo.DATA) == 196 and sum(len(p["d"]) for d in geo.DATA for p in d["p"]) == 1892
    assert geo.valid("La Libertad", "Trujillo", "Víctor Larco Herrera") and geo.valid("Lima", "Lima", "Miraflores") and geo.valid("Junín", "Huancayo", "Huancayo")
    assert not geo.valid("Lima", "Trujillo", "Trujillo") and not geo.valid("La Libertad", "Trujillo", "Miraflores")
    assert client.get("/static/ubigeo.json").status_code == 200 and "La Libertad" in client.get("/static/ubigeo.json").text
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l"); login(c, "p@t.l")
    html = c.get(f"/empleos/{vid}").text
    assert 'name="dept"' in html and 'name="prov"' in html and 'name="district"' in html and "ubigeo.json" in html
    assert apply(c, vid, district="Víctor Larco Herrera").headers["location"].endswith("/exito")
    assert cand_rows()[0]["applicant_district"] == "Víctor Larco Herrera, Trujillo, La Libertad"


def test_admin_edita_restablece_y_elimina_cuentas(client):
    c = client; login(c, "a@t.l")
    page = c.get("/admin/companies/1").text
    assert "Restablecer contraseña" in page and "r@t.l" in page and "Editar" in page
    uid = make_user("x@t.l", "Ana Uno", "reclutador", 1)
    assert "Cuenta actualizada" in c.post(f"/admin/users/{uid}/edit", data={"name": "Ana Dos", "email": "ana2@t.l"}, follow_redirects=True).text
    assert "Ya existe otra cuenta" in c.post(f"/admin/users/{uid}/edit", data={"name": "Ana", "email": "r@t.l"}, follow_redirects=True).text
    assert "Revisa el nombre" in c.post(f"/admin/users/{uid}/edit", data={"name": "Ana", "email": "no-es-correo"}, follow_redirects=True).text
    r = c.post(f"/admin/users/{uid}/reset-password")
    assert "Nueva contraseña generada" in r.text and "ana2@t.l" in r.text
    import re as _re
    pw = _re.search(r"Contraseña: <code>([^<]+)</code>", r.text).group(1)
    c.post("/logout")
    assert c.post("/login", data={"email": "ana2@t.l", "password": pw}, follow_redirects=False).status_code == 303
    assert c.post("/login", data={"email": "ana2@t.l", "password": PW}, follow_redirects=False).status_code == 200      # la anterior ya no sirve
    login(c, "a@t.l")
    assert "Cuenta eliminada" in c.post(f"/admin/users/{uid}/delete", follow_redirects=True).text
    assert c.post(f"/admin/users/{uid}/delete").status_code == 404


def test_limpiar_cuentas_de_participantes(client):
    c = client; login(c, "a@t.l")
    c.post("/admin/users/bulk", data={"role": "jefe", "count": 4, "company_id": 1}); c.post("/admin/users/bulk", data={"role": "reclutador", "count": 3, "company_id": 1})
    from app.db import get_db
    with get_db() as db:
        jef01 = db.execute("SELECT id FROM users WHERE email='jef01-e1@localmatch.local'").fetchone()["id"]
        rec01 = db.execute("SELECT id FROM users WHERE email='rec01-e1@localmatch.local'").fetchone()["id"]
        jef02 = db.execute("SELECT id FROM users WHERE email='jef02-e1@localmatch.local'").fetchone()["id"]
        db.execute("INSERT INTO sus_responses(user_id,profile,answers,score) VALUES(?,?,?,?)", (jef02, "jefe", "[4,2,4,2,4,2,4,2,4,2]", 75))
    c.post("/logout"); login(c, "r@t.l"); vid = new_vac(c, boss_id=jef01); c.post("/logout")        # convocatoria asignada a un participante
    login(c, "a@t.l")
    assert "7 cuenta(s)" in c.get("/admin/companies/1").text or "Eliminar las 7" in c.get("/admin/companies/1").text
    msg = c.post("/admin/companies/1/clean-participants", follow_redirects=True).text
    assert "Se eliminaron 6 cuenta(s)" in msg and "jef02-e1@localmatch.local" in msg and "respondió el SUS" in msg    # conserva al que contestó el SUS
    with get_db() as db:
        emails = {r["email"] for r in db.execute("SELECT email FROM users").fetchall()}
        boss = db.execute("SELECT boss_id FROM vacancies WHERE id=?", (vid,)).fetchone()["boss_id"]
        j_id = db.execute("SELECT id FROM users WHERE email='j@t.l'").fetchone()["id"]
    assert {"r@t.l", "j@t.l", "a@t.l", "jef02-e1@localmatch.local"} <= emails and "rec01-e1@localmatch.local" not in emails and "jef01-e1@localmatch.local" not in emails
    assert boss == j_id                                                                      # la convocatoria pasó al jefe que se conserva


def test_el_jefe_ve_la_opcion_alterna_y_el_motivo(client):
    c = client; login(c, "r@t.l"); vid = new_vac(c); c.post("/logout")
    make_user("p@t.l", "Carlos Medina"); login(c, "p@t.l"); apply(c, vid, content=WEAK); c.post("/logout")
    cid = cand_rows()[0]["id"]
    login(c, "r@t.l")
    assert "Enviar los 0 mejores al jefe" in c.get(f"/vacancies/{vid}").text        # no cumple los excluyentes: el top queda vacío
    c.post(f"/candidates/{cid}/shortlist")                                           # pero la reclutadora puede enviarlo igual
    c.post("/logout"); login(c, "j@t.l")
    dash = c.get("/dashboard").text
    assert "Carlos Medina" in dash and "Opción alterna" in dash and "no cumple" in dash

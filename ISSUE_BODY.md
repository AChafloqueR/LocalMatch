# Resumen de cambios: Registro de postulantes, anonimizacion dual y mejoras UX

## Resumen general

Este PR implementa el registro de postulantes como nuevo rol, cambia el flujo de anonimizacion para guardar ambas versiones del CV (original + anonimizada), anade paginas legales publicas (Terminos y Privacidad), y mejora la UX del boton "Ver CV original".

---

## Cambios principales

### 1. Nuevo rol: Postulante (app/db.py, app/main.py, app/templates/)

Que cambia:
- Tabla users: nuevo valor role = 'postulante' en el CHECK constraint
- Rutas nuevas:
  - GET /registro — formulario publico de registro
  - POST /registro — crea cuenta con validacion de contrasena (>=8 chars) y aceptacion obligatoria de Terminos y Privacidad
  - GET /postular/{vid} — formulario para postularse a una vacante (1 solo archivo, max. 5 MB)
  - POST /postular/{vid} — guarda postulacion con CV original + anonimizado
  - GET /dashboard (postulante) — muestra vacantes abiertas + estado de postulaciones propias

Por que: Los postulantes ahora se auto-registran, suben su CV y siguen el estado de su postulacion (Recibido -> Evaluado -> Preseleccionado -> Decision del jefe). Antes solo existia via seed manual.

---

### 2. Anonimizacion dual: CV original + CV anonimizado (app/db.py, app/main.py)

Que cambia:
- Tabla candidates: nueva columna original_text TEXT NOT NULL
- Al subir CV (reclutador o postulante):
  - original_text = texto extraido del PDF/DOCX/TXT sin modificar
  - redacted_text = version anonimizada (para LLM/scoring)
- Mensaje de confirmacion: "X CV cargado(s)." (ya no dice "y anonimizado(s)")

Por que:
- Reclutador ve CV original para contactar al candidato si queda seleccionado
- Jefe de area tambien ve CV original de preseleccionados (para contactar)
- LLM/Agente recibe solo la version anonimizada (privacidad)
- Cumple con el principio: anonymize before LLM, keep original for humans

---

### 3. Paginas legales publicas (app/main.py, app/templates/terminos.html, app/templates/privacidad.html)

Rutas nuevas (sin login):
- GET /terminos — Terminos y condiciones detallados (10 secciones)
- GET /privacidad — Politica de privacidad (11 secciones)

Contenido clave actualizado:

| Seccion | Antes | Ahora |
|---------|-------|-------|
| Anonimizacion | "CV se anonimiza antes de guardarse" | "CV original se guarda; solo se anonimiza al enviar al LLM" |
| Quien ve que | "Reclutador y jefe no ven identidad" | Reclutador ve original, Jefe ve original de preseleccionados, solo LLM ve anonimizado |
| Flujo | 4 pasos | 6 pasos (explicito: original guardado -> anonimizado para LLM -> reclutador ve original -> jefe ve original) |
| Destinatarios | Jefe = anonimizado | Jefe = CV original |
| Seguridad | "Datos nunca persisten en CV guardado" | "CV original seguro (acceso reclutador + jefe). Anonimizacion antes de LLM" |

En /registro: Checkbox obligatorio con enlaces a ambas paginas (target="_blank")

---

### 4. UX: Boton "Ver CV original" <-> "Ocultar CV original" (app/templates/vacancy_detail.html, app/templates/shortlist.html)

Que cambia:
- Boton con id="btn-cv-{id}"
- JS toggleCV(id) alterna:
  - Muestra/oculta <pre> con original_text
  - Cambia textContent: "Ver CV original" <-> "Ocultar CV original"

Por que: Feedback visual claro del estado (visible/oculto). Antes el texto no cambiaba y el usuario no sabia si estaba abierto o cerrado.

---

### 5. Eliminacion del modulo SUS (app/sus.py, app/templates/sus.html, app/templates/admin_sus.html, app/main.py)

Que se elimino:
- Archivo app/sus.py (calculo SUS, categorias)
- Rutas /sus, /admin/sus, /admin/sus.csv
- Templates sus.html, admin_sus.html
- Referencias en navbar, dashboard, base.html

Por que: El cuestionario SUS era para el estudio academico (60 usuarios). Ahora el foco es el flujo productivo de postulantes.

---

### 6. Tests actualizados (tests/test_core.py)

Nuevos tests:
- test_sus_eliminado — verifica que rutas SUS devuelven 404
- test_manual_de_ayuda — verifica /ayuda accesible con login
- test_flujo_postulante — flujo completo: registro -> postulacion -> evaluacion -> preseleccion -> decision
- test_postulante_permisos — postulante no accede a /vacancies/new, /admin/users, /shortlists
- test_postulacion_validaciones — contrasena corta, correo duplicado, archivo ilegible, postulacion duplicada

Tests eliminados:
- test_sus_ejemplo_de_la_diapositiva
- test_categorias
- test_sus_valida_entrada
- test_sus_y_admin

Resultado: 10 tests pasan (antes 10 + 4 SUS = 14, ahora 10 relevantes)

---

## Archivos modificados

| Archivo | Tipo | Descripcion |
|---------|------|-------------|
| app/db.py | mod | +columna original_text, +rol postulante, -tabla sus_responses |
| app/main.py | mod | +rutas registro/postulacion/legales, -rutas SUS, +logica dual original/redacted |
| app/sus.py | del | Eliminado (modulo SUS completo) |
| app/templates/vacancy_detail.html | mod | Boton toggle CV original, hint actualizado |
| app/templates/shortlist.html | mod | Boton toggle CV original, subtitulo actualizado |
| app/templates/registro.html | new | Formulario con Terminos/Privacidad expandibles + checkbox obligatorio |
| app/templates/postular.html | new | Formulario postulacion (1 archivo, 5 MB) |
| app/templates/postulante.html | new | Dashboard postulante (vacantes + mis postulaciones) |
| app/templates/terminos.html | new | 10 secciones detalladas |
| app/templates/privacidad.html | new | 11 secciones detalladas |
| app/templates/base.html | mod | Navbar: +Ayuda, -SUS, +rol postulante |
| app/templates/dashboard.html | mod | Dashboard por rol (postulante/admin), -banner SUS |
| app/templates/login.html | mod | Enlace a /registro |
| tests/test_core.py | mod | Tests SUS -> tests postulante |

---

## Verificacion manual

```bash
# 1. Tests
python -m pytest -q
# 10 passed

# 2. Como reclutador (ve CV original)
curl -b cookies.txt http://localhost:8000/vacancies/1
# -> Boton "Ver CV original" / "Ocultar CV original" funciona

# 3. Como jefe de area (ve CV original de preseleccionados)
curl -b cookies_jefe.txt http://localhost:8000/shortlists/1
# -> Igual: boton toggle funciona

# 4. Paginas legales publicas (sin login)
curl http://localhost:8000/terminos
curl http://localhost:8000/privacidad

# 5. Registro postulante
curl http://localhost:8000/registro
# -> Checkbox "He leido y acepto los Terminos y condiciones y la Politica de privacidad"
```

---

## Migracion de base de datos

Si actualizas desde version anterior:
```bash
rm localmatch.db
python -m scripts.seed --demo
```
Cambios en esquema:
- candidates.original_text (nueva, NOT NULL DEFAULT '')
- users.role ahora incluye 'postulante'
- Tabla sus_responses eliminada
- Indice unico candidates_applicant (applicant_id, vacancy_id)

Checklist de revision:
- [ ] Tests pasan (10/10)
- [ ] Registro postulante funciona con Terminos/Privacidad
- [ ] Postulacion a vacante (1 archivo, 5 MB)
- [ ] Reclutador ve CV original + boton toggle
- [ ] Jefe ve CV original de preseleccionados + boton toggle
- [ ] LLM recibe solo version anonimizada
- [ ] Paginas legales accesibles sin login
- [ ] Textos legales reflejan flujo real (original para humanos, anonimizado para IA)
- [ ] Migracion DB documentada
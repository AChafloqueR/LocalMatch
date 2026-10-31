# Pipeline de construcción de LocalMatch

Se sigue el proceso de seis etapas del curso, organizado en tres sprints de Scrum. Cada etapa deja una evidencia para el informe (figura, tabla o anexo).

| Etapa | Qué se hace en LocalMatch | Evidencia para el informe |
|---|---|---|
| 1. Análisis de requisitos | Entrevista con el propietario del negocio; lista de requisitos e historias de usuario (ver abajo) | Lista de requisitos, historias de usuario |
| 2. Diseño | Modelo de datos (`app/db.py`), wireframes de las 5 pantallas, arquitectura de 3 capas | Diagrama del modelo, wireframes, diagrama de arquitectura |
| 3. Construcción | Sprints 1 y 2, en ramas `feature/*` con revisión entre pares | Capturas del repositorio y del tablero |
| 4. Pruebas | `python -m pytest -q` + casos manuales por perfil | Matriz de casos de prueba con resultado |
| 5. Despliegue | Docker en Render o Railway, usuarios de los 60 participantes | URL pública, manual breve |
| 6. Evaluación de uso | SUS dentro del sistema (`/sus`), CSV y análisis | Base de respuestas y puntajes |

## Sprint 1 · semanas 5–7 · CRUD de la entidad núcleo (vacante + CV)
- [ ] Estructura del repositorio, `requirements.txt`, `.env.example`, `README.md`
- [ ] Login y perfiles (`reclutador`, `jefe`, `admin`) con contraseñas con hash
- [ ] CRUD de vacantes
- [ ] Carga de CV (PDF/DOCX/TXT), lectura de texto y **anonimización** (`skills/redact.py`)
- [ ] Pruebas de acceso por perfil
**Incremento:** reclutamiento crea vacantes y sube CV anonimizados.

## Sprint 2 · semanas 8–10 · Funcionalidad diferenciadora: el agente
- [ ] `skills/extract.py` (competencias, años, formación, evidencias)
- [ ] `skills/score.py` (pesos: obligatorios 50 %, deseables 15 %, experiencia 20 %, afinidad semántica 15 %)
- [ ] `skills/explain.py` y `skills/pipeline.py`
- [ ] Pantalla de ranking con desglose, evidencias y nota manual
- [ ] Envío al jefe de área y pantalla de decisión
- [ ] Opcional: `LLM_PROVIDER=ollama` o `anthropic` y comparar contra el modo `mock`
**Incremento:** ranking explicable de punta a punta con decisión del jefe de área.

## Sprint 3 · semanas 11–13 · Despliegue, correcciones y preparación del SUS
- [ ] Módulo SUS (`/sus`), consentimiento informado, exportación CSV (`/admin/sus.csv`)
- [ ] Cuentas para 30 + 30 participantes (`scripts/create_users.py`)
- [ ] Despliegue (abajo) y manual breve de uso
- [ ] Correcciones de las pruebas y prueba piloto con 3–5 personas
- [ ] Ensayo del análisis con datos de prueba (`analysis/sus_analysis.py`)
**Incremento:** sistema desplegado y listo para aplicar el SUS.

## Historias de usuario base (ajústalas con tu entrevista)
1. Como reclutador quiero registrar una vacante con sus requisitos para que el agente sepa qué buscar.
2. Como reclutador quiero subir varios CV a la vez para no revisarlos uno por uno.
3. Como reclutador quiero ver un ranking con el motivo de cada puntaje para confiar en él y corregirlo.
4. Como reclutador quiero enviar solo los mejores candidatos al jefe de área para ahorrarle tiempo.
5. Como jefe de área quiero ver candidatos anonimizados y explicados para decidir sin sesgos.
6. Como jefe de área quiero registrar mi decisión y un comentario para que reclutamiento continúe el proceso.
7. Como participante del estudio quiero responder el SUS dentro del sistema para evaluar mi experiencia.
8. Como investigador quiero descargar los puntajes por perfil para analizarlos estadísticamente.

## Despliegue
**Opción A · Render (simple).** Sube el repo a GitHub → Render → *New Web Service* → elige el repo → *Runtime: Docker* →
variables: `SECRET_KEY` (cadena larga), `HTTPS_ONLY=1`, `LLM_PROVIDER=mock`, `DB_PATH=/data/localmatch.db` → agrega un **disco persistente** montado en `/data` (SQLite necesita disco persistente).
Luego, en la consola (*Shell*) de Render: `python -m scripts.seed` y `python -m scripts.create_users --role reclutador --count 30`.

**Opción B · Docker local.** `docker build -t localmatch . && docker run -p 8000:8000 -e SECRET_KEY=algo-largo -v lm:/data -e DB_PATH=/data/lm.db localmatch`

## Flujo de Git (evidencia de que todos programan)
```bash
git init && git add . && git commit -m "Estructura inicial de LocalMatch"
git branch -M main
git remote add origin https://github.com/<usuario>/localmatch.git
git push -u origin main
# cada integrante:
git checkout -b feature/ranking && git commit -am "Agrega desglose del puntaje" && git push -u origin feature/ranking
# abrir Pull Request en GitHub y pedir revisión de un compañero antes de fusionar
```

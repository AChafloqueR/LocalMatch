# LocalMatch

Agente de apoyo a la preselección y ranking de candidatos, con **supervisión humana**, pensado para empresas de Trujillo.
Incluye perfiles diferenciados (reclutamiento / jefe de área / investigación) y un módulo para aplicar el cuestionario **SUS** del estudio.

## Qué hace
1. **Reclutamiento** crea una vacante (requisitos obligatorios y deseables, años mínimos) y sube CV en PDF, DOCX o TXT.
2. El agente **anonimiza** cada CV, **extrae** su perfil, **puntúa** de 0 a 100 con pesos visibles y **explica** el resultado.
3. Reclutamiento revisa el ranking, agrega notas y **envía al jefe de área** los mejores candidatos.
4. El **jefe de área** ve candidatos anonimizados con su explicación y decide: entrevistar, en espera o descartar.
5. Ambos perfiles responden el **SUS** dentro del sistema; el perfil de investigación descarga el CSV.

## Novedades de la versión 1.2 (multiempresa y portal del postulante)
- **Multiempresa:** el perfil de investigación registra empresas y crea las cuentas de su personal de reclutamiento y de sus jefes de área. Cada empresa solo ve sus vacantes y candidatos.
- **Portal del postulante** (`/empleos`, sin iniciar sesión): ve las vacantes publicadas, postula con sus datos, su CV y el consentimiento, y consulta su estado con un **código de seguimiento** (no se envían correos). Puede eliminar su postulación.
- **Evaluación automática** al recibir cada postulación (el ranking se recalcula con cada una).
- **Privacidad:** el CV se anonimiza antes de evaluarse. El personal de reclutamiento ve el contacto del postulante; el jefe de área ve solo el código.
- Las vacantes se publican en el portal con una casilla al crearlas o editarlas (las existentes quedan sin publicar).
- Las bases de la versión anterior se migran solas: los usuarios y vacantes existentes pasan a la «Empresa de práctica».

## Novedades de la versión 1.1 (cierre de brechas de la ERS)
- **Consentimiento al cargar CV** (RF-08): casilla obligatoria; queda registrada en el registro de auditoría.
- **Editar y cerrar vacantes** (RF-06) y **exportar el ranking a CSV** (RF-20).
- **Tarea guiada** (RF-24): cada participante ve sus pasos en *Inicio*; el SUS se habilita al completarlos (`SUS_REQUIRE_TASK=1`). Reclutamiento puede descargar 10 CV de práctica.
- **Escenario para jefes de área** (RF-25): en *Participantes* > *Preparar escenario* se crea, para cada jefe, una vacante de práctica con una lista corta de 5 candidatos ya generada.
- **Registro de auditoría** (RF-26): menú *Auditoría* del perfil de investigación.
- Solo se aceptan CV en PDF, DOCX o TXT (RF-07). Las bases creadas con versiones anteriores se migran solas al iniciar.

## Instalación rápida
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # Windows: copy .env.example .env
python -m scripts.seed --demo                          # crea usuarios y una vacante de ejemplo (anota las contraseñas)
uvicorn app.main:app --reload
```
Abre http://127.0.0.1:8000 e ingresa con `reclutadora@localmatch.local` o `jefe@localmatch.local`.

Pruebas: `python -m pytest -q`

## Modelo de lenguaje (opcional)
| `LLM_PROVIDER` | Qué hace | Privacidad |
|---|---|---|
| `mock` (por defecto) | Extracción por reglas + similitud TF-IDF. Sin internet. | Todo queda en tu equipo |
| `ollama` | Modelo local (`ollama pull llama3.1:8b`) | Todo queda en tu equipo |
| `anthropic` | API de Claude (`ANTHROPIC_API_KEY`) | Salen los CV ya anonimizados |

El **puntaje lo calcula siempre código determinista** (auditable); el modelo solo ayuda a reconocer sinónimos y a redactar la explicación.

## Estructura
```
app/main.py            rutas y perfiles de acceso
app/skills/            skills del agente: redact → extract → score → explain (pipeline.py las une)
app/sus.py             cálculo del puntaje SUS y categorías
app/templates, static  interfaz
scripts/seed.py        usuarios iniciales y datos de demostración
scripts/create_users.py cuentas para los 30 + 30 participantes del estudio
analysis/sus_analysis.py  Shapiro-Wilk, Levene y t de Welch / Mann-Whitney
docs/PIPELINE.md       cómo construirlo por sprints, y cómo desplegarlo
```

## Base de datos
Sin configurar nada usa **SQLite** (archivo local). Si defines `DATABASE_URL` usa **PostgreSQL**, que es lo que debes usar al desplegar. Las pruebas corren con ambos motores.

## Despliegue
Ver `docs/DESPLIEGUE.md` (GitHub → pruebas automáticas → Render → PostgreSQL).

## Estudio SUS (60 usuarios)
```bash
python -m scripts.create_users --role reclutador --count 30
python -m scripts.create_users --role jefe --count 30
```
En producción puedes crear las cuentas desde la web (menú *Participantes* del perfil de investigación). Cada participante entra, usa el sistema en una tarea real y responde `/sus`. Luego, con el usuario `admin`, descarga `/admin/sus.csv` y ejecuta:
```bash
python analysis/sus_analysis.py sus_respuestas.csv
```

## Límites conocidos
- La anonimización por reglas puede dejar pasar datos con formatos poco comunes; revisa los CV antes de usar con datos reales.
- El agente **no decide**: ordena y explica. Toda decisión final es humana.
- Los CV reales son datos personales (Ley N.° 29733 y su reglamento): pide consentimiento y usa el botón de eliminar al terminar.

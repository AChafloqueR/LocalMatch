# LocalMatch

Agente de apoyo a la preselección y ranking de candidatos, con **supervisión humana**, pensado para empresas de Trujillo.
Incluye perfiles diferenciados (reclutamiento / jefe de área / investigación) y un módulo para aplicar el cuestionario **SUS** del estudio.

## Qué hace
1. **Reclutamiento** crea una vacante (requisitos obligatorios y deseables, años mínimos) y sube CV en PDF, DOCX o TXT.
2. El agente **anonimiza** cada CV, **extrae** su perfil, **puntúa** de 0 a 100 con pesos visibles y **explica** el resultado.
3. Reclutamiento revisa el ranking, agrega notas y **envía al jefe de área** los mejores candidatos.
4. El **jefe de área** ve candidatos anonimizados con su explicación y decide: entrevistar, en espera o descartar.
5. Ambos perfiles responden el **SUS** dentro del sistema; el perfil de investigación descarga el CSV.

## Instalación rápida
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # Windows: copy .env.example .env
python -m scripts.seed --demo                          # crea usuarios y una vacante de ejemplo (anota las contraseñas)
uvicorn app.main:app --reload
```
Abre http://127.0.0.1:8000 e ingresa con `reclutadora@localmatch.local` o `jefe@localmatch.local`.

Pruebas: `pytest -q`

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

## Estudio SUS (60 usuarios)
```bash
python -m scripts.create_users --role reclutador --count 30
python -m scripts.create_users --role jefe --count 30
```
Cada participante entra, usa el sistema en una tarea real y responde `/sus`. Luego, con el usuario `admin`, descarga `/admin/sus.csv` y ejecuta:
```bash
python analysis/sus_analysis.py sus_respuestas.csv
```

## Límites conocidos
- La anonimización por reglas puede dejar pasar datos con formatos poco comunes; revisa los CV antes de usar con datos reales.
- El agente **no decide**: ordena y explica. Toda decisión final es humana.
- Los CV reales son datos personales (Ley N.° 29733 y su reglamento): pide consentimiento y usa el botón de eliminar al terminar.

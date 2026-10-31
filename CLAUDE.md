# CLAUDE.md · contexto para Claude Code

Proyecto: **LocalMatch**, agente de preselección y ranking de candidatos con supervisión humana (curso Negocios Centrados en la IA, UPAO, Trujillo 2026).
El producto se evalúa con el cuestionario SUS por dos grupos de usuarios: personal de reclutamiento y jefes de área (n = 30 por grupo).

## Stack
Python 3.12 · FastAPI · Jinja2 · SQLite (sqlite3 puro) · CSS propio sin frameworks. Sin dependencias para el LLM (urllib).

## Comandos
- Instalar: `pip install -r requirements-dev.txt`
- Ejecutar: `uvicorn app.main:app --reload`
- Pruebas: `pytest -q`  (deben pasar antes de cada commit)
- Datos de demo: `python -m scripts.seed --demo`

## Reglas del proyecto
- Interfaz y textos **en español**, claros y sin jerga. Diseño simple: tarjetas, mucho espacio, un solo color de acento.
- El **puntaje lo calcula código determinista** (`app/skills/score.py`). El LLM nunca fija el puntaje.
- Los CV se **anonimizan** antes de guardarse y antes de enviarse a cualquier LLM. El jefe de área nunca ve el nombre del archivo.
- Cada perfil solo accede a lo suyo (`require()` en `app/auth.py`). No relajar permisos.
- Cada cambio nuevo lleva prueba en `tests/`.
- Git: ramas `feature/<tema>`, commits pequeños en español, pull request con revisión de un compañero antes de fusionar en `main`.
- No subir `.env`, bases de datos ni `credenciales_*.csv`.

## Mapa
- `app/skills/` = las "skills" del agente (redact → extract → score → explain), orquestadas en `pipeline.py`.
- `app/sus.py` = fórmula SUS: ítems impares (r − 1), pares (5 − r), suma × 2,5. Categorías: >80,3 excelente; 68–80,3 bueno; 51–67 marginal; <51 no aceptable.

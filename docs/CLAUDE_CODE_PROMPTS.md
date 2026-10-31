# Prompts para Claude Code

Instalación y uso:
```bash
npm install -g @anthropic-ai/claude-code
cd localmatch
claude            # inicia sesión la primera vez
```
Claude Code lee `CLAUDE.md` automáticamente. Pega los prompts de a uno y revisa los cambios antes de aceptar.

**1 · Orientación**
> Lee CLAUDE.md, README.md y la carpeta app/. Ejecuta `pytest -q` y dime en 5 líneas cómo está estructurado el proyecto y si algo falla.

**2 · Mejorar la interfaz (diseño bonito, claro, sencillo)**
> Revisa app/static/style.css y las plantillas. Mantén un solo color de acento, mucho espacio en blanco y textos cortos en español. Mejora la jerarquía visual del ranking (puesto, puntaje, motivo) y la versión móvil. No agregues frameworks. Ejecuta las pruebas.

**3 · Skills del agente con un LLM real**
> En app/skills/extract.py y explain.py el proveedor `ollama` ya está conectado. Prueba con LLM_PROVIDER=ollama y el modelo llama3.1:8b sobre los CV de samples/. Compara los resultados con el modo mock en una tabla y propón ajustes de prompt sin cambiar el cálculo del puntaje.

**4 · Pruebas**
> Agrega pruebas en tests/ para: carga de PDF y DOCX, anonimización de teléfonos y DNI con formatos variados, y permisos (un jefe no puede ver vacantes de otro jefe). Ejecuta `pytest -q`.

**5 · Despliegue**
> Prepara el despliegue en Render con el Dockerfile existente: verifica que DB_PATH sea configurable, que HTTPS_ONLY=1 funcione y agrega un endpoint /health. Escribe los pasos exactos en docs/PIPELINE.md.

**6 · Documentación del informe**
> Genera docs/manual_usuario.md (máximo 1 página por perfil, con pasos numerados) y docs/matriz_pruebas.md con columnas: caso, perfil, pasos, resultado esperado, resultado obtenido.

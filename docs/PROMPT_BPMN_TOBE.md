# Prompt para generar el diagrama BPMN TO-BE de LocalMatch

Pegar este prompt en la IA de preferencia, copiar el XML resultante e importarlo
en <https://demo.bpmn.io> para exportar el diagrama como SVG/PNG.

---

```text
Actúa como analista de procesos de negocio, experto en BPMN 2.0. Necesito que
modeles el proceso TO-BE del sistema "LocalMatch" y me entregues el resultado
como XML BPMN 2.0 válido e importable en bpmn.io (https://demo.bpmn.io), con
la sección BPMNDiagram/BPMNPlane (coordenadas) incluida para que se visualice
ordenado sin retoques. Todas las etiquetas en español claro, sin jerga técnica.

# Contexto del producto
LocalMatch es una aplicación web de preselección y ranking de candidatos con
supervisión humana. Un agente de IA evalúa CVs de forma automática, pero el
puntaje lo calcula código determinista y la decisión final siempre es humana.
El proceso TO-BE representa el proceso de selección CON LocalMatch ya operativo
(en contraste con el proceso AS-IS manual de leer CVs uno por uno).
El sistema se evalúa con el cuestionario SUS aplicado a dos perfiles: personal
de reclutamiento y jefes de área.

# Estructura del diagrama
Un solo pool llamado "LocalMatch – Preselección de candidatos" con 3 lanes:
  1. Reclutador
  2. Sistema LocalMatch (agente de IA)
  3. Jefe de área
Opcional: un pool externo "Proveedor LLM (Ollama / API Anthropic)" conectado
SOLO con message flows hacia el lane del sistema. Si lo incluís, recordá que
sequence flows nunca cruzan pools.

# Flujo que debés modelar (no inventes pasos adicionales)

EVENTO DE INICIO: "Se necesita cubrir una vacante".

Lane Reclutador:
1. Tarea de usuario "Registrar vacante y asignar jefe de área": define título,
   área, descripción, requisitos excluyentes (must), requisitos deseables
   (nice), años mínimos de experiencia y el jefe responsable.
2. Tarea de usuario "Cargar CVs de postulantes" (hasta 40 archivos, máx. 5 MB
   cada uno, PDF/DOCX/TXT).

Lane Sistema LocalMatch (por cada CV cargado):
3. Tarea de servicio "Extraer texto del CV".
4. Gateway exclusivo "¿CV legible y con contenido suficiente?".
   - NO: evento de fin "CV rechazado: no se pudo leer" (se informa al
     reclutador cuántos fallaron; el resto continúa).
   - SÍ: continuar.
5. Tarea de servicio "Anonimizar CV (eliminar datos personales)". REGLA
   OBLIGATORIA: ocurre ANTES de guardar y ANTES de cualquier llamada al LLM.
6. Tarea de servicio "Almacenar CV anonimizado" (objeto de datos: "CV
   anonimizado").
7. Cuando el reclutador lo solicita (tarea de usuario en su lane "Ejecutar
   evaluación del agente"), subproceso expandido "Evaluar candidatos" con
   multi-instancia en paralelo (un ciclo por cada CV de la vacante):
   a. "Calcular similitud texto-vacante (TF-IDF)".
   b. "Extraer perfil estructurado del candidato".
      Gateway "¿Proveedor LLM disponible?": SÍ -> "Apoyarse en LLM con texto
      anonimizado" (message flow al pool externo si lo incluís); NO ->
      "Aplicar método por reglas". Ambos caminos se reúnen.
   c. "Calcular puntaje con código determinista" (REGLA OBLIGATORIA: el LLM
      nunca fija el puntaje).
   d. "Generar explicación legible del puntaje".
   e. "Guardar perfil, puntaje, desglose y explicación" (objetos de datos:
      "Perfil estructurado", "Puntaje y desglose", "Explicación").
8. Tarea de servicio "Ordenar candidatos por puntaje (ranking)".

Lane Reclutador:
9. Tarea de usuario "Revisar ranking y explicaciones".
10. Tarea de usuario "Preseleccionar candidatos (shortlist) y agregar notas".
    Puede también eliminar CVs o re-ejecutar la evaluación (flujo de retorno
    a la tarea 7 si lo querés mostrar como bucle).
11. Enviar message flow "Shortlist disponible" hacia el lane Jefe de área
    (no hay correo automático: el jefe ingresa a su panel).

Lane Jefe de área:
12. Tarea de usuario "Revisar candidatos preseleccionados". REGLAS: solo ve
    los CV preseleccionados de SUS vacantes asignadas, ordenados por puntaje,
    y NUNCA ve el nombre del archivo ni datos personales.
13. Tarea de usuario "Registrar decisión por candidato" con comentario
    opcional, seguida de gateway exclusivo con 3 salidas: "Entrevistar",
    "En espera", "Descartar" (objeto de datos: "Decisión del jefe").
14. EVENTO DE FIN: "Candidatos con decisión registrada" (las entrevistas
    posteriores quedan FUERA del alcance del sistema).

# Subproceso independiente: evaluación SUS (modelar aparte o al final)
1. Inicio: "Usuario completa su experiencia con el sistema".
2. Tarea de usuario "Responder cuestionario SUS (10 ítems) y aceptar
   consentimiento informado" (reclutador o jefe).
3. Gateway "¿Ítems completos, consentimiento aceptado y sin respuesta previa?".
   NO -> fin "Evaluación no registrada (volver a intentar)".
   SÍ -> tarea de servicio "Calcular puntaje SUS (0-100) y categoría".
4. Tarea de usuario (Administrador) "Analizar resultados por perfil y exportar
   CSV anonimizado". Fin: "Resultados listos para la investigación".

# Reglas de negocio que el diagrama DEBE dejar explícitas (como notas)
- El puntaje lo calcula código determinista; el LLM solo apoya en extracción y
  explicación, y si falla, el sistema usa reglas.
- El sistema recomienda; el humano decide (reclutador preselecciona, jefe decide).
- Anonimización antes de guardar y antes de enviar texto a cualquier LLM.
- Cada perfil solo accede a sus propias vacantes (control de acceso).

# Requisitos de calidad del entregable
- Tipos de elemento correctos: tareas de usuario para personas, tareas de
  servicio para el sistema, gateways exclusivos con condiciones escritas en las
  compuertas y en los flujos de salida, eventos de inicio y fin nombrados.
- Usá sequence flows dentro del pool y message flows solo entre pools.
- No agregues funcionalidades que no estén en este prompt (no hay notificaciones
  por correo, ni entrevistas dentro del sistema, ni publicación de vacantes).
- Si no podés generar el XML completo con coordenadas, entregá la lista
  estructurada de elementos y conexiones para dibujarlo manualmente en bpmn.io.
```

---

**Notas de uso**

- Si el XML llega roto o desordenado, el final del prompt ya prevé el plan B
  (lista estructurada para dibujarlo a mano en bpmn.io).
- La evaluación SUS se modela como subproceso aparte porque mide el producto,
  no al candidato; las entrevistas quedan fuera del alcance porque el sistema
  termina en la decisión del jefe.

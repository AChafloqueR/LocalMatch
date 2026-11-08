"""Catálogo de plantillas de convocatoria y lista de distritos."""

DISTRICTS = [
    # Provincia de Trujillo
    "Trujillo", "El Porvenir", "Florencia de Mora", "Huanchaco", "La Esperanza", "Laredo", "Moche", "Poroto", "Salaverry", "Simbal", "Víctor Larco Herrera",
    # Otras ciudades y distritos de La Libertad
    "Virú", "Chao", "Guadalupe", "Chepén", "Pacasmayo", "San Pedro de Lloc", "Ascope", "Casa Grande", "Chocope", "Paiján", "Santiago de Cao",
    "Otuzco", "Huamachuco", "Santiago de Chuco", "Cascas", "Pacanga",
]
OTHER = "Otro"

KINDS = {"herramienta": "Herramienta o habilidad", "formacion": "Formación", "certificacion": "Certificación", "idioma": "Idioma"}


def R(name, kind, weight, mandatory=False, syn=""):
    return {"name": name, "kind": kind, "weight": weight, "mandatory": mandatory, "synonyms": [s.strip() for s in syn.split("|") if s.strip()]}


TEMPLATES = [
    {"slug": "ing-sistemas", "title": "Ingeniero/a de Sistemas", "area": "Tecnologías de la información", "min_years": 2,
     "description": "Desarrollar y mantener aplicaciones, administrar bases de datos y dar soporte técnico a las áreas de la empresa.",
     "items": [R("Ingeniería de Sistemas", "formacion", 4, True, "Ingeniería Informática|Ing. de Sistemas|Ciencias de la Computación|Ingeniería de Software"),
               R("SQL", "herramienta", 4, True), R("Python", "herramienta", 4), R("Git", "herramienta", 3), R("Scrum", "herramienta", 2, False, "metodologías ágiles"),
               R("Inglés", "idioma", 2), R("PSM I", "certificacion", 2, False, "Professional Scrum Master|CSM")],
     "questions": [("¿Tienes disponibilidad inmediata?", False)]},
    {"slug": "analista-datos", "title": "Analista de datos", "area": "Operaciones", "min_years": 1,
     "description": "Analizar datos de ventas y logística, construir reportes y tableros para la gerencia.",
     "items": [R("SQL", "herramienta", 5, True), R("Excel", "herramienta", 4, True, "hojas de cálculo|tablas dinámicas"), R("Power BI", "herramienta", 4, True, "PowerBI"),
               R("Python", "herramienta", 3), R("Estadística", "formacion", 2, False, "estadístico|estadísticas"), R("Inglés", "idioma", 2)],
     "questions": [("¿Tienes disponibilidad inmediata?", False)]},
    {"slug": "asistente-contable", "title": "Asistente contable", "area": "Administración y finanzas", "min_years": 1,
     "description": "Registrar operaciones contables, preparar declaraciones tributarias y apoyar el cierre mensual.",
     "items": [R("Contabilidad", "formacion", 4, True, "Contador|Técnico en contabilidad|Contable|Ciencias Contables"), R("Excel", "herramienta", 4, True, "hojas de cálculo"),
               R("SUNAT", "herramienta", 4, True, "PDT|declaraciones tributarias|PLAME"), R("Facturación electrónica", "herramienta", 3, False, "comprobantes electrónicos"),
               R("SAP", "herramienta", 2, False, "ERP|Concar|Siscont")],
     "questions": [("¿Tienes disponibilidad inmediata?", False)]},
    {"slug": "practicante-derecho", "title": "Practicante de Derecho", "area": "Asesoría legal", "min_years": 0,
     "description": "Apoyar al equipo legal en la revisión de contratos, redacción de documentos y seguimiento de expedientes.",
     "items": [R("Derecho", "formacion", 5, True, "Abogacía|Ciencias Jurídicas|Estudiante de Derecho"), R("Redacción", "herramienta", 3, False, "redacción jurídica|redacción de documentos"),
               R("Word", "herramienta", 2, False, "Microsoft Word"), R("Normativa laboral", "herramienta", 2, False, "legislación laboral|derecho del trabajo"), R("Inglés", "idioma", 1)],
     "questions": [("¿Estás cursando los últimos ciclos de la carrera?", True), ("¿Tienes disponibilidad en horario de mañana?", False)]},
    {"slug": "ing-mecanico", "title": "Ingeniero/a Mecánico", "area": "Mantenimiento y planta", "min_years": 2,
     "description": "Planificar el mantenimiento de equipos, supervisar intervenciones y proponer mejoras de confiabilidad.",
     "items": [R("Ingeniería Mecánica", "formacion", 4, True, "Ing. Mecánico|Mecánica"), R("Mantenimiento", "herramienta", 4, True, "mantenimiento preventivo|mantenimiento correctivo"),
               R("AutoCAD", "herramienta", 4), R("SolidWorks", "herramienta", 3), R("Colegiatura", "certificacion", 2, False, "CIP|colegiado"), R("Inglés", "idioma", 1)],
     "questions": [("¿Cuentas con colegiatura vigente?", False), ("¿Puedes trabajar en turnos rotativos?", False)]},
    {"slug": "asistente-administrativo", "title": "Asistente administrativo", "area": "Administración", "min_years": 1,
     "description": "Gestionar documentos, atender a clientes y proveedores, y apoyar las tareas administrativas diarias.",
     "items": [R("Administración", "formacion", 3, False, "Gestión empresarial|Secretariado"), R("Excel", "herramienta", 3, True, "hojas de cálculo"),
               R("Atención al cliente", "herramienta", 3, True), R("Redacción", "herramienta", 2), R("Archivo", "herramienta", 2, False, "gestión documental|archivo de documentos")],
     "questions": [("¿Tienes disponibilidad inmediata?", False)]},
    {"slug": "asesor-comercial", "title": "Asesor/a comercial", "area": "Comercial", "min_years": 1,
     "description": "Captar y atender clientes, cerrar ventas y mantener la relación con la cartera asignada.",
     "items": [R("Ventas", "herramienta", 5, True, "venta|asesor de ventas|ejecutivo de ventas|vendedor"), R("Atención al cliente", "herramienta", 4), R("CRM", "herramienta", 3, False, "Salesforce|HubSpot"),
               R("Negociación", "herramienta", 2)],
     "questions": [("¿Tienes disponibilidad para visitas a clientes?", False)]},
]


def template(slug: str):
    return next((t for t in TEMPLATES if t["slug"] == slug), None)

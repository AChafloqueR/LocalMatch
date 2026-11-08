# Despliegue de LocalMatch (GitHub + Render + PostgreSQL)

Resultado: una URL pública `https://localmatch.onrender.com` (o `localmatch-xxxx` si el nombre está ocupado),
con base de datos PostgreSQL persistente y pruebas automáticas en cada push.

```
tu laptop ──push──▶ GitHub ──▶ Actions (pruebas SQLite + PostgreSQL)
                        │                 │ si pasan
                        └──────────────▶ Render (Docker) ──▶ PostgreSQL (Supabase o Neon)
```

## 1. Base de datos (elige una)
**Supabase**: New project → región *South America (São Paulo)* → crea una contraseña (guárdala) →
botón **Connect** → cadena **Session pooler** → copia la URL (`postgresql://postgres.xxxx:[PASSWORD]@...pooler.supabase.com:5432/postgres`).
Reemplaza `[PASSWORD]` por tu contraseña (si tiene símbolos como @ # / :, codifícalos: @=%40, #=%23, /=%2F, :=%3A).
Nota: los proyectos gratuitos de Supabase se pausan tras 7 días sin actividad; si pasa, pulsa *Restore*.

**Neon** (alternativa): New project → copia la *connection string*. Los datos persisten aunque el cómputo se suspenda.

## 2. GitHub
```bash
cd localmatch
git init
git add .
git commit -m "LocalMatch: version inicial"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/localmatch.git
git push -u origin main
```
Antes crea el repositorio vacío `localmatch` en github.com (sin README). Al subir, en la pestaña **Actions** verás correr las pruebas.

## 3. Render
1. render.com → **New → Blueprint** → conecta tu GitHub → elige el repo `localmatch`. Lee `render.yaml`.
2. Render pedirá tres valores: `DATABASE_URL` (paso 1), `ADMIN_EMAIL` y `ADMIN_PASSWORD` (los que usarás para entrar).
3. **Apply**. Espera 3–5 minutos. La URL aparece arriba del servicio.
4. Comprueba `https://<tu-url>/health` → debe responder `{"ok":true,...}`.

`autoDeployTrigger: checksPass` hace que Render despliegue solo cuando las pruebas de GitHub pasan.
Verifícalo en Render → Settings → Build & Deploy → Auto-Deploy → *After CI Checks Pass*.

## 4. Primer uso en producción
1. Entra con `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
2. **Empresas y participantes**: crea una cuenta de reclutamiento y una de jefe de área (para probar), y luego en lote las de los 30 + 30 del estudio (descarga el CSV con las contraseñas).
3. **Preparar escenario:** en *Participantes*, pulsa *Preparar escenario* después de crear las cuentas de jefes de área (cada jefe recibe su vacante de práctica con lista corta).
4. Ingresa como reclutamiento → crea una vacante → sube CV → ejecuta el agente.
5. Los participantes completan su tarea (en *Inicio*) y luego responden el SUS en `/sus`. Tú descargas `/admin/sus.csv` y corres `analysis/sus_analysis.py`.

## Cosas que debes saber
- **Plan gratuito de Render:** el servicio se "duerme" tras 15 minutos sin visitas y tarda ~50 segundos en despertar. Antes de cada sesión del estudio, abre la URL unos minutos antes.
- **Datos personales:** los CV se guardan anonimizados en la base de datos en la nube. Pide consentimiento, borra los CV al terminar (botón *Eliminar todos los CV*) y no subas CV reales sin autorización.
- **Contraseñas:** nunca las pongas en el código ni en GitHub. Solo en las variables de entorno de Render.
- **Si cambias el código:** `git add . && git commit -m "mensaje" && git push`. GitHub corre las pruebas y Render despliega si pasan.

## Versión 1.2: pasos tras actualizar
1. Sube los cambios (`git add .`, `git commit`, `git push`). Al iniciar, la base de Supabase se migra sola.
2. Entra como investigación > *Empresas y participantes* > **Registrar una empresa** y crea sus cuentas (en lote o una por una).
3. Entra como reclutamiento de esa empresa, crea una vacante y deja marcada la casilla de publicarla.
4. Abre `/empleos` en una ventana privada, postula con un CV y guarda el código; luego revisa el estado en `/postulacion/<código>`.
5. Pulsa **Preparar escenario** para que cada jefe de área reciba su lista corta de práctica.

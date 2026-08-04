# Monitor de precios (MX) — ROG Xbox Ally X & Legion Go S SteamOS

Job automático que corre en **GitHub Actions** (sin tu computadora prendida),
consulta precios cada 3 días durante agosto 2026 y te envía un resumen a
**Telegram**. Guarda un log acumulado para el resumen de fin de mes.

## Qué monitorea

1. **ASUS ROG Xbox Ally X** (flagship: Z2 Extreme, 24GB, 1TB). Descarta el modelo base.
2. **Lenovo Legion Go S — edición SteamOS**. Descarta la versión Windows.

Fuentes: **SerpApi** (Google Shopping MX, principal) + **Playwright** (Cyberpuerta, PCEL).

---

## Puesta en marcha (una sola vez)

### 1. Crear el repositorio
- Crea un repo nuevo en GitHub (puede ser **privado**).
- Sube estos archivos manteniendo la estructura:

```
monitor.py
requirements.txt
README.md
.gitignore
.github/workflows/monitor.yml
```

### 2. Conseguir la API key de SerpApi (gratis)
- Entra a https://serpapi.com y crea una cuenta.
- En el dashboard copia tu **API Key** (el plan gratis da 100 búsquedas/mes;
  este monitor usa ~4 por corrida, de sobra).

### 3. Cargar los 3 secrets
En el repo: **Settings → Secrets and variables → Actions → New repository secret**.
Crea estos tres:

| Nombre              | Valor                                             |
|---------------------|---------------------------------------------------|
| `TELEGRAM_TOKEN`    | `8842952085:AAG1qUJMPakcAscStSf8Cb_E5BOSSV35zcA`  |
| `TELEGRAM_CHAT_ID`  | `335273511`                                        |
| `SERPAPI_KEY`       | tu API key de SerpApi                              |

> El token y el chat_id ya son los tuyos (validados). El token es secreto:
> guárdalo solo como secret, nunca en el código.

### 4. Probar
- Ve a la pestaña **Actions → Monitor de precios → Run workflow**
  (esto lo dispara manualmente sin esperar al horario).
- En 1–2 min deberías recibir el mensaje en Telegram.

---

## Programación

El workflow corre solo los días **1, 4, 7, 10, 13, 16, 19, 22, 25, 28 y 31 de
agosto** a las 15:00 UTC (~9–10 AM hora del centro de México). Cambia el `cron`
en `.github/workflows/monitor.yml` si quieres otro horario o frecuencia.

El **31 de agosto** el mensaje incluye el resumen final del mes y avisa que la
tarea ya puede desactivarse (borra el repo o deshabilita el workflow).

## Ajustes útiles

- **Precio oficial de referencia:** en `monitor.py`, edita el diccionario
  `OFFICIAL_PRICE` cuando confirmes el precio de lista oficial (ASUS/Xbox/Lenovo).
  Si lo dejas en `None`, se usa la mediana de mercado como referencia y se marca.
- **Precio objetivo:** ya calcula el rango 75–80% de la mediana (20–25% de
  descuento). Cuando el mejor precio baja del 80%, el mensaje encabeza con
  **✅ OBJETIVO ALCANZADO**.
- **Más tiendas por scraping:** agrega entradas a `PLAYWRIGHT_STORES`.

## Limitaciones (honestas)

- Los precios de Google Shopping son **de lista**; envío e impuestos pueden
  variar. El script lo aclara en cada mensaje.
- Los selectores de Playwright (Cyberpuerta/PCEL) son *best-effort*; si una
  tienda cambia su HTML, esa fuente puede fallar sin romper el resto. Google
  Shopping (SerpApi) es la fuente confiable.
- No se realiza ninguna compra ni apartado. Solo monitorea y avisa.

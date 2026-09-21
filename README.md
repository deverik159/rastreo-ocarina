# Rastreador de preventa · Ocarina of Time (Nintendo Switch 2)

Revisa cada 10 minutos las fichas del juego en tiendas en línea de México y te avisa por
Telegram **sólo cuando algo cambia**: agotado → disponible (alerta), disponible → agotado,
sólo revendedores, o cuando una tienda lleva demasiadas revisiones sin poder leerse.
Además manda un resumen diario para que sepas que sigue vivo.

Se combina con una **tarea programada de Claude** (ver `tarea_claude.md`) que hace la
revisión amplia: tiendas nuevas, noticias de restock y Mercado Libre.

## Archivos

| Archivo | Para qué |
|---|---|
| `rastreador.py` | El script. Descarga cada ficha, la clasifica, compara con `estado.json` y avisa. |
| `tiendas.json` | Tiendas, URLs y reglas de detección. **Es el único archivo que normalmente editas.** |
| `estado.json` | Último estado por tienda. Lo actualiza el workflow con un commit; no lo edites a mano. |
| `.github/workflows/rastreo.yml` | Cron cada 10 min + ejecución manual. |
| `pruebas.py` | Pruebas de la clasificación con HTML sintético (`python pruebas.py`). |
| `tarea_claude.md` | Prompt y pasos para la tarea programada de Claude (opción 1). |

## Puesta en marcha (unos 15 minutos)

1. **Bot de Telegram.** En Telegram habla con `@BotFather` → `/newbot` → copia el token.
   Escríbele cualquier cosa a tu bot nuevo y luego abre en el navegador
   `https://api.telegram.org/bot<TOKEN>/getUpdates`: el número en `"chat":{"id":…}` es tu
   `TELEGRAM_CHAT_ID`.
2. **Repositorio.** Crea un repo en GitHub y sube estos archivos. Recomendación: **público**.
   El código no tiene nada sensible (el token va en Secrets) y en repos públicos los minutos
   de Actions son ilimitados. En un repo privado con plan Free tienes 2,000 min/mes; a
   10 min de cadencia son ~4,300 corridas al mes y cada una cobra al menos 1 min, así que
   te quedarías sin minutos a mitad de mes (cada 30 min sí cabe).
3. **Secrets.** Settings → Secrets and variables → Actions → New repository secret:
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
4. **Permiso de escritura.** Settings → Actions → General → Workflow permissions →
   *Read and write permissions* (para que el workflow pueda hacer commit de `estado.json`).
5. **Primera corrida.** Actions → *Rastreo de preventa* → *Run workflow* → marca `resumen`.
   Debes recibir el resumen en Telegram en menos de un minuto. La pestaña *Summary* de la
   corrida muestra una tabla con el estado de cada tienda.
6. A partir de ahí corre solo. Para pausarlo: Actions → el workflow → *Disable workflow*.

## Estados posibles

| Estado | Significado | ¿Avisa? |
|---|---|---|
| `disponible` | Hay botón de reservar / agregar al carrito | 🟢 Alerta al entrar en este estado |
| `agotado` | La tienda dice agotado / no disponible | Aviso si venía de `disponible` |
| `terceros` | Sólo vendedores externos (Amazon "Ver opciones de compra") | Aviso con el precio, para que juzgues |
| `bloqueado` | HTTP 403/429/5xx o captcha | Aviso tras 12 seguidos (~2 h) |
| `desconocido` | Cargó pero no reconoció señales | Aviso tras 12 seguidos |
| `sin_ficha` | HTTP 404 | Aviso tras 12 seguidos |
| `error` | Falla de red / motor | Aviso tras 12 seguidos |

## Completar y afinar tiendas

`tiendas.json` trae Amazon México y Coppel activas con URL real. Mercado Libre, Gameplanet,
Liverpool y Walmart están **inactivas con URL vacía** porque la ficha no existía o no pude
obtener la URL exacta: cuando la tengas (la tarea de Claude te la dará), pégala en `url`
y pon `"activa": true`.

Para afinar las reglas de una tienda:

```bash
pip install -r requirements.txt
python rastreador.py --solo coppel --dump --dry-run   # guarda debug/coppel.html
```

Abre el HTML guardado, busca el botón de compra o el mensaje de agotado, y agrega su
selector CSS (`selectores_disponible` / `selectores_agotado`) o su texto
(`texto_disponible` / `texto_agotado`). Si el detalle dice *"la página llegó vacía"*, el
sitio pinta con JavaScript: cambia `"motor": "playwright"` (el workflow lo instala solo
cuando alguna tienda activa lo usa; localmente:
`pip install playwright && playwright install chromium`).

Orden de decisión por tienda: bloqueo → selectores_agotado → selectores_disponible →
texto_agotado → texto_disponible → texto_terceros → desconocido. Los textos se comparan
sin acentos ni mayúsculas, y si defines `selector_zona` sólo se buscan dentro de esos
elementos (evita falsos positivos por carruseles de "otros productos").

## Correrlo también desde tu computadora

Las IPs de GitHub Actions son de centro de datos y **Amazon suele contestarles con
captcha** (verás `bloqueado`). Desde tu casa la IP es residencial y casi nunca bloquea, así
que vale tener las dos cosas. En Linux/macOS, `crontab -e`:

```
*/10 * * * * cd /ruta/rastreo-ocarina && TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy /usr/bin/python3 rastreador.py >> rastreo.log 2>&1
```

En Windows, el Programador de tareas con la misma línea (`python rastreador.py`) cada 10
minutos y las variables definidas en el sistema. Si corres en dos lugares, cada uno lleva
su propio `estado.json`; recibirás la alerta dos veces, que para este caso es aceptable.

## Límites que conviene tener claros

- **Avisa, no compra.** El checkout con tu cuenta y tu pago lo haces tú. Ten la sesión
  iniciada en cada tienda y el método de pago guardado para tardar segundos.
- **El cron de GitHub no es puntual.** Puede retrasarse varios minutos en horas pico y el
  mínimo es cada 5 minutos. Para restocks que duran minutos, la corrida local es más fiable.
- **Las tiendas cambian su HTML.** Si una tienda pasa a `desconocido`, recibirás un aviso
  tras ~2 h; entonces corre `--dump` y ajusta la regla.
- **Sé razonable con la frecuencia.** Cada 10 minutos a dos o tres fichas es un uso
  moderado; no bajes de 5 y no dupliques tiendas innecesariamente.
- **Complementos sin código:** el botón "Avísame cuando esté disponible" de Amazon si la
  ficha lo ofrece, un tracker en Keepa sobre la misma ficha, y una alerta por palabra clave
  en Promodescuentos ("Ocarina of Time").

## Probar cambios al script

```bash
python pruebas.py
```

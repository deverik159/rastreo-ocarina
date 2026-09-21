#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rastreador de preventa · The Legend of Zelda: Ocarina of Time (Nintendo Switch 2)

Revisa las fichas de producto definidas en tiendas.json, clasifica cada una en
un estado (disponible / agotado / terceros / bloqueado / desconocido / sin_ficha
/ error), compara contra estado.json y avisa por Telegram sólo cuando algo
cambia. Pensado para correr cada 10 minutos desde GitHub Actions o desde cron.

Uso:
  python rastreador.py                  # revisa todas las tiendas activas
  python rastreador.py --solo amazon_mx # una sola tienda (por id)
  python rastreador.py --dry-run        # no manda Telegram ni guarda estado
  python rastreador.py --dump           # guarda el HTML de cada tienda en debug/
  python rastreador.py --resumen        # fuerza el envío del resumen (prueba Telegram)

Variables de entorno:
  TELEGRAM_BOT_TOKEN   token del bot (de @BotFather)
  TELEGRAM_CHAT_ID     id del chat que recibe las alertas
  Si faltan, los mensajes sólo se imprimen en consola.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

try:  # lxml es más rápido y tolerante; si no está, usamos el parser estándar
    import lxml  # noqa: F401

    PARSER = "lxml"
except ImportError:  # pragma: no cover
    PARSER = "html.parser"

BASE = Path(__file__).resolve().parent
ARCHIVO_TIENDAS = BASE / "tiendas.json"
ARCHIVO_ESTADO = BASE / "estado.json"
CARPETA_DEBUG = BASE / "debug"
TZ = ZoneInfo("America/Mexico_City")

# Estados que sí dicen algo sobre el producto (los demás son fallas de lectura)
ESTADOS_DEFINITIVOS = {"disponible", "agotado", "terceros"}

EMOJI = {
    "disponible": "🟢",
    "agotado": "🔴",
    "terceros": "🟡",
    "bloqueado": "🟠",
    "desconocido": "⚪",
    "sin_ficha": "⚫",
    "error": "⚠️",
}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
]
HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def ahora() -> datetime:
    return datetime.now(TZ)


def fecha_legible(dt: datetime | None = None) -> str:
    dt = dt or ahora()
    return f"{dt.day} {MESES[dt.month - 1]} {dt.year}, {dt:%H:%M} (hora centro)"


def fecha_corta(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso).astimezone(TZ)
        return f"{dt.day} {MESES[dt.month - 1]} {dt:%H:%M}"
    except ValueError:
        return iso


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados, para comparar textos."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def cargar_json(ruta: Path, por_defecto):
    if not ruta.exists():
        return por_defecto
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def guardar_json(ruta: Path, datos) -> None:
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


def formatear_precio(precio: float | None) -> str:
    return f"${precio:,.2f} MXN" if precio is not None else "precio no detectado"


# --------------------------------------------------------------------------- #
# Descarga de páginas
# --------------------------------------------------------------------------- #
def obtener_html_requests(url: str, timeout: int = 25, intentos: int = 2) -> tuple[int, str]:
    ultimo_error: Exception | None = None
    for i in range(intentos):
        try:
            headers = dict(HEADERS_BASE)
            headers["User-Agent"] = random.choice(USER_AGENTS)
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            return r.status_code, r.text
        except requests.RequestException as e:
            ultimo_error = e
            time.sleep(2 + i * 3)
    raise RuntimeError(f"Error de red: {ultimo_error}")


def obtener_html_playwright(url: str, espera_ms: int = 4000, timeout_ms: int = 45000) -> tuple[int, str]:
    """Para tiendas que arman la página con JavaScript (Liverpool, Walmart, etc.).
    Requiere: pip install playwright && playwright install --with-deps chromium"""
    from playwright.sync_api import sync_playwright  # import tardío: es opcional

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(
            locale="es-MX",
            timezone_id="America/Mexico_City",
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 850},
        )
        pagina = contexto.new_page()
        respuesta = pagina.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        pagina.wait_for_timeout(espera_ms)  # dar tiempo a que el JS pinte el buybox
        html = pagina.content()
        status = respuesta.status if respuesta else 0
        navegador.close()
    return status, html


# --------------------------------------------------------------------------- #
# Clasificación
# --------------------------------------------------------------------------- #
def extraer_texto(soup: BeautifulSoup, selectores: list[str]) -> str | None:
    for sel in selectores:
        nodo = soup.select_one(sel)
        if nodo:
            texto = nodo.get_text(" ", strip=True)
            if texto:
                return texto[:120]
    return None


def extraer_precio(soup: BeautifulSoup, selectores: list[str]) -> float | None:
    for sel in selectores:
        nodo = soup.select_one(sel)
        if not nodo:
            continue
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)", nodo.get_text(" "))
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _coincide(patrones: list[str], texto_normalizado: str) -> str | None:
    for patron in patrones:
        if normalizar(patron) in texto_normalizado:
            return patron
    return None


def evaluar(status: int, html: str, reglas: dict) -> dict:
    """Devuelve {'estado', 'precio', 'vendedor', 'detalle'} a partir del HTML.

    Orden de decisión:
      1. HTTP 404 → sin_ficha; HTTP 403/429/5xx o patrón de bloqueo → bloqueado
      2. selectores_agotado → agotado
      3. selectores_disponible → disponible
      4. texto_agotado → agotado   (sólo dentro de selector_zona, si se definió)
      5. texto_disponible → disponible
      6. texto_terceros → terceros (sólo vendedores externos)
      7. nada de lo anterior → desconocido
    """
    res: dict = {"estado": "desconocido", "precio": None, "vendedor": None, "detalle": ""}

    if status == 404:
        res.update(estado="sin_ficha", detalle="HTTP 404")
        return res
    if status in (403, 429) or status >= 500:
        res.update(estado="bloqueado", detalle=f"HTTP {status}")
        return res

    html_norm = normalizar(html)
    patron = _coincide(reglas.get("bloqueo", []), html_norm)
    if patron:
        res.update(estado="bloqueado", detalle=f"patrón de bloqueo: {patron}")
        return res

    soup = BeautifulSoup(html, PARSER)
    for etiqueta in soup(["script", "style", "noscript", "template"]):
        etiqueta.decompose()

    res["precio"] = extraer_precio(soup, reglas.get("selector_precio", []))
    res["vendedor"] = extraer_texto(soup, reglas.get("selector_vendedor", []))

    for sel in reglas.get("selectores_agotado", []):
        if soup.select_one(sel):
            res.update(estado="agotado", detalle=f"selector {sel}")
            return res
    for sel in reglas.get("selectores_disponible", []):
        if soup.select_one(sel):
            res.update(estado="disponible", detalle=f"selector {sel}")
            return res

    zona = reglas.get("selector_zona")
    if zona:
        nodos = soup.select(zona)
        texto = " ".join(n.get_text(" ") for n in nodos) if nodos else ""
    else:
        texto = soup.get_text(" ")
    texto_norm = normalizar(texto)

    if not texto_norm.strip():
        res.update(detalle="la página llegó vacía (¿render por JavaScript? prueba motor playwright)")
        return res

    patron = _coincide(reglas.get("texto_agotado", []), texto_norm)
    if patron:
        res.update(estado="agotado", detalle=f"texto «{patron}»")
        return res
    patron = _coincide(reglas.get("texto_disponible", []), texto_norm)
    if patron:
        res.update(estado="disponible", detalle=f"texto «{patron}»")
        return res
    patron = _coincide(reglas.get("texto_terceros", []), texto_norm)
    if patron:
        res.update(estado="terceros", detalle=f"texto «{patron}»")
        return res

    res.update(detalle="sin señales reconocibles; revisa los selectores (usa --dump)")
    return res


def revisar_tienda(tienda: dict, dump: bool = False) -> dict:
    url = tienda["url"]
    motor = tienda.get("motor", "requests")
    inicio = time.time()
    try:
        if motor == "playwright":
            status, html = obtener_html_playwright(url)
        else:
            status, html = obtener_html_requests(url)
    except Exception as e:  # red caída, playwright no instalado, etc.
        return {
            "estado": "error",
            "detalle": str(e)[:200],
            "precio": None,
            "vendedor": None,
            "http": None,
            "segundos": round(time.time() - inicio, 1),
        }

    if dump:
        CARPETA_DEBUG.mkdir(exist_ok=True)
        (CARPETA_DEBUG / f"{tienda['id']}.html").write_text(html, encoding="utf-8")

    res = evaluar(status, html, tienda.get("reglas", {}))
    res["http"] = status
    res["segundos"] = round(time.time() - inicio, 1)
    return res


# --------------------------------------------------------------------------- #
# Mensajes
# --------------------------------------------------------------------------- #
def enviar_telegram(texto: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("   (Telegram no configurado; el mensaje sólo se imprime)\n" + texto + "\n")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": texto,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"   Telegram respondió {r.status_code}: {r.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"   Error enviando a Telegram: {e}")
        return False


def mensaje_alerta(tienda: dict, r: dict, tope: float | None) -> str:
    esc = html_lib.escape
    lineas = [
        "🟢 <b>ALERTA: preventa disponible</b>",
        f"<b>{esc(tienda['nombre'])}</b> — {formatear_precio(r['precio'])}",
    ]
    if r.get("vendedor"):
        lineas.append(f"Vendedor: {esc(r['vendedor'])}")
    if tope and r.get("precio") and r["precio"] > tope:
        lineas.append(f"⚠️ Arriba de tu tope de ${tope:,.0f} MXN — revisa que no sea reventa.")
    lineas += [f"👉 {tienda['url']}", fecha_legible()]
    return "\n".join(lineas)


def mensaje_aviso(titulo: str, cuerpo: list[str]) -> str:
    return "\n".join([f"<b>{html_lib.escape(titulo)}</b>", *cuerpo, fecha_legible()])


def mensaje_resumen(cfg: dict, estado: dict, titulo: str) -> str:
    esc = html_lib.escape
    lineas = [f"📋 <b>{esc(titulo)}</b>"]
    for t in cfg["tiendas"]:
        e = estado.get(t["id"])
        if not e:
            continue
        precio = f" · {formatear_precio(e.get('precio'))}" if e.get("precio") else ""
        lineas.append(
            f"{EMOJI.get(e['estado'], '•')} {esc(t['nombre'])}: <b>{e['estado']}</b>"
            f"{precio} (desde {fecha_corta(e.get('desde'))})"
        )
    lineas.append(fecha_legible())
    return "\n".join(lineas)


def escribir_resumen_github(resultados: list[tuple[dict, dict]]) -> None:
    ruta = os.getenv("GITHUB_STEP_SUMMARY")
    if not ruta:
        return
    filas = ["| Tienda | Estado | Precio | HTTP | Detalle |", "|---|---|---|---|---|"]
    for t, r in resultados:
        filas.append(
            f"| {t['nombre']} | {EMOJI.get(r['estado'], '')} {r['estado']} | "
            f"{formatear_precio(r.get('precio'))} | {r.get('http') or '-'} | {r.get('detalle', '')} |"
        )
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(f"## Rastreo · {fecha_legible()}\n\n" + "\n".join(filas) + "\n")


# --------------------------------------------------------------------------- #
# Programa principal
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Rastreador de preventa con alertas por Telegram")
    ap.add_argument("--solo", help="id de una sola tienda (ver tiendas.json)")
    ap.add_argument("--dry-run", action="store_true", help="no envía Telegram ni guarda estado")
    ap.add_argument("--dump", action="store_true", help="guarda el HTML de cada tienda en debug/")
    ap.add_argument("--resumen", action="store_true", help="fuerza el envío del resumen")
    args = ap.parse_args()

    cfg = cargar_json(ARCHIVO_TIENDAS, None)
    if not cfg:
        print(f"No encuentro {ARCHIVO_TIENDAS}")
        return 2
    estado = cargar_json(ARCHIVO_ESTADO, {})
    meta = estado.setdefault("_meta", {})
    tope = cfg.get("precio_maximo_mxn")
    umbral_errores = int(cfg.get("aviso_tras_errores_seguidos", 12))

    tiendas = [t for t in cfg["tiendas"] if t.get("activa", True)]
    if args.solo:
        tiendas = [t for t in tiendas if t["id"] == args.solo]
        if not tiendas:
            print(f"No hay tienda activa con id «{args.solo}»")
            return 2
    sin_url = [t["nombre"] for t in tiendas if not t.get("url")]
    tiendas = [t for t in tiendas if t.get("url")]
    if sin_url:
        print("Omitidas por no tener URL:", ", ".join(sin_url))

    print(f"== Rastreo {fecha_legible()} · {len(tiendas)} tienda(s) · parser {PARSER}")
    ahora_iso = ahora().isoformat(timespec="seconds")
    resultados: list[tuple[dict, dict]] = []
    alertas: list[str] = []
    avisos: list[str] = []

    for i, t in enumerate(tiendas):
        if i:
            time.sleep(random.uniform(1.5, 4.0))  # no martillar a las tiendas
        r = revisar_tienda(t, dump=args.dump)
        resultados.append((t, r))

        previo = estado.get(t["id"], {})
        estado_previo = previo.get("estado")
        nuevo = r["estado"]

        entrada = {
            "estado": nuevo,
            "precio": r.get("precio"),
            "vendedor": r.get("vendedor"),
            "detalle": r.get("detalle", ""),
            "http": r.get("http"),
            "ultima_revision": ahora_iso,
            "desde": ahora_iso if nuevo != estado_previo else previo.get("desde", ahora_iso),
            "errores_seguidos": 0 if nuevo in ESTADOS_DEFINITIVOS else previo.get("errores_seguidos", 0) + 1,
        }

        if nuevo == "disponible" and estado_previo != "disponible":
            alertas.append(mensaje_alerta(t, r, tope))
        elif nuevo == "terceros" and estado_previo != "terceros":
            avisos.append(
                f"🟡 {html_lib.escape(t['nombre'])}: sólo vendedores externos "
                f"({formatear_precio(r.get('precio'))}). Revisa precio antes de comprar.\n{t['url']}"
            )
        elif estado_previo == "disponible" and nuevo in {"agotado", "terceros"}:
            avisos.append(f"🔴 {html_lib.escape(t['nombre'])} volvió a «{nuevo}».")
        elif nuevo not in ESTADOS_DEFINITIVOS and entrada["errores_seguidos"] == umbral_errores:
            avisos.append(
                f"🟠 {html_lib.escape(t['nombre'])} lleva {umbral_errores} revisiones seguidas en "
                f"«{nuevo}» ({html_lib.escape(entrada['detalle'])}). Puede que la tienda esté "
                f"bloqueando el rastreo o que cambió la página."
            )

        estado[t["id"]] = entrada
        print(
            f"[{t['id']:<14}] {EMOJI.get(nuevo, '')} {nuevo:<11} "
            f"{formatear_precio(r.get('precio')):<22} http={r.get('http') or '-'} "
            f"{r.get('segundos', 0)}s · {r.get('detalle', '')}"
        )

    # Resumen diario (una vez al día, a partir de la hora configurada)
    hora_resumen = cfg.get("resumen_diario_hora")
    hoy = ahora().date().isoformat()
    manda_resumen = args.resumen or (
        hora_resumen is not None and meta.get("ultimo_resumen") != hoy and ahora().hour >= int(hora_resumen)
    )

    enviados = 0
    if not args.dry_run:
        for a in alertas:
            enviados += enviar_telegram(a)
        if avisos:
            enviados += enviar_telegram(mensaje_aviso("Aviso del rastreador", avisos))
        if manda_resumen:
            titulo = f"Resumen diario — {cfg.get('producto', 'producto')}"
            if enviar_telegram(mensaje_resumen(cfg, estado, titulo)):
                meta["ultimo_resumen"] = hoy
                enviados += 1
        guardar_json(ARCHIVO_ESTADO, estado)
    else:
        for a in alertas:
            print("[dry-run] alerta:\n" + a)
        for v in avisos:
            print("[dry-run] aviso: " + v)
        if manda_resumen:
            print("[dry-run] resumen:\n" + mensaje_resumen(cfg, estado, "Resumen"))

    escribir_resumen_github(resultados)
    print(f"== Fin · {len(alertas)} alerta(s), {len(avisos)} aviso(s), {enviados} mensaje(s) enviado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

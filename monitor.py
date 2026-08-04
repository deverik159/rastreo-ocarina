#!/usr/bin/env python3
"""
Monitor de precios (MX) para Kaizen.
Productos:
  1) ASUS ROG Xbox Ally X (flagship, Z2 Extreme, 24GB, 1TB)  -> descarta el Ally base
  2) Lenovo Legion Go S edicion SteamOS                       -> descarta la version Windows

Fuentes:
  - SerpApi (Google Shopping MX)  [principal, confiable]
  - Playwright headless           [tiendas puntuales: Cyberpuerta, PCEL]

Salida:
  - Mensaje a Telegram con tabla comparativa + alertas
  - Log acumulado en log/monitor_log.md (para el resumen de fin de mes)

Secrets requeridos (env):
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SERPAPI_KEY
"""

import os
import re
import json
import statistics
import datetime
import urllib.parse
import urllib.request

# ------------------------------------------------------------------ config ---

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()

LOG_PATH = os.path.join("log", "monitor_log.md")

# Ventana de monitoreo
WINDOW_START = datetime.date(2026, 8, 1)
WINDOW_END = datetime.date(2026, 8, 31)

# Precio OFICIAL / de referencia por producto (MXN).
# Ajusta cuando confirmes el precio de lista en la tienda oficial (ASUS/Xbox/Lenovo).
# Si lo dejas en None, el script usa la mediana de mercado como referencia y lo marca.
OFFICIAL_PRICE = {
    "ally_x": None,      # p.ej. 21999.0  (ASUS/Xbox MX)
    "legion_go_s": None, # p.ej. 13999.0  (Lenovo MX)
}

PRODUCTS = {
    "ally_x": {
        "name": "ASUS ROG Xbox Ally X (Z2 Extreme / 24GB / 1TB)",
        "queries": [
            "ASUS ROG Xbox Ally X 1TB",
            "ROG Xbox Ally X Z2 Extreme 24GB",
        ],
        # el titulo debe contener TODOS los grupos (cada grupo = alternativas OR)
        "must_match": [["ally x"]],
        # senales que confirman el flagship (al menos una ayuda, no obligatorio)
        "flagship_hints": ["1tb", "24gb", "z2 extreme", "rc73xa"],
        # si aparece esto y NO hay senal de flagship, se descarta como modelo base
        "base_markers": ["512gb", "16gb", "z2 a"],
        "exclude": ["funda", "case", "carcasa", "protector", "cargador",
                    "mica", "grip", "usado", "reacondicionado", "open box",
                    "caja abierta"],
    },
    "legion_go_s": {
        "name": "Lenovo Legion Go S - SteamOS",
        "queries": [
            "Lenovo Legion Go S SteamOS",
        ],
        "must_match": [["legion go s"], ["steamos", "steam os"]],
        "flagship_hints": [],
        "base_markers": [],
        "exclude": ["windows", "funda", "case", "carcasa", "protector",
                    "cargador", "mica", "usado", "reacondicionado",
                    "open box", "caja abierta"],
    },
}

# Tiendas puntuales para Playwright (busqueda simple). Selectores best-effort.
PLAYWRIGHT_STORES = [
    {
        "store": "Cyberpuerta",
        "url": "https://www.cyberpuerta.mx/Buscar/?q={q}",
        "item_sel": "div.emproduct",
        "title_sel": ".emproduct_right_title",
        "price_sel": ".price",
        "link_sel": "a.emproduct_right_title, a",
    },
    {
        "store": "PCEL",
        "url": "https://pcel.com/busca?query={q}",
        "item_sel": ".product-item, .item",
        "title_sel": ".product-title, .title",
        "price_sel": ".price, .precio",
        "link_sel": "a",
    },
]

# ---------------------------------------------------------------- helpers ----

def log(msg):
    print(f"[monitor] {msg}", flush=True)


def parse_price(text):
    """Extrae un float MXN de un texto tipo '$21,999.00 MXN'."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.findall(r"[\d][\d,\.]*", str(text))
    if not m:
        return None
    raw = m[0]
    # normaliza separadores: quita comas de miles, deja punto decimal
    raw = raw.replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    return val


def norm(s):
    return (s or "").lower()


def title_matches(title, cfg):
    t = norm(title)
    for bad in cfg["exclude"]:
        if bad in t:
            return False
    for group in cfg["must_match"]:
        if not any(alt in t for alt in group):
            return False
    # descarta modelo base si aplica
    if cfg["base_markers"]:
        has_base = any(b in t for b in cfg["base_markers"])
        has_flag = any(f in t for f in cfg["flagship_hints"])
        if has_base and not has_flag:
            return False
    return True


def is_outlier(price, prices):
    """Descarta outliers extremos (menos de 40% o mas de 200% de la mediana)."""
    if not prices:
        return False
    med = statistics.median(prices)
    if med <= 0:
        return False
    return price < med * 0.4 or price > med * 2.0

# --------------------------------------------------------------- serpapi -----

def serpapi_shopping(query):
    """Devuelve lista de dicts {store, title, price, link} desde Google Shopping MX."""
    if not SERPAPI_KEY:
        log("SERPAPI_KEY vacio; se omite SerpApi.")
        return []
    params = {
        "engine": "google_shopping",
        "q": query,
        "gl": "mx",
        "hl": "es",
        "google_domain": "google.com.mx",
        "api_key": SERPAPI_KEY,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa
        log(f"SerpApi error ({query}): {e}")
        return []
    out = []
    for it in data.get("shopping_results", []):
        price = it.get("extracted_price") or parse_price(it.get("price"))
        if price is None:
            continue
        out.append({
            "store": it.get("source") or it.get("store") or "Google Shopping",
            "title": it.get("title", ""),
            "price": float(price),
            "link": it.get("product_link") or it.get("link") or "",
        })
    log(f"SerpApi '{query}': {len(out)} resultados crudos")
    return out

# ------------------------------------------------------------- playwright ----

def playwright_search(query):
    """Best-effort scraping de tiendas puntuales. Devuelve lista de dicts."""
    results = []
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa
        log(f"Playwright no disponible: {e}")
        return results

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="es-MX",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"),
        )
        page = ctx.new_page()
        for store in PLAYWRIGHT_STORES:
            url = store["url"].format(q=urllib.parse.quote(query))
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                items = page.query_selector_all(store["item_sel"])
                for it in items[:15]:
                    try:
                        te = it.query_selector(store["title_sel"])
                        pe = it.query_selector(store["price_sel"])
                        le = it.query_selector(store["link_sel"])
                        title = te.inner_text() if te else ""
                        price = parse_price(pe.inner_text()) if pe else None
                        link = le.get_attribute("href") if le else url
                        if price is None:
                            continue
                        if link and link.startswith("/"):
                            base = "/".join(url.split("/")[:3])
                            link = base + link
                        results.append({
                            "store": store["store"],
                            "title": title.strip(),
                            "price": price,
                            "link": link or url,
                        })
                    except Exception:
                        continue
                log(f"Playwright {store['store']} '{query}': "
                    f"{len(items)} items en pagina")
            except Exception as e:  # noqa
                log(f"Playwright {store['store']} error: {e}")
                continue
        browser.close()
    return results

# ---------------------------------------------------------------- core -------

def collect(product_key):
    cfg = PRODUCTS[product_key]
    raw = []
    for q in cfg["queries"]:
        raw += serpapi_shopping(q)
        raw += playwright_search(q)

    # filtra por titulo
    valid = [r for r in raw if title_matches(r["title"], cfg)]

    # dedup por (store, precio redondeado)
    seen = set()
    dedup = []
    for r in valid:
        key = (norm(r["store"]), round(r["price"]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    # quita outliers
    prices_all = [r["price"] for r in dedup]
    clean = [r for r in dedup if not is_outlier(r["price"], prices_all)]

    clean.sort(key=lambda x: x["price"])
    return clean


def analyze(product_key, listings):
    cfg = PRODUCTS[product_key]
    prices = [l["price"] for l in listings]

    official = OFFICIAL_PRICE.get(product_key)
    official_src = "config"
    if official is None and prices:
        official = statistics.median(prices)
        official_src = "mediana de mercado (sin precio oficial configurado)"

    market = statistics.median(prices) if prices else None
    target_low = round(market * 0.75) if market else None
    target_high = round(market * 0.80) if market else None

    best = listings[0] if listings else None
    hit = bool(best and market and best["price"] <= market * 0.80)

    return {
        "name": cfg["name"],
        "listings": listings,
        "official": official,
        "official_src": official_src,
        "market": market,
        "target_low": target_low,
        "target_high": target_high,
        "best": best,
        "hit": hit,
    }


def pct(a, b):
    if not a or not b:
        return None
    return round((1 - a / b) * 100, 1)


def fmt_disc(dp):
    """Formatea un % de descuento: positivo = descuento, negativo = más caro."""
    if dp is None:
        return ""
    if dp >= 0:
        return f"−{dp}%"
    return f"+{abs(dp)}% s/ref"

# --------------------------------------------------------------- format ------

def fmt_money(v):
    return f"${v:,.0f} MXN" if v is not None else "—"


def build_message(today, analyses):
    L = []
    L.append(f"<b>Monitor de precios — {today.isoformat()}</b>")
    for key, a in analyses.items():
        L.append("")
        L.append(f"<b>▪ {a['name']}</b>")
        if not a["listings"]:
            L.append("Sin listados válidos hoy (revisa fuentes / selectores).")
            continue
        if a["hit"]:
            L.append("✅ <b>OBJETIVO ALCANZADO</b>")
        off = a["official"]
        L.append(f"Precio oficial/ref.: {fmt_money(off)} "
                 f"({a['official_src']})")
        L.append(f"Mercado (mediana): {fmt_money(a['market'])}")
        L.append(f"Objetivo (20–25% off): "
                 f"{fmt_money(a['target_low'])} – {fmt_money(a['target_high'])}")
        b = a["best"]
        d_off = pct(b["price"], off)
        d_mkt = pct(b["price"], a["market"])
        L.append(f"Mejor hoy: <b>{fmt_money(b['price'])}</b> en {b['store']}"
                 + (f" ({fmt_disc(d_off)} vs oficial" if d_off is not None else "")
                 + (f", {fmt_disc(d_mkt)} vs mercado)" if d_mkt is not None else ")"))
        if b["link"]:
            L.append(f'<a href="{b["link"]}">ver oferta</a>')
        # top 5 tabla compacta
        L.append("Top precios:")
        for l in a["listings"][:5]:
            dp = pct(l["price"], off)
            dp_s = f" ({fmt_disc(dp)})" if dp is not None else ""
            L.append(f"• {fmt_money(l['price'])}{dp_s} — {l['store']}")
    L.append("")
    L.append("<i>Precios de lista (envío/impuestos pueden variar). "
             "No se realizó ninguna compra.</i>")
    return "\n".join(L)

# ------------------------------------------------------------- telegram ------

def send_telegram(text):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        log("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID; no se envía.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=30) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
            log(f"Telegram enviado: {ok}")
            return ok
    except Exception as e:  # noqa
        log(f"Telegram error: {e}")
        return False

# ---------------------------------------------------------------- log --------

def append_log(today, analyses):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        if new:
            f.write("# Log de monitoreo de precios (MX)\n\n")
        f.write(f"## {today.isoformat()}\n\n")
        for key, a in analyses.items():
            b = a["best"]
            f.write(f"### {a['name']}\n")
            f.write(f"- Precio oficial/ref.: {fmt_money(a['official'])} "
                    f"({a['official_src']})\n")
            f.write(f"- Mercado (mediana): {fmt_money(a['market'])}\n")
            f.write(f"- Objetivo: {fmt_money(a['target_low'])} – "
                    f"{fmt_money(a['target_high'])}\n")
            if b:
                f.write(f"- Mejor visto: {fmt_money(b['price'])} en "
                        f"{b['store']} — {b['link']}\n")
                f.write(f"- Objetivo alcanzado: {'SÍ' if a['hit'] else 'no'}\n")
            else:
                f.write("- Mejor visto: sin datos\n")
            f.write("\n")


def month_summary(today):
    """Resumen de fin de mes leyendo el log."""
    if not os.path.exists(LOG_PATH):
        return "No hay log para resumir."
    with open(LOG_PATH, encoding="utf-8") as f:
        content = f.read()
    L = ["<b>📅 RESUMEN FINAL DE AGOSTO 2026</b>",
         "Revisa el log completo en el repo para el detalle diario.",
         "La tarea/monitor ya puede desactivarse.",
         "", "<i>Resumen textual del log:</i>"]
    # incluye ultimas lineas de "Mejor visto" por producto
    for line in content.splitlines():
        if line.startswith("### ") or "Mejor visto" in line or "alcanzado" in line:
            L.append(line.replace("### ", "▪ "))
    return "\n".join(L)[:3900]

# ---------------------------------------------------------------- main -------

def main():
    today = datetime.date.today()
    # Permite override para pruebas: MONITOR_DATE=2026-08-31
    ov = os.environ.get("MONITOR_DATE", "").strip()
    if ov:
        today = datetime.date.fromisoformat(ov)

    if today > WINDOW_END:
        send_telegram("La ventana de monitoreo (agosto 2026) terminó. "
                      "La tarea puede desactivarse.")
        return

    analyses = {}
    for key in PRODUCTS:
        log(f"== Producto: {key} ==")
        listings = collect(key)
        analyses[key] = analyze(key, listings)

    append_log(today, analyses)

    msg = build_message(today, analyses)
    if today == WINDOW_END:
        msg += "\n\n" + month_summary(today)
    send_telegram(msg)
    log("Listo.")


if __name__ == "__main__":
    main()

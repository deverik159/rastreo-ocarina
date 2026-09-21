#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de la clasificación con HTML sintético. Ejecuta: python pruebas.py"""
import json
from pathlib import Path

from rastreador import evaluar, normalizar, extraer_precio
from bs4 import BeautifulSoup

CFG = json.loads((Path(__file__).parent / "tiendas.json").read_text(encoding="utf-8"))
REGLAS = {t["id"]: t["reglas"] for t in CFG["tiendas"]}


def caso(nombre, esperado, obtenido):
    ok = esperado == obtenido["estado"]
    print(f"{'OK ' if ok else 'FALLA'} {nombre:<48} → {obtenido['estado']:<11} {obtenido['detalle']}")
    assert ok, f"{nombre}: esperaba {esperado}, obtuve {obtenido}"


AMAZON_DISPONIBLE = """
<html><body>
<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">$1,749.00</span></span></div>
<div id="buybox">
  <div id="availability"><span>Este artículo se lanzará el 5 de noviembre de 2026.</span></div>
  <input id="add-to-cart-button" type="submit" value="Reservar ahora">
  <div id="merchant-info">Vendido y enviado por Amazon México.</div>
</div>
<script>var x = "No disponible por el momento";</script>
</body></html>
"""

AMAZON_AGOTADO = """
<html><body>
<div id="buybox">
  <div id="outOfStock">
    <div id="availability"><span class="a-color-price">No disponible por el momento.</span>
    <span>No sabemos si este producto volverá a estar disponible, ni cuándo.</span></div>
  </div>
</div>
<div class="a-carousel"><span>Agregar al carrito</span></div>
</body></html>
"""

AMAZON_TERCEROS = """
<html><body>
<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">$2,899.00</span></span></div>
<div id="buybox-see-all-buying-choices"><a>Ver todas las opciones de compra</a></div>
</body></html>
"""

AMAZON_CAPTCHA = """
<html><head><title>Amazon.com.mx</title></head><body>
<form action="/errors/validateCaptcha"><h4>Escribe los caracteres que ves en la imagen</h4>
<input id="captchacharacters"></form></body></html>
"""

GENERICO_AGOTADO = """
<html><body><h1>Preventa The Legend of Zelda: Ocarina of Time</h1>
<div class="precio"><span class="current">$1,799.00</span></div>
<button disabled>Producto agotado</button></body></html>
"""

GENERICO_DISPONIBLE = """
<html><body><h1>Preventa The Legend of Zelda: Ocarina of Time</h1>
<button>Agregar al carrito</button></body></html>
"""

VACIO_SPA = "<html><body><div id='root'></div><script>window.__DATA__={}</script></body></html>"

MAGENTO_AGOTADO = """
<html><body><div class="product-info-main">
<span class="price">$1,799.00</span>
<div class="stock unavailable"><span>Agotado</span></div>
</div></body></html>
"""

MAGENTO_DISPONIBLE = """
<html><body><div class="product-info-main">
<span class="price">$1,799.00</span>
<button id="product-addtocart-button">Añadir al carrito</button>
</div></body></html>
"""

if __name__ == "__main__":
    r = evaluar(200, AMAZON_DISPONIBLE, REGLAS["amazon_mx"])
    caso("Amazon con botón de reservar", "disponible", r)
    assert r["precio"] == 1749.0, r
    assert "Amazon" in (r["vendedor"] or ""), r

    caso("Amazon agotado (#outOfStock)", "agotado", evaluar(200, AMAZON_AGOTADO, REGLAS["amazon_mx"]))
    r = evaluar(200, AMAZON_TERCEROS, REGLAS["amazon_mx"])
    caso("Amazon sólo vendedores externos", "terceros", r)
    assert r["precio"] == 2899.0, r
    caso("Amazon captcha", "bloqueado", evaluar(200, AMAZON_CAPTCHA, REGLAS["amazon_mx"]))
    caso("HTTP 503", "bloqueado", evaluar(503, "<html></html>", REGLAS["amazon_mx"]))
    caso("HTTP 404", "sin_ficha", evaluar(404, "<html></html>", REGLAS["amazon_mx"]))

    r = evaluar(200, GENERICO_AGOTADO, REGLAS["coppel"])
    caso("Coppel agotado por texto", "agotado", r)
    assert r["precio"] == 1799.0, r
    caso("Coppel disponible por texto", "disponible", evaluar(200, GENERICO_DISPONIBLE, REGLAS["coppel"]))
    r = evaluar(200, VACIO_SPA, REGLAS["coppel"])
    caso("Página vacía (SPA sin render)", "desconocido", r)
    assert "playwright" in r["detalle"], r

    caso("Gameplanet/Magento agotado", "agotado", evaluar(200, MAGENTO_AGOTADO, REGLAS["gameplanet"]))
    caso("Gameplanet/Magento disponible", "disponible", evaluar(200, MAGENTO_DISPONIBLE, REGLAS["gameplanet"]))

    assert normalizar("  Pre-Ordena  AHORA ") == "pre-ordena ahora"
    assert normalizar("Publicación finalizada") == "publicacion finalizada"
    soup = BeautifulSoup("<p class='p'>Precio: $ 1,449.50 MXN</p>", "html.parser")
    assert extraer_precio(soup, [".p"]) == 1449.5

    print("\nTodas las pruebas pasaron.")

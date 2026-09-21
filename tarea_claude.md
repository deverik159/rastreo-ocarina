# Opción 1 · Tarea programada de Claude (la red amplia)

El script del repo vigila **fichas concretas** cada 10 minutos. La tarea programada de
Claude cubre lo que un script no puede: descubrir tiendas nuevas, leer noticias de
restock y revisar Mercado Libre sin que tengas que pegar URLs. Las dos se complementan.

## Cómo crearla

Las tareas programadas están en todos los planes de pago y corren en la nube (no
necesitas la computadora encendida). Dos caminos, según cómo se vea tu app:

- **Barra lateral → "Scheduled" (Programadas) → "New task" → "Create with Claude"**, pega
  el prompt de abajo, elige la cadencia y confirma con "Schedule".
- Si tu cuadro de mensaje ya no muestra "Chat" y "Cowork" (experiencia unificada), abre
  una **conversación nueva**, pega el prompt seguido de la cadencia ("…ejecútalo todos los
  días a las 9:00") y confirma cuando Claude te proponga nombre, horario e instrucciones.

## Cadencia sugerida

- **Diaria a las 9:00** desde hoy hasta el 5 de noviembre: es la red que revisa todo.
- **Cada hora** (la frecuencia máxima) la última semana de octubre, cuando suele haber
  la segunda ola de unidades en preventa. Puedes pausarla/reanudarla desde "Scheduled".

## Prompt (pégalo tal cual)

```
Eres mi rastreador de preventa. Producto: "The Legend of Zelda: Ocarina of Time" para
Nintendo Switch 2, edición física (portada texturizada), lanzamiento 5 de noviembre de
2026, precio oficial en México $1,749 MXN.

1. Abre estas fichas y dime si permiten reservar (botón de reservar / agregar al
   carrito) o están agotadas, y el precio que muestran:
   - Amazon México: https://www.amazon.com.mx/dp/B0HJ6W2J5W
   - Coppel: https://www.coppel.com/pdp/preventa-the-legend-of-zelda-ocarina-of-time-para-nintendo-switch-2-pm-2504943
2. Busca en Mercado Libre México si la tienda oficial de Nintendo tiene el artículo
   publicado y disponible. Ignora revendedores y cualquier precio arriba de $1,800.
3. Busca si Gameplanet, Liverpool, Sanborns, Palacio de Hierro, Walmart o Sears ya
   tienen ficha del juego y si aceptan preventa. Si encuentras una ficha nueva, dame
   la URL exacta.
4. Busca noticias de las últimas 24 horas sobre reapertura de preventas en México
   (incluye Promodescuentos y Xataka México Selección).

Formato de respuesta:
- Si CUALQUIER tienda oficial permite reservar, empieza con "🟢 ALERTA" y el enlace
  directo, una línea por tienda disponible.
- Después una tabla: Tienda | Estado (disponible / agotado / sin ficha / no pude
  verificar) | Precio | Enlace.
- Si nada está disponible y no hay noticias nuevas, responde en máximo 3 líneas.
- No inventes disponibilidad: si una página no cargó, márcala como "no pude verificar".
```

## Qué esperar

- El resultado de cada corrida aparece en "Scheduled" como una sesión más; revísalo ahí.
- Claude **detecta y reporta**, no reserva: el checkout con tu cuenta y tu pago lo haces tú.
- Cuando la tarea descubra una ficha nueva (p. ej. Gameplanet o Liverpool), pega esa URL
  en `tiendas.json` del repo para que el script la vigile cada 10 minutos.

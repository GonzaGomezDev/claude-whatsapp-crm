---
name: knowledge
description: >-
  Buscar respuestas en la base de conocimiento interna: listas de precios, políticas de
  pago, plazos de entrega, documentación de productos. Usala antes de responder cualquier
  pregunta sobre precios, condiciones comerciales o características de un producto.
  Devuelve los documentos con cuántos términos matchearon y un score del motor de búsqueda.
---

# Knowledge

La regla es una sola: **no inventes datos comerciales.** Precios, plazos y
condiciones salen de acá o no salen.

## Precondiciones

Ninguna. Se puede correr en paralelo con `client-management` — no depende del
cliente.

## Cómo funciona la búsqueda

Es full-text search de Postgres con stemming en español, no búsqueda vectorial.
Consecuencia práctica: **matchea palabras, no conceptos.** "cotización" encuentra
"cotizaciones" y "cotizar", pero no encuentra "presupuesto".

La búsqueda hace dos pasadas automáticamente:

1. **`all_terms`** — todos los términos de tu consulta aparecen en el documento.
2. **`any_term`** — si lo anterior no encontró nada, reintenta con los términos
   sueltos y ordena por cuántos matchearon.

El campo `match_mode` te dice cuál se usó. Si vino `any_term`, **leé el contenido
antes de citarlo**: el documento matcheó parcialmente y puede no ser sobre lo que
preguntaste.

## Cómo consultar

Usá las palabras que esperás encontrar **escritas en el documento**, no la
pregunta del cliente. Menos términos y más específicos funciona mejor que una
frase larga.

**Escribí la consulta con acentos**, aunque el cliente haya escrito sin ellos.
El stemmer español los necesita para reconocer sufijos: `cotización` se reduce a
`cotiz` y matchea `cotizaciones`, pero `cotizacion` sin acento no se reduce y no
matchea nada.

| el cliente dice | consultá |
|---|---|
| "¿cuál es la lista de precios actualizada?" | `precios lista` |
| "¿cuánto me sale si llevo 500?" | `descuento volumen unidades` |
| "¿cómo puedo pagar?" | `formas de pago` |
| "¿en cuánto llega?" | `plazo entrega` |

Si el primer intento vuelve vacío, reformulá una vez con sinónimos antes de
darte por vencido:

- precio → cotización, tarifa, lista, valor
- descuento → bonificación, volumen, mayorista
- envío → entrega, plazo, despacho

## Leer los resultados

**`matched_terms` / `query_terms`** es la señal más confiable. 4 de 4 es un match
sólido; 1 de 4 en modo `any_term` es probablemente ruido.

**`confidence`** es `ts_rank` normalizado, en el rango [0, 1). No es una
probabilidad. Un match real suele dar entre 0.28 y 0.50; por debajo de 0.10 es
ruido. Usalo para desempatar, no como criterio principal.

**`truncated: true`** significa que el documento sigue más allá de lo que estás
viendo. **No afirmes que tenés la información completa.** Respondé con lo que
tenés, aclarando que hay más detalle, y ofrecé un ticket si el cliente lo
necesita.

## Si ya hay un ticket abierto sobre el tema

**Buscá igual.** Que exista un ticket no significa que la respuesta no esté en la
base: puede haberse cargado después, o la búsqueda anterior puede haber fallado.

Si esta vez encontrás la respuesta, dásela y actualizá el ticket con
`update_ticket_status`. Recién si volvés a no encontrar nada, referí al ticket
que ya existe — sin crear uno nuevo.

Responder "eso ya está cargado en el ticket 4001" sin haber buscado es, para el
cliente, lo mismo que no haber preguntado.

## Si no encontrás nada

No improvises un precio. Creá un ticket de tipo `quotation` y decile al cliente
que el equipo le pasa la información. Un "no lo tengo a mano, te lo confirmo en
24hs" cuesta mucho menos que un precio inventado.

## Error handling

- Resultado vacío no es un error. Reformulá una vez, después creá el ticket.
- `error_type: timeout` o `circuit_open` — la KB no responde. Respondé lo que
  sepas con certeza del historial de la conversación y creá un ticket para el
  resto. No escales a un humano sólo por esto: no es bloqueante.

## Qué no hacer

- No cites el contenido textual como si fuera tuyo sin decir de dónde sale.
- No sumes ni conviertas precios de cabeza. Si el cliente pide 500 unidades y el
  documento da el unitario, decí el unitario y el total como cálculo explícito,
  para que sea auditable.
- No respondas una pregunta sobre condiciones comerciales con `match_mode:
  any_term` y 1 de 4 términos. Eso es adivinar con pasos extra.

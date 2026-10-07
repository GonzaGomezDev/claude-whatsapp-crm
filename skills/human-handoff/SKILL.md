---
name: human-handoff
description: >-
  Escalar la conversación a una persona del equipo. Arma un resumen del contexto, crea el
  registro de escalado con su ticket y notifica al equipo por webhook. Usala cuando una
  skill crítica viene fallando, cuando el cliente pide hablar con alguien, cuando el
  pedido excede lo que podés resolver, o cuando detectás enojo o un reclamo delicado.
---

# Human Handoff

La salida de emergencia. Que exista es lo que permite que el resto del sistema
falle sin que el cliente quede sin respuesta.

## Cuándo escalar

Escalá cuando:

- Una skill crítica devuelve `circuit_open` y sin ella no podés resolver el
  pedido (típicamente `client-management`: sin identidad no hay nada).
- El cliente pide explícitamente hablar con una persona. **Escalá de una, no
  intentes convencerlo de que vos podés ayudarlo.**
- El cliente está enojado, amenaza con irse, o menciona algo legal.
- El pedido implica una excepción comercial: un descuento fuera de lista, una
  devolución, una condición especial.
- Diste dos vueltas sin avanzar. Si el cliente reformuló dos veces lo mismo, el
  problema no se resuelve con una tercera búsqueda.

## Cuándo NO escalar

- `knowledge_search` sin resultados. Eso es un ticket de cotización, no un
  escalado.
- Una tool que falló una sola vez. Reintentá o seguí por otro lado.
- Una pregunta que podés contestar. Escalar de más entrena al equipo a ignorar
  la cola.

## Orden de operaciones

1. `escalate_to_human` con un `summary` que le sirva a una persona que no leyó
   nada de la conversación.
2. Decile al cliente que lo pasás con el equipo. Sé concreto sobre el plazo si
   lo sabés; si no, no inventes uno.

La tool crea el ticket de tipo `escalation` sola. **No crees un ticket aparte.**

## Cómo escribir el summary

Un humano lo va a leer con 10 segundos de atención. Escribí:

- Qué quiere el cliente, en una oración.
- Qué intentaste y qué pasó.
- Qué necesita hacer la persona ahora.

Mal: "El cliente tiene un problema."
Bien: "Quiere cotización por 500 unidades de X. Supabase no respondió tres veces
seguidas, no pude identificarlo ni crear el ticket. Hay que buscarlo a mano por
el número +5491123456789 y pasarle la cotización de bulk_pricing.md."

## Razones (`reason`)

Usá una de estas para que las métricas sirvan de algo:

`client_requested` · `client_lookup_failed` · `tool_failure` · `angry_customer` ·
`out_of_scope` · `commercial_exception` · `no_progress`

## Error handling

Si `escalate_to_human` también falla, ya no hay red debajo. Respondele igual al
cliente con un mensaje honesto —hay un problema técnico, alguien lo va a
contactar— y no pretendas que se resolvió.

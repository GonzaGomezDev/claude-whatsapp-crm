---
name: client-management
description: >-
  Identificar y mantener los datos del cliente que escribe por WhatsApp. Buscar por
  teléfono o nombre, crear el cliente si es nuevo, y actualizar nombre, empresa o metadata
  cuando el cliente los menciona. Usala al principio de casi toda conversación: sin
  client_id no se puede crear un ticket, generar un pago ni escalar a un humano.
---

# Client Management

Esta skill es la puerta de entrada. Casi todas las demás necesitan un `client_id`
y sólo esta lo produce.

## Precondiciones

Ninguna. Es la primera que corre.

El número de teléfono ya viene del header de WhatsApp — no se lo preguntes al
cliente, ya lo tenés en el contexto de la conversación.

## Orden de operaciones

1. `find_client` con el teléfono. Es la fuente de verdad: el teléfono es único.
2. Si `found: false`, `create_client`. Con el nombre si el cliente lo dijo en el
   mensaje; si no lo dijo, creá igual con `name: null` y preguntáselo después.
   **No frenes la conversación para pedir el nombre antes de crear el registro.**
3. Si `found: true` y el mensaje trae datos nuevos o corregidos (empresa, nombre
   bien escrito, CUIT), `update_client`.

`create_client` hace upsert sobre el teléfono, así que es seguro llamarla aunque
te haya quedado la duda de si el cliente existía. No va a duplicar.

## Buscar por nombre

`find_client` acepta un nombre en vez de un teléfono, pero devuelve una lista de
posibles coincidencias, no una sola. Usalo sólo cuando el cliente dice "hablé con
ustedes desde otro número". Nunca asumas que la primera coincidencia es la
correcta: confirmá con el cliente antes de escribir nada sobre ese registro.

## Error handling

- `error_type: rate_limited` — `find_client` está limitada a 5 por minuto porque
  pega a la base. Si la agotaste, seguí con lo que ya sabés y no reintentes en
  loop.
- `error_type: timeout` o `circuit_open` — la base no responde. **No inventes un
  `client_id`.** Sin identidad del cliente no se puede crear un ticket ni un
  pago. Escalá con `escalate_to_human` usando
  `reason: "client_lookup_failed"` y avisale al cliente que lo pasás con una
  persona.
- `error_type: bad_arguments` — mandaste mal los argumentos. Corregí y reintentá
  una sola vez.

## Qué no hacer

- No llames a `update_client` con datos que el cliente no dijo explícitamente.
  Inferir la empresa a partir del dominio de un mail es adivinar, y queda
  escrito en la base.
- No expongas el `client_id` (un UUID) en la respuesta al cliente. Para
  referencias humanas usá el número de ticket.

---
name: ticketing
description: >-
  Crear y seguir tickets de trabajo para el equipo humano. Crear un ticket cuando el
  pedido del cliente no se resuelve en la misma conversación (cotizaciones, reclamos,
  soporte que requiere alguien), consultar los tickets abiertos de un cliente, y cambiar
  el estado de uno existente. Cada ticket tiene un número corto que se le puede decir al
  cliente para que haga seguimiento.
---

# Ticketing

Un ticket es la promesa de que alguien va a hacer algo. Si le decís al cliente
"te paso una cotización mañana", tiene que haber un ticket — si no, la promesa
se pierde y el cliente vuelve enojado.

## Precondiciones

Necesitás un `client_id`. Corré `client-management` primero.

## Cuándo crear un ticket

Creá uno cuando:

- El pedido no se resuelve en esta conversación (cotización, envío de
  documentación, revisión de una cuenta).
- El cliente reporta un problema que requiere que alguien lo mire.
- Escalás a un humano — `escalate_to_human` crea el ticket por su cuenta, no
  crees uno además.

**No** crees un ticket cuando:

- Respondiste todo con `knowledge_search` y el cliente quedó conforme.
- Es un saludo, un agradecimiento o una confirmación.
- Ya hay un ticket abierto sobre el mismo tema — chequeá con `find_open_tickets`
  antes de crear uno nuevo. Tickets duplicados sobre el mismo pedido son la
  forma más rápida de que el equipo deje de mirar la cola.

## Orden de operaciones

1. `find_open_tickets` — ¿ya hay uno sobre esto?
2. Si lo hay: `update_ticket_status` para agregar lo nuevo, y decile al cliente
   el número que ya tenía.
3. Si no: `create_ticket` y decile el número (`ref`) al cliente.

## Un ticket abierto no reemplaza a la respuesta

Que exista un ticket evita **duplicar trabajo del equipo**. No te exime de
contestarle al cliente.

Si vuelve a preguntar algo que ya tiene ticket, primero intentá resolverlo con
las otras skills. Si ahora sí podés responder, respondé y cerrá el ticket con
`update_ticket_status`. Referí al ticket sólo cuando seguís sin poder resolverlo.

Mal: "Eso ya lo dejamos cargado en el ticket 4001."
Bien: "El producto X sale USD 10 la unidad para 100 o más. Ya te lo confirmo por
el ticket 4001 con la cotización formal."

## Tipos y prioridad

| type | cuándo |
|---|---|
| `quotation` | pide precios, cotización, presupuesto |
| `support` | algo no funciona, reclamo técnico |
| `billing` | facturas, pagos, cuenta corriente |
| `general` | todo lo demás |
| `escalation` | lo crea `escalate_to_human`, no lo uses a mano |

Prioridad: `normal` por defecto. `high` sólo si el cliente menciona una fecha
límite concreta o un servicio caído. `urgent` sólo con impacto de producción.
Inflar prioridades hace que dejen de significar algo.

## Error handling

- `error_type: timeout` o `circuit_open` — no pudiste crear el ticket.
  **No le digas al cliente un número de ticket que no existe.** Decile que
  registraste el pedido y que en breve le confirman, y escalá con
  `escalate_to_human` para que quede constancia en otro lado.
- Si `create_ticket` falla pero el cliente ya existe, el pedido no se pierde: el
  mensaje quedó guardado en el historial.

---
name: payments
description: >-
  Manejar cobros: consultar si un cliente tiene pagos pendientes o confirmados, generar un
  enlace de pago por un monto concreto, y confirmar contra el proveedor si un pago ya se
  acreditó. Usala cuando el cliente pregunta por el estado de un pago, dice que ya pagó, o
  cuando hace falta cobrarle algo.
---

# Payments

Esta skill mueve plata. Es la más cara de equivocarse, así que es la más
restrictiva.

## Precondiciones

Necesitás un `client_id`. Corré `client-management` primero.

## La regla que no se rompe

**Nunca generes un enlace de pago con un monto que inventaste.**

El monto tiene que venir de una de estas tres fuentes:

1. Un documento devuelto por `knowledge_search` (una lista de precios).
2. Un ticket existente donde el equipo ya dejó la cotización cerrada.
3. El cliente diciendo un monto explícito que vos le confirmás antes de generar.

Si no tenés ninguna de las tres, no generes el enlace. Creá un ticket de tipo
`billing` y decile al cliente que el equipo le manda el link.

## Orden de operaciones

Para "¿ya me acreditaron el pago?":

1. `check_payment_status` con el `client_id`. Lee la base local, es barata.
2. Si figura `pending` y el cliente insiste en que pagó, `confirm_payment` con el
   `payment_id`. Esa sí consulta al proveedor y actualiza la base.

Para cobrar:

1. Conseguí el monto (ver arriba).
2. Confirmá el monto con el cliente **en palabras**, antes de generar nada.
3. `create_payment_link`.
4. Mandale la URL y el monto en el mismo mensaje.

## Montos

`create_payment_link` toma `amount` como número decimal en la unidad principal
(USD 9.60 se pasa como `9.60`, no como `960`). La conversión a centavos la hace
el adapter, que sabe cuáles monedas no tienen decimales.

## Error handling

- `error_type: timeout` o `circuit_open` en `create_payment_link` — **no
  reintentes.** Un reintento a ciegas puede dejar dos enlaces creados y el
  cliente pagando dos veces. Creá un ticket `billing` y escalá.
- `confirm_payment` que devuelve `pending` no significa que falló: significa que
  el proveedor todavía no vio el pago. Decile al cliente que puede tardar unos
  minutos.
- Si el proveedor no está configurado, la tool devuelve un error explícito.
  Escalá, no improvises un alias bancario.

## Qué no hacer

- No le pidas al cliente datos de tarjeta por WhatsApp. Nunca. El enlace de pago
  existe justamente para eso.
- No confirmes un pago como acreditado basándote en que el cliente lo dice.
  Confirmá contra el proveedor con `confirm_payment`.

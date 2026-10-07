"""Skill 4: Payments.

Las tools hablan con `ctx.payments`, que es un PaymentProvider. No saben si abajo
hay Stripe, Mercado Pago o lo que sea.
"""

from __future__ import annotations

from typing import Any

from whatsapp_skills.skills.base import SkillContext, skill_tool


def _money(cents: int, currency: str) -> str:
    return f"{currency.upper()} {cents / 100:.2f}"


@skill_tool(
    name="check_payment_status",
    description=(
        "Ver los pagos registrados de un cliente y su estado. Lee la base local, no "
        "consulta al proveedor: es rápida y barata."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "UUID del cliente, como lo devuelven find_client o create_client.",
            },
            "status": {
                "type": ["string", "null"],
                "enum": ["pending", "paid", "failed", "expired", "refunded", None],
                "description": "Filtrar por estado, o null para traer todos.",
            },
        },
        "required": ["client_id", "status"],
        "additionalProperties": False,
    },
    timeout_s=2.0,
    rate_limit="20/minute",
)
async def check_payment_status(
    ctx: SkillContext, client_id: str, status: str | None
) -> dict[str, Any]:
    rows = await ctx.db.payments_for_client(client_id, status)
    return {
        "count": len(rows),
        "payments": [
            {
                "payment_id": r["id"],
                "status": r["status"],
                "amount": _money(r["amount_cents"], r["currency"]),
                "url": r.get("payment_url"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }


@skill_tool(
    name="create_payment_link",
    description=(
        "Generar un enlace de pago por un monto concreto. El monto DEBE venir de la "
        "knowledge base, de un ticket cerrado, o confirmado con el cliente. Nunca lo "
        "inventes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "UUID del cliente, como lo devuelven find_client o create_client.",
            },
            "amount": {
                "type": "number",
                "description": "Monto en la unidad principal. USD 9.60 se pasa como 9.6.",
                "exclusiveMinimum": 0,
            },
            "currency": {
                "type": "string",
                "description": "Código ISO de 3 letras, ej: usd, eur, ars.",
            },
            "description": {
                "type": "string",
                "description": "Qué se está cobrando. El cliente lo ve en el checkout.",
            },
            "amount_source": {
                "type": "string",
                "description": (
                    "De dónde salió el monto. Ej: 'bulk_pricing.md' o 'ticket 4412' o "
                    "'confirmado con el cliente'. Queda auditado."
                ),
            },
        },
        "required": ["client_id", "amount", "currency", "description", "amount_source"],
        "additionalProperties": False,
    },
    timeout_s=8.0,
    rate_limit="5/minute",
)
async def create_payment_link(
    ctx: SkillContext,
    client_id: str,
    amount: float,
    currency: str,
    description: str,
    amount_source: str,
) -> dict[str, Any]:
    if ctx.payments is None:
        raise RuntimeError(
            "No hay proveedor de pagos configurado. Revisá PAYMENT_PROVIDER y "
            "STRIPE_SECRET_KEY."
        )

    amount_cents = ctx.payments.to_minor_units(amount, currency)
    link = await ctx.payments.create_link(
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        metadata={"client_id": client_id, "amount_source": amount_source[:400]},
    )

    row = await ctx.db.create_payment_row(
        {
            "client_id": client_id,
            "provider": ctx.payments.name,
            "external_id": link.external_id,
            "status": "pending",
            "amount_cents": link.amount_cents,
            "currency": link.currency,
            "payment_url": link.url,
            "metadata": {"amount_source": amount_source, "description": description},
        }
    )

    return {
        "payment_id": row["id"],
        "url": link.url,
        "amount": _money(link.amount_cents, link.currency),
        "created": True,
        "tell_client": f"{description} — {_money(link.amount_cents, link.currency)}: {link.url}",
    }


@skill_tool(
    name="confirm_payment",
    description=(
        "Consultar al proveedor si un pago ya se acreditó y actualizar la base. Usala "
        "cuando el cliente dice que pagó y en la base todavía figura pendiente."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "payment_id": {
                "type": "string",
                "description": "UUID del pago, tal como lo devuelve check_payment_status.",
            }
        },
        "required": ["payment_id"],
        "additionalProperties": False,
    },
    timeout_s=8.0,
    rate_limit="10/minute",
)
async def confirm_payment(ctx: SkillContext, payment_id: str) -> dict[str, Any]:
    if ctx.payments is None:
        raise RuntimeError("No hay proveedor de pagos configurado.")

    record = await ctx.db.get_payment(payment_id)
    if record is None:
        return {"found": False, "error": f"No existe el pago {payment_id}."}

    # Chequeo de pertenencia: un payment_id alucinado no debe filtrar el pago de
    # otro cliente.
    if ctx.client_id and record["client_id"] != ctx.client_id:
        return {"found": False, "error": f"El pago {payment_id} no es de este cliente."}

    if not record.get("external_id"):
        return {
            "found": True,
            "payment_id": payment_id,
            "status": record["status"],
            "note": "El pago no tiene referencia del proveedor; no se puede confirmar.",
        }

    status = await ctx.payments.get_status(record["external_id"])
    if status.status != record["status"]:
        await ctx.db.update_payment_row(payment_id, {"status": status.status})

    return {
        "found": True,
        "payment_id": payment_id,
        "status": status.status,
        "amount": _money(status.amount_cents or record["amount_cents"], status.currency),
        "changed": status.status != record["status"],
        "note": (
            "Un pago recién hecho puede tardar unos minutos en acreditarse."
            if status.status == "pending"
            else None
        ),
    }

"""Skill 2: Ticketing."""

from __future__ import annotations

from typing import Any

from whatsapp_skills.skills.base import SkillContext, skill_tool

TICKET_TYPES = ["general", "quotation", "support", "billing"]
PRIORITIES = ["low", "normal", "high", "urgent"]
STATUSES = ["open", "in_progress", "waiting_client", "resolved", "closed"]


@skill_tool(
    name="create_ticket",
    description=(
        "Crear un ticket para que el equipo humano dé seguimiento a un pedido que no "
        "se resuelve en esta conversación. Devuelve un número corto para el cliente."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "UUID del cliente, como lo devuelven find_client o create_client.",
            },
            "type": {
                "type": "string",
                "enum": TICKET_TYPES,
                "description": (
                    "quotation para pedidos de precio, support para reclamos técnicos, "
                    "billing para facturación, general para el resto."
                ),
            },
            "subject": {
                "type": "string",
                "description": "Una línea describiendo el pedido, en las palabras del cliente.",
            },
            "priority": {
                "type": "string",
                "enum": PRIORITIES,
                "description": (
                    "normal por defecto. high sólo con fecha límite concreta o servicio "
                    "caído; urgent sólo con impacto de producción."
                ),
            },
            "details": {
                "type": ["string", "null"],
                "description": "Contexto extra para el equipo: cantidades, plazos, producto.",
            },
        },
        "required": ["client_id", "type", "subject", "priority", "details"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="20/minute",
)
async def create_ticket(
    ctx: SkillContext,
    client_id: str,
    type: str,  # noqa: A002 - el nombre lo fija el schema que ve Claude
    subject: str,
    priority: str,
    details: str | None,
) -> dict[str, Any]:
    row = await ctx.db.create_ticket_row(
        client_id=client_id,
        ticket_type=type,
        subject=subject,
        priority=priority,
        metadata={"details": details} if details else {},
    )
    return {
        "ticket_id": row["id"],
        "ticket_ref": row["ref"],
        "status": row["status"],
        "created": True,
        "tell_client": f"Tu número de seguimiento es el {row['ref']}.",
    }


@skill_tool(
    name="find_open_tickets",
    description=(
        "Listar los tickets abiertos de un cliente. Corré esto ANTES de crear uno "
        "nuevo, para no duplicar."
    ),
    input_schema={
        "type": "object",
        "properties": {
                "client_id": {
                    "type": "string",
                    "description": "UUID del cliente, como lo devuelve find_client.",
                }
            },
        "required": ["client_id"],
        "additionalProperties": False,
    },
    timeout_s=2.0,
    rate_limit="20/minute",
)
async def find_open_tickets(ctx: SkillContext, client_id: str) -> dict[str, Any]:
    rows = await ctx.db.open_tickets(client_id)
    return {
        "count": len(rows),
        "tickets": [
            {
                "ref": r["ref"],
                "type": r["type"],
                "status": r["status"],
                "priority": r["priority"],
                "subject": r.get("subject"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }


@skill_tool(
    name="update_ticket_status",
    description=(
        "Cambiar el estado de un ticket existente, o sumarle una nota de avance. "
        "Se identifica por el número corto (ref), no por UUID."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ticket_ref": {
                "type": "integer",
                "description": "El número corto que se le dijo al cliente. Ej: 4412.",
            },
            "status": {
                "type": "string",
                "enum": STATUSES,
                "description": "Nuevo estado del ticket.",
            },
            "note": {
                "type": ["string", "null"],
                "description": "Qué cambió y por qué.",
            },
        },
        "required": ["ticket_ref", "status", "note"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="20/minute",
)
async def update_ticket_status(
    ctx: SkillContext, ticket_ref: int, status: str, note: str | None
) -> dict[str, Any]:
    # La nota se MEZCLA con la metadata existente. Reemplazarla se llevaría
    # puesto el `details` que guardó create_ticket, que es el contexto que el
    # equipo humano necesita para atender el ticket.
    row = await ctx.db.update_ticket_row(
        ticket_ref,
        {"status": status},
        metadata_patch={"last_note": note} if note else None,
    )
    return {"ticket_ref": row["ref"], "status": row["status"], "updated": True}

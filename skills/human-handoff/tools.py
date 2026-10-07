"""Skill 5: HumanHandoff.

Es la única skill que tiene permitido fallar parcialmente y devolver éxito: si
el registro en la base se crea pero la notificación al equipo no sale, el
escalado igual quedó asentado. Lo contrario —notificar sin registrar— sí sería
un problema, así que ese es el orden.
"""

from __future__ import annotations

from typing import Any

from whatsapp_skills.integrations.notifications import Escalation
from whatsapp_skills.observability.logging import get_logger
from whatsapp_skills.skills.base import SkillContext, skill_tool

log = get_logger(__name__)

REASONS = [
    "client_requested",
    "client_lookup_failed",
    "tool_failure",
    "angry_customer",
    "out_of_scope",
    "commercial_exception",
    "no_progress",
]


@skill_tool(
    name="escalate_to_human",
    description=(
        "Pasar la conversación a una persona del equipo. Crea el registro de escalado "
        "con su ticket y notifica al equipo. No crees un ticket aparte además de este."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "enum": REASONS,
                "description": (
                    "Motivo del escalado. Elegí el más específico: es lo que después "
                    "se mide para saber dónde falla el agente."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Qué quiere el cliente, qué intentaste, y qué tiene que hacer la "
                    "persona ahora. Escribilo para alguien que no leyó la conversación."
                ),
            },
            "client_id": {
                "type": ["string", "null"],
                "description": "UUID del cliente, o null si justamente no se pudo identificar.",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high", "urgent"],
                "description": (
                    "high si el cliente está molesto o hay un plazo; urgent si hay "
                    "plata o un servicio caído en juego."
                ),
            },
        },
        "required": ["reason", "summary", "client_id", "urgency"],
        "additionalProperties": False,
    },
    timeout_s=6.0,
    rate_limit="10/minute",
)
async def escalate_to_human(
    ctx: SkillContext,
    reason: str,
    summary: str,
    client_id: str | None,
    urgency: str,
) -> dict[str, Any]:
    client_id = client_id or ctx.client_id

    # Últimos turnos, para que el humano tenga el hilo sin abrir la base.
    transcript = [
        {
            "role": m.get("role") or m.get("direction"),
            "text": str(m.get("content") or m.get("body"))[:500],
        }
        for m in ctx.conversation[-6:]
    ]

    ticket_ref: int | None = None
    if client_id:
        ticket = await ctx.db.create_ticket_row(
            client_id=client_id,
            ticket_type="escalation",
            subject=summary[:200],
            priority=urgency,
            metadata={"reason": reason},
        )
        ticket_ref = ticket["ref"]
        ticket_id = ticket["id"]
    else:
        ticket_id = None

    escalation = await ctx.db.create_escalation_row(
        {
            "client_id": client_id,
            "ticket_id": ticket_id,
            "reason": reason,
            "summary": summary,
            "context": {
                "phone": ctx.phone,
                "urgency": urgency,
                "transcript": transcript,
                "breakers": ctx.scratch.get("breakers", {}),
            },
        }
    )

    # La bandeja la muestra como "pidió humano". Sólo desde 'bot': si ya hay una
    # persona en el chat, no se le pisa el estado.
    try:
        await ctx.db.set_conversation_status(ctx.phone, "needs_human", only_from="bot")
    except Exception as exc:  # noqa: BLE001
        # El escalado ya quedó registrado; la etiqueta es secundaria.
        log.warning("needs_human_label_failed", error=str(exc))

    notified = await _notify_team(
        ctx,
        Escalation(
            reason=reason,
            summary=summary,
            phone=ctx.phone,
            urgency=urgency,
            ticket_ref=ticket_ref,
            escalation_id=escalation["id"],
        ),
    )

    return {
        "escalated": True,
        "escalation_id": escalation["id"],
        "ticket_ref": ticket_ref,
        "team_notified": notified,
        "tell_client": (
            "Te paso con alguien del equipo que puede ayudarte mejor con esto."
            + (f" Tu número de seguimiento es el {ticket_ref}." if ticket_ref else "")
        ),
    }


async def _notify_team(ctx: SkillContext, escalation: Escalation) -> bool:
    """Best-effort. El escalado ya quedó registrado; esto es sólo el aviso.

    El destino se deduce de HANDOFF_NOTIFY_URL: Slack, Discord, ntfy, Telegram,
    WhatsApp o un webhook propio. Ver integrations/notifications.py.
    """
    if ctx.notifier is None:
        return False
    return await ctx.notifier.send(escalation)

"""CRM: lo que el panel le pide al agente.

El panel sólo lee de Supabase (anon key + RLS). Todo lo que escribe pasa por
acá, con la service_role key y las credenciales de Twilio, que nunca salen del
servidor. El token es el JWT de Supabase Auth del operador.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .observability.logging import get_logger
from .window import window_remaining

log = get_logger(__name__)
router = APIRouter(prefix="/crm")


async def require_operator(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Falta el token de sesión.")
    operator = await request.app.state.db.operator_id(token)
    if operator is None:
        raise HTTPException(403, "Este usuario no es operador.")
    return operator


@router.post("/conversations/{phone}/take")
async def take(phone: str, request: Request, operator: str = Depends(require_operator)) -> Any:
    db = request.app.state.db
    row = await db.set_conversation_status(phone, "human")
    if row is None:
        raise HTTPException(404, "No existe esa conversación.")
    client = await db.find_client_by_phone(phone)
    if client:
        await db.move_escalations_for_client(client["id"], "pending", "claimed")
    log.info("chat_tomado", phone=phone, operator=operator)
    return row


@router.post("/conversations/{phone}/return")
async def give_back(phone: str, request: Request, operator: str = Depends(require_operator)) -> Any:
    db = request.app.state.db
    row = await db.set_conversation_status(phone, "bot")
    if row is None:
        raise HTTPException(404, "No existe esa conversación.")
    client = await db.find_client_by_phone(phone)
    if client:
        await db.move_escalations_for_client(client["id"], "claimed", "resolved")
    log.info("chat_devuelto", phone=phone, operator=operator)
    return row


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/conversations/{phone}/reply")
async def reply(
    phone: str, body: Reply, request: Request, operator: str = Depends(require_operator)
) -> Any:
    state = request.app.state
    db = state.db

    # Sólo con el chat tomado: si no, el bot y el humano le contestan a la vez.
    conversation = await db.get_conversation(phone)
    if (conversation or {}).get("status") != "human":
        raise HTTPException(409, "Tomá el chat antes de responder.")

    if window_remaining(await db.last_inbound_at(phone)) is None:
        raise HTTPException(
            422,
            "La ventana de 24 h está cerrada: el cliente no escribe hace más de un día. "
            "WhatsApp sólo acepta una plantilla aprobada.",
        )

    try:
        sids = await state.whatsapp.send(phone, body.text)
    except Exception as exc:  # noqa: BLE001
        log.error("operator_send_failed", phone=phone, error=str(exc))
        raise HTTPException(502, f"Twilio no aceptó el mensaje: {exc}") from exc

    # Queda en el mismo historial que lee el agente: cuando le devuelvan el
    # chat, sabe qué contestó el humano.
    client = await db.find_client_by_phone(phone)
    await db.record_message(
        client_id=(client or {}).get("id"),
        direction="outbound",
        body=body.text,
        twilio_sid=sids[0] if sids else None,
        metadata={"source": "operator", "operator": operator},
        phone=phone,
    )
    log.info("operator_reply", phone=phone, operator=operator, chars=len(body.text))
    return {"sent": len(sids)}

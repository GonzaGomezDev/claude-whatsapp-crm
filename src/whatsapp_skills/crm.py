"""CRM: lo que el panel le pide al agente.

El panel sólo lee de Supabase (anon key + RLS). Todo lo que escribe pasa por
acá, con la service_role key y las credenciales de Twilio, que nunca salen del
servidor. El token es el JWT de Supabase Auth del operador.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .observability.logging import get_logger

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

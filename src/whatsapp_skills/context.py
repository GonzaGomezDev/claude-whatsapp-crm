"""Capa 3: juntar el contexto antes de invocar al agente.

Traemos de una sola vez lo que el agente casi seguro va a necesitar: quién es el
cliente, de qué venían hablando, y qué tiene abierto. Cada uno de estos datos es
una tool call que Claude no tiene que hacer — y una tool call que no se hace son
dos round trips menos y unos cuantos tokens.

Es el equivalente de precargar el contexto en vez de hacer que el agente lo
descubra a fuerza de preguntas.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .agent.backend import Conversation
from .integrations.supabase_client import Database
from .observability.logging import get_logger

log = get_logger(__name__)

HISTORY_LIMIT = 10


async def build_conversation(
    db: Database, phone: str, message: str, handoff_note: str | None = None
) -> Conversation:
    """Arma la Conversation. Nunca levanta: sin contexto igual se puede responder."""
    client = await _safe(db.find_client_by_phone(phone), "find_client_by_phone")

    if not client:
        return Conversation(phone=phone, message=message, handoff_note=handoff_note)

    # Historial y tickets no dependen entre sí: van en paralelo.
    history, tickets = await asyncio.gather(
        _safe(db.recent_messages(client["id"], HISTORY_LIMIT), "recent_messages"),
        _safe(db.open_tickets(client["id"]), "open_tickets"),
    )

    return Conversation(
        phone=phone,
        message=message,
        history=history or [],
        client=client,
        open_tickets=tickets or [],
        session_id=client.get("claude_session_id"),
        handoff_note=handoff_note,
    )


async def _safe(coro: Any, label: str) -> Any:
    """Degradación elegante: si la base falla, el agente arranca sin ese dato.

    Es deliberado que esto no propague. Un historial que no cargó empeora la
    respuesta; una excepción acá deja al cliente sin ninguna respuesta.
    """
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("context_fetch_failed", step=label, error=str(exc))
        return None

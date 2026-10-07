"""Capa 1: el webhook de Twilio, y Capa 5: la respuesta de vuelta.

Dos decisiones que parecen detalles y no lo son:

1. Contestamos 200 vacío de inmediato y procesamos en background. Twilio corta
   el request a los 15s; el agente tarda ~8s. Sin este patrón, cualquier pico de
   latencia deja al cliente sin respuesta Y dispara un reintento.

2. Validamos la firma antes de tocar nada. El webhook es una URL pública: sin
   validación, cualquiera puede hacerte crear clientes y disparar escalados.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response

from .agent.backend import FALLBACK_REPLY
from .context import build_conversation
from .integrations.twilio_client import strip_whatsapp
from .observability.logging import get_logger
from .router import Route, route_message
from .skills.base import SkillContext

log = get_logger(__name__)
router = APIRouter()

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks) -> Response:
    app_state = request.app.state
    form = dict(await request.form())

    if app_state.settings.twilio_validate_signature:
        signature = request.headers.get("X-Twilio-Signature", "")
        if not app_state.whatsapp.validate_signature(
            app_state.settings.webhook_url, form, signature
        ):
            log.warning("invalid_signature", url=app_state.settings.webhook_url)
            return Response(status_code=403, content="invalid signature")

    phone = strip_whatsapp(str(form.get("From", "")))
    body = str(form.get("Body", "") or "")
    sid = str(form.get("MessageSid", "") or "") or None
    num_media = int(form.get("NumMedia", 0) or 0)

    if not phone:
        return Response(content=EMPTY_TWIML, media_type="application/xml")

    log.info("inbound", phone=phone, body=body, sid=sid)

    # Twilio reintenta ante cualquier no-2xx. 200 primero, trabajo después.
    background.add_task(_process, request.app, phone, body, sid, num_media)
    return Response(content=EMPTY_TWIML, media_type="application/xml")


async def _process(app: Any, phone: str, body: str, sid: str | None, num_media: int) -> None:
    state = app.state
    db = state.db

    # Idempotencia: si este MessageSid ya se guardó, es un reintento de Twilio y
    # el mensaje ya se procesó. Cortamos acá o el cliente recibe todo duplicado.
    recorded: dict[str, Any] | None = None
    try:
        recorded = await db.record_message(
            client_id=None, direction="inbound", body=body, twilio_sid=sid, phone=phone
        )
        if sid and recorded is None:
            log.info("duplicate_ignored", sid=sid)
            return
    except Exception as exc:  # noqa: BLE001
        # Sin registro no hay idempotencia, pero dejar al cliente sin respuesta
        # es peor. Seguimos y lo dejamos anotado.
        log.warning("inbound_record_failed", error=str(exc))

    try:
        await db.touch_conversation(phone)
    except Exception as exc:  # noqa: BLE001
        log.warning("conversation_touch_failed", error=str(exc))

    decision = route_message(body, num_media)
    if decision.route is Route.IGNORE:
        log.info("routed", route=decision.route.value, reason=decision.reason)
        return

    if decision.route is Route.DIRECT_REPLY:
        log.info("routed", route=decision.route.value, reason=decision.reason)
        await _reply(state, phone, decision.reply or "", client_id=None)
        return

    convo = await build_conversation(db, phone, body)
    ctx = SkillContext(
        phone=phone,
        settings=state.settings,
        db=db,
        payments=state.payments,
        notifier=state.notifier,
        client_id=(convo.client or {}).get("id"),
        conversation=convo.history,
    )

    try:
        result = await state.backend.run(convo, ctx)
    except Exception as exc:  # noqa: BLE001
        log.error("agent_failed", error=str(exc), error_type=type(exc).__name__)
        await _reply(state, phone, FALLBACK_REPLY, client_id=ctx.client_id)
        return

    client_id = ctx.client_id or (convo.client or {}).get("id")

    # El entrante se grabó antes de saber de quién era (el insert temprano es lo
    # que da idempotencia por twilio_sid). Recién ahora sabemos el cliente — si
    # no lo asociamos, el mensaje queda huérfano y el modelo nunca lo ve en el
    # historial de los turnos siguientes.
    if recorded and client_id:
        try:
            await db.attach_message_client(recorded["id"], client_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("inbound_attach_failed", error=str(exc))

    # El session_id de Claude Code se guarda para continuar la conversación en
    # el próximo mensaje. En messages_api viene None y no se toca nada.
    if result.session_id and client_id:
        try:
            await db.set_claude_session(client_id, result.session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("session_persist_failed", error=str(exc))

    await _reply(state, phone, result.reply_text, client_id=client_id)


async def _reply(state: Any, phone: str, text: str, client_id: str | None) -> None:
    try:
        sids = await state.whatsapp.send(phone, text)
    except Exception as exc:  # noqa: BLE001
        # Última línea: si ni siquiera se puede mandar el mensaje, que quede en
        # los logs con toda la data para reconstruirlo a mano.
        log.error("send_failed", phone=phone, error=str(exc), text=text[:200])
        return

    try:
        await state.db.record_message(
            client_id=client_id,
            direction="outbound",
            body=text,
            twilio_sid=sids[0] if sids else None,
            phone=phone,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("outbound_record_failed", error=str(exc))


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    return {
        "status": "ok",
        "backend": state.backend.name,
        "model": state.settings.anthropic_model,
        **state.registry.health(),
    }

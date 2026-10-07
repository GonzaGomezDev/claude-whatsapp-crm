"""Capa 5: mandar la respuesta de vuelta a WhatsApp.

No respondemos con TwiML dentro del webhook. El agente tarda ~8s y Twilio corta
el request a los 15s: cualquier pico de latencia deja al cliente sin respuesta y
dispara un reintento. En su lugar contestamos 200 vacío al toque, procesamos en
background y mandamos la respuesta por la REST API.
"""

from __future__ import annotations

import asyncio
from typing import Any

from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioRest

from ..observability.logging import get_logger

log = get_logger(__name__)

# WhatsApp corta los mensajes largos. Partimos nosotros para controlar dónde.
MAX_BODY_CHARS = 1500


class WhatsAppClient:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._rest = TwilioRest(account_sid, auth_token)
        self._validator = RequestValidator(auth_token)
        self.from_number = _as_whatsapp(from_number)

    def validate_signature(self, url: str, form: dict[str, Any], signature: str) -> bool:
        """Valida la firma de Twilio.

        La firma se calcula sobre la URL pública EXACTA, no sobre la que ve
        FastAPI detrás del túnel o del proxy. Si esto falla siempre, casi seguro
        PUBLIC_BASE_URL no coincide con lo que configuraste en la consola de
        Twilio (http vs https, barra final, subdominio de ngrok viejo).
        """
        return self._validator.validate(url, form, signature or "")

    async def send(self, to: str, body: str) -> list[str]:
        """Manda el mensaje, partiéndolo si hace falta. Devuelve los SIDs."""
        chunks = _split(body, MAX_BODY_CHARS)
        sids: list[str] = []
        for chunk in chunks:
            message = await asyncio.to_thread(
                self._rest.messages.create,
                from_=self.from_number,
                to=_as_whatsapp(to),
                body=chunk,
            )
            sids.append(message.sid)
            log.info("outbound", sid=message.sid, to=to, chars=len(chunk))
        return sids


def _as_whatsapp(number: str) -> str:
    number = number.strip()
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def strip_whatsapp(number: str) -> str:
    """'whatsapp:+5491123456789' -> '+5491123456789'."""
    return number.strip().removeprefix("whatsapp:")


def _split(body: str, limit: int) -> list[str]:
    """Parte por párrafo, después por oración, y recién al final a lo bruto."""
    body = body.strip()
    if len(body) <= limit:
        return [body or "…"]

    chunks: list[str] = []
    current = ""
    for paragraph in body.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            cut = paragraph.rfind(". ", 0, limit)
            cut = cut + 1 if cut > limit // 2 else limit
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        current = paragraph
    if current:
        chunks.append(current)
    return chunks

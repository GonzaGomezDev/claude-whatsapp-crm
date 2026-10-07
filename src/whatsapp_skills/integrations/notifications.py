"""A dónde avisar cuando el agente escala a un humano.

Un escalado que nadie ve es lo mismo que no escalar. Pero cada servicio espera
un JSON distinto, así que un solo `POST {"text": ...}` sólo funciona con Slack.

Acá el destino se deduce de `HANDOFF_NOTIFY_URL`:

    https://hooks.slack.com/services/...        -> Slack
    https://discord.com/api/webhooks/...        -> Discord
    https://ntfy.sh/mi-topico                   -> ntfy (push al teléfono)
    https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>  -> Telegram
    whatsapp:+5491167455471                     -> WhatsApp, por el Twilio que ya tenés
    (vacío)                                     -> sólo queda en los logs

Notificar es **best-effort**: el escalado ya se guardó en la base antes de
llegar acá. Si el aviso falla, se loguea y se sigue. Lo contrario —perder el
escalado porque Slack estaba caído— sí sería un problema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

import httpx

from ..observability.logging import get_logger

log = get_logger(__name__)

TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Escalation:
    """Lo que hay que contarle al equipo."""

    reason: str
    summary: str
    phone: str
    urgency: str = "normal"
    ticket_ref: int | None = None
    escalation_id: str | None = None

    def as_text(self) -> str:
        cabecera = f"[{self.urgency.upper()}] Escalado: {self.reason}"
        ticket = f"\nTicket {self.ticket_ref}" if self.ticket_ref else ""
        return (
            f"{cabecera}\n"
            f"Cliente: {self.phone}{ticket}\n\n"
            f"{self.summary}\n\n"
            f"Para responder:  python scripts/inbox.py show {self.ticket_ref or ''}"
        )


@runtime_checkable
class Notifier(Protocol):
    name: str

    async def send(self, escalation: Escalation) -> bool: ...


# ── Implementaciones ────────────────────────────────────────────────────────


class LogNotifier:
    """Sin destino configurado. El escalado igual queda visible en los logs."""

    name = "log"

    async def send(self, escalation: Escalation) -> bool:
        log.warning(
            "escalation_sin_destino",
            reason=escalation.reason,
            phone=escalation.phone,
            ticket_ref=escalation.ticket_ref,
            detail="Configurá HANDOFF_NOTIFY_URL para que el equipo se entere.",
        )
        return False


@dataclass
class JSONWebhookNotifier:
    """Slack y Discord: mismo verbo, distinta clave para el texto."""

    name: str
    url: str
    field: str  # "text" en Slack, "content" en Discord
    limit: int = 4000

    async def send(self, escalation: Escalation) -> bool:
        return await _post(
            self.name, self.url, json={self.field: escalation.as_text()[: self.limit]}
        )


@dataclass
class NtfyNotifier:
    """ntfy.sh: sin cuenta, sin API key. Elegís un tópico y la app te lo pushea.

    Es lo más rápido que hay para tener el aviso en el teléfono.
    """

    name = "ntfy"
    url: str

    _PRIORIDAD = {"normal": "default", "high": "high", "urgent": "urgent"}

    async def send(self, escalation: Escalation) -> bool:
        titulo = f"Escalado {escalation.reason}"
        if escalation.ticket_ref:
            titulo += f" · ticket {escalation.ticket_ref}"
        return await _post(
            self.name,
            self.url,
            content=escalation.as_text().encode("utf-8"),
            headers={
                # ntfy lee los metadatos de los headers, no del body.
                "Title": titulo.encode("utf-8"),
                "Priority": self._PRIORIDAD.get(escalation.urgency, "default"),
                "Tags": "rotating_light" if escalation.urgency == "urgent" else "bell",
            },
        )


@dataclass
class TelegramNotifier:
    """La URL trae el token y el chat_id: .../sendMessage?chat_id=123"""

    name = "telegram"
    url: str
    chat_id: str

    async def send(self, escalation: Escalation) -> bool:
        return await _post(
            self.name,
            self.url,
            json={"chat_id": self.chat_id, "text": escalation.as_text()[:4000]},
        )


@dataclass
class WhatsAppNotifier:
    """Avisar por el mismo canal que atiende el bot, con el Twilio que ya tenés.

    Cero servicios nuevos. La contra: al operador le aplica la misma ventana de
    24 h, así que tiene que haberle escrito al número del bot en el último día
    (con el sandbox, además, tiene que haberse unido).
    """

    name = "whatsapp"
    client: Any
    to: str

    async def send(self, escalation: Escalation) -> bool:
        try:
            await self.client.send(self.to, escalation.as_text())
        except Exception as exc:  # noqa: BLE001
            log.warning("notify_failed", target="whatsapp", error=str(exc))
            return False
        return True


# ── Fábrica ─────────────────────────────────────────────────────────────────


def build_notifier(settings: Any, whatsapp_client: Any = None) -> Notifier:
    destino = (getattr(settings, "handoff_notify_url", "") or "").strip()
    if not destino:
        return LogNotifier()

    if destino.startswith("whatsapp:") or destino.startswith("+"):
        if whatsapp_client is None:
            log.error(
                "notifier_sin_twilio",
                detail="HANDOFF_NOTIFY_URL apunta a WhatsApp pero no hay cliente Twilio.",
            )
            return LogNotifier()
        return WhatsAppNotifier(client=whatsapp_client, to=destino)

    host = (urlparse(destino).hostname or "").lower()

    if "hooks.slack.com" in host:
        return JSONWebhookNotifier(name="slack", url=destino, field="text")

    if "discord.com" in host or "discordapp.com" in host:
        # Discord corta en 2000 caracteres.
        return JSONWebhookNotifier(
            name="discord", url=destino, field="content", limit=2000
        )

    if "ntfy" in host:
        return NtfyNotifier(url=destino)

    if "api.telegram.org" in host:
        chat_id = (parse_qs(urlparse(destino).query).get("chat_id") or [""])[0]
        if not chat_id:
            log.error(
                "notifier_telegram_sin_chat_id",
                detail="Agregá ?chat_id=<ID> al final de la URL de Telegram.",
            )
            return LogNotifier()
        return TelegramNotifier(url=destino, chat_id=chat_id)

    # Un webhook propio (n8n, Make, tu backend): mandamos el shape más común.
    return JSONWebhookNotifier(name="webhook", url=destino, field="text")


async def _post(name: str, url: str, **kwargs: Any) -> bool:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
            response = await http.post(url, **kwargs)
    except Exception as exc:  # noqa: BLE001 - notificar es best-effort por diseño
        log.warning("notify_failed", target=name, error=str(exc))
        return False

    if response.status_code >= 400:
        log.warning(
            "notify_rejected",
            target=name,
            status=response.status_code,
            body=response.text[:200],
        )
        return False
    return True

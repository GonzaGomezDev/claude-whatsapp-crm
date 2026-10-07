"""A dónde va el aviso de un escalado.

Cada servicio espera un JSON distinto. Mandar el shape de Slack a un webhook de
Discord devuelve 400 y el escalado queda sin avisar — que es lo mismo que no
escalar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from whatsapp_skills.integrations.notifications import (
    Escalation,
    JSONWebhookNotifier,
    LogNotifier,
    NtfyNotifier,
    TelegramNotifier,
    WhatsAppNotifier,
    build_notifier,
)


@dataclass
class FakeSettings:
    handoff_notify_url: str = ""


class FakeWhatsApp:
    def __init__(self) -> None:
        self.enviados: list[tuple[str, str]] = []

    async def send(self, to: str, body: str) -> list[str]:
        self.enviados.append((to, body))
        return ["SM123"]


ESCALADO = Escalation(
    reason="angry_customer",
    summary="Pide la cotización hace tres días y nadie le contestó.",
    phone="+5491167455471",
    urgency="high",
    ticket_ref=4001,
)


# ── Detección del destino ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "esperado", "campo"),
    [
        ("https://hooks.slack.com/services/T00/B00/xxx", "slack", "text"),
        ("https://discord.com/api/webhooks/123/abc", "discord", "content"),
        ("https://discordapp.com/api/webhooks/123/abc", "discord", "content"),
        ("https://n8n.midominio.com/webhook/escalados", "webhook", "text"),
    ],
)
def test_detecta_webhooks_json(url, esperado, campo):
    n = build_notifier(FakeSettings(url))
    assert isinstance(n, JSONWebhookNotifier)
    assert n.name == esperado
    assert n.field == campo


def test_discord_recorta_a_2000_caracteres():
    """Discord rechaza cualquier content más largo."""
    n = build_notifier(FakeSettings("https://discord.com/api/webhooks/1/a"))
    assert n.limit == 2000


def test_detecta_ntfy():
    assert isinstance(build_notifier(FakeSettings("https://ntfy.sh/mis-escalados")), NtfyNotifier)


def test_detecta_telegram_y_saca_el_chat_id():
    n = build_notifier(
        FakeSettings("https://api.telegram.org/bot123:ABC/sendMessage?chat_id=987")
    )
    assert isinstance(n, TelegramNotifier)
    assert n.chat_id == "987"


def test_telegram_sin_chat_id_no_rompe_pero_avisa():
    """Mejor caer al log que mandar requests que Telegram va a rechazar siempre."""
    n = build_notifier(FakeSettings("https://api.telegram.org/bot123:ABC/sendMessage"))
    assert isinstance(n, LogNotifier)


@pytest.mark.parametrize("url", ["whatsapp:+5491167455471", "+5491167455471"])
def test_detecta_whatsapp(url):
    n = build_notifier(FakeSettings(url), FakeWhatsApp())
    assert isinstance(n, WhatsAppNotifier)
    assert n.to == url


def test_whatsapp_sin_cliente_twilio_cae_al_log():
    assert isinstance(build_notifier(FakeSettings("whatsapp:+549")), LogNotifier)


def test_sin_url_configurada_queda_en_los_logs():
    assert isinstance(build_notifier(FakeSettings("")), LogNotifier)
    assert isinstance(build_notifier(FakeSettings("   ")), LogNotifier)


# ── Contenido del aviso ─────────────────────────────────────────────────────


def test_el_texto_trae_lo_que_el_humano_necesita():
    texto = ESCALADO.as_text()
    assert "HIGH" in texto
    assert "angry_customer" in texto
    assert "+5491167455471" in texto
    assert "4001" in texto
    assert ESCALADO.summary in texto
    # Y cómo actuar, sin tener que buscarlo.
    assert "inbox.py" in texto


def test_sin_ticket_el_texto_igual_sirve():
    """Si no se pudo identificar al cliente, no hay ticket — pero hay que avisar."""
    texto = Escalation(
        reason="client_lookup_failed", summary="La base no responde", phone="+549"
    ).as_text()
    assert "client_lookup_failed" in texto
    assert "Ticket" not in texto


# ── Envío ───────────────────────────────────────────────────────────────────


async def test_whatsapp_manda_por_twilio():
    wa = FakeWhatsApp()
    assert await WhatsAppNotifier(client=wa, to="whatsapp:+549").send(ESCALADO) is True
    destino, cuerpo = wa.enviados[0]
    assert destino == "whatsapp:+549"
    assert "angry_customer" in cuerpo


async def test_un_fallo_al_notificar_no_levanta_excepcion():
    """El escalado ya está en la base. Notificar es best-effort."""

    class Roto:
        async def send(self, to: str, body: str) -> list[str]:
            raise ConnectionError("Twilio caído")

    assert await WhatsAppNotifier(client=Roto(), to="+549").send(ESCALADO) is False


async def test_el_log_notifier_reporta_que_no_hubo_aviso():
    assert await LogNotifier().send(ESCALADO) is False


async def test_ntfy_manda_los_metadatos_en_headers(monkeypatch):
    """ntfy lee título y prioridad de los headers, no del body."""
    capturado: dict[str, Any] = {}

    async def fake_post(name: str, url: str, **kwargs: Any) -> bool:
        capturado.update(kwargs)
        return True

    monkeypatch.setattr(
        "whatsapp_skills.integrations.notifications._post", fake_post
    )
    assert await NtfyNotifier(url="https://ntfy.sh/x").send(ESCALADO) is True
    assert capturado["headers"]["Priority"] == "high"
    assert b"4001" in capturado["headers"]["Title"]
    assert b"angry_customer" in capturado["content"]

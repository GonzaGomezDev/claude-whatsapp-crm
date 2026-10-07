"""El bot se calla cuando una persona tomó el chat.

Fakes en vez de Supabase/Twilio: lo que se prueba es la decisión del webhook,
no las integraciones.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from whatsapp_skills.agent.backend import AgentResult
from whatsapp_skills.webhook import _process

PHONE = "+5491100000000"


class FakeDB:
    def __init__(self, status: str) -> None:
        self.status = status
        self.messages: list[dict[str, Any]] = []

    async def record_message(self, **row: Any) -> dict[str, Any]:
        self.messages.append(row)
        return {"id": str(len(self.messages)), **row}

    async def touch_conversation(self, phone: str) -> dict[str, Any]:
        return {"phone": phone, "status": self.status}

    async def get_conversation(self, phone: str) -> dict[str, Any]:
        return {"phone": phone, "status": self.status}

    async def find_client_by_phone(self, phone: str) -> None:
        return None


class FakeBackend:
    name = "fake"

    def __init__(self, during_run: Any = None) -> None:
        self.calls = 0
        self.during_run = during_run

    async def run(self, convo: Any, ctx: Any) -> AgentResult:
        self.calls += 1
        if self.during_run:
            self.during_run()
        return AgentResult(reply_text="Respuesta del bot")


class FakeWhatsApp:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, to: str, body: str) -> list[str]:
        self.sent.append(body)
        return ["SM1"]


def _app(db: FakeDB, backend: FakeBackend) -> Any:
    state = SimpleNamespace(
        db=db, backend=backend, whatsapp=FakeWhatsApp(),
        settings=None, payments=None, notifier=None,
    )
    return SimpleNamespace(state=state)


async def test_en_modo_humano_el_bot_no_contesta_pero_el_mensaje_queda():
    db, backend = FakeDB("human"), FakeBackend()
    app = _app(db, backend)

    await _process(app, PHONE, "necesito el presupuesto", "SM_IN", 0)

    assert backend.calls == 0
    assert app.state.whatsapp.sent == []
    assert db.messages[0]["direction"] == "inbound"
    assert db.messages[0]["phone"] == PHONE


async def test_en_modo_humano_ni_la_respuesta_fija_del_router_sale():
    db = FakeDB("human")
    app = _app(db, FakeBackend())

    await _process(app, PHONE, "gracias", "SM_IN", 0)

    assert app.state.whatsapp.sent == []


async def test_en_modo_bot_contesta_el_agente():
    db, backend = FakeDB("bot"), FakeBackend()
    app = _app(db, backend)

    await _process(app, PHONE, "necesito el presupuesto", "SM_IN", 0)

    assert backend.calls == 1
    assert app.state.whatsapp.sent == ["Respuesta del bot"]

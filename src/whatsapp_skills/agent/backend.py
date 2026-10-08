"""El contrato que cumplen los dos backends.

Este archivo es el corazón del repo. `webhook.py` no sabe —ni le importa— si
abajo hay una llamada a la Messages API o un subproceso `claude -p`. Le pide a
un `AgentBackend` que resuelva una conversación y recibe un `AgentResult`.

Es el mismo argumento que el video hace sobre las Skills, una capa más abajo:
separación de responsabilidades. La Skill no cambia, cambia el backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..skills.base import SkillContext


@dataclass
class Conversation:
    """Lo que la Capa 3 juntó antes de invocar al agente."""

    phone: str
    message: str
    history: list[dict[str, str]] = field(default_factory=list)
    client: dict[str, Any] | None = None
    open_tickets: list[dict[str, Any]] = field(default_factory=list)
    # session_id de Claude Code, para --resume. Sin uso en messages_api.
    session_id: str | None = None
    # Lo que acordó el humano antes de devolver el chat (CRM).
    handoff_note: str | None = None

    def as_messages(self) -> list[dict[str, Any]]:
        """Historial + mensaje actual, en el formato de la Messages API."""
        messages: list[dict[str, Any]] = []
        for turn in self.history:
            role = "assistant" if turn.get("direction") == "outbound" else "user"
            body = (turn.get("body") or "").strip()
            if not body:
                continue
            # La API rechaza dos turnos seguidos del mismo rol.
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += f"\n{body}"
            else:
                messages.append({"role": role, "content": body})

        # La API exige que el primer mensaje sea del usuario. Un historial que
        # arranca con un turno del asistente es posible —el equipo puede haber
        # escrito primero desde scripts/inbox.py, o el registro del entrante
        # puede haber fallado— y devolvería un 400.
        while messages and messages[0]["role"] == "assistant":
            messages.pop(0)

        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += f"\n{self.message}"
        else:
            messages.append({"role": "user", "content": self.message})
        return messages


@dataclass
class ToolCall:
    """Una llamada a tool, tal como quedó registrada. Alimenta los logs."""

    name: str
    input: dict[str, Any]
    latency_ms: float = 0.0
    is_error: bool = False
    error_type: str | None = None


@dataclass
class Usage:
    """Consumo del turno. Los dos backends reportan lo que su superficie expone.

    messages_api llena tokens; el backend cli llena cost_usd y a veces tokens.
    Los campos que un backend no puede conocer quedan en None — mentir acá
    haría que las métricas del video no signifiquen nada.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost_usd: float | None = None


@dataclass
class AgentResult:
    reply_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    escalated: bool = False
    session_id: str | None = None
    stop_reason: str | None = None
    iterations: int = 0

    @property
    def used_tools(self) -> list[str]:
        return [c.name for c in self.tool_calls]


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    async def run(self, convo: Conversation, ctx: SkillContext) -> AgentResult:
        """Resuelve un turno completo y devuelve qué responderle al cliente."""
        ...

    async def complete(self, system: str, prompt: str) -> str:
        """Una respuesta de texto, sin tools (ej. resumir un cliente para el CRM).

        El prompt puede traer texto de clientes: es input no confiable y tiene
        que correr con el mismo aislamiento que run().
        """
        ...


# Mensaje de último recurso. Si el backend no puede producir texto, el cliente
# igual recibe algo: el silencio es la peor respuesta posible en WhatsApp.
FALLBACK_REPLY = (
    "Perdón, tuve un inconveniente técnico procesando tu mensaje. "
    "Ya avisé al equipo para que te contacte."
)

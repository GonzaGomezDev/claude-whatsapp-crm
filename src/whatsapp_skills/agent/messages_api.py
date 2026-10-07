"""Backend de producción: loop agéntico manual sobre la Messages API.

Es manual y no usa el Tool Runner del SDK a propósito. El Tool Runner genera los
schemas desde la firma de la función y no deja setear `defer_loading`, ni da un
punto donde meter timeout por tool, circuit breaker, rate limiting y logging de
latencia. Todo el manejo de errores que hace interesante a esta arquitectura
vive justamente en ese punto.

El loop, en una línea: pedir -> ejecutar en paralelo lo que Claude pidió ->
devolver TODOS los resultados en UN mensaje -> repetir hasta que deje de pedir.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from anthropic import AsyncAnthropic

from ..observability.logging import get_logger
from ..skills.base import SkillContext
from ..skills.registry import SkillRegistry, ToolMode
from .backend import FALLBACK_REPLY, AgentResult, Conversation, ToolCall, Usage
from .prompt import system_blocks

log = get_logger(__name__)

# En un bot de atención al cliente, un stop_reason "refusal" sin fallback deja
# al cliente sin respuesta. El servidor rutea solo según la categoría.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class MessagesAPIBackend:
    name = "messages_api"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        api_key: str,
        model: str = "claude-opus-5",
        effort: str = "medium",
        max_tokens: int = 8000,
        max_iterations: int = 8,
        tool_mode: ToolMode = "full",
    ) -> None:
        self.registry = registry
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.tool_mode = tool_mode
        # Se apaga solo si el SDK instalado no conoce el parámetro.
        self._server_fallbacks = True

    # ── Loop ────────────────────────────────────────────────────────────────

    async def run(self, convo: Conversation, ctx: SkillContext) -> AgentResult:
        system = system_blocks(self.registry.system_prompt_block(), convo)
        tools = self.registry.anthropic_tools(self.tool_mode)
        messages: list[dict[str, Any]] = convo.as_messages()

        log.info("agent_start", backend=self.name, skills=len(self.registry.docs))

        calls: list[ToolCall] = []
        usage = Usage(input_tokens=0, output_tokens=0, cache_read_tokens=0)
        escalated = False
        response: Any = None
        iteration = 0

        for iteration in range(1, self.max_iterations + 1):  # noqa: B007
            response = await self._create(system=system, tools=tools, messages=messages)
            _accumulate(usage, response)

            # Siempre mirar stop_reason ANTES de leer content: en un refusal, el
            # content puede venir vacío.
            if response.stop_reason == "refusal":
                detail = getattr(response, "stop_details", None)
                log.warning(
                    "refusal",
                    category=getattr(detail, "category", None),
                    explanation=getattr(detail, "explanation", None),
                )
                return AgentResult(
                    reply_text=FALLBACK_REPLY,
                    tool_calls=calls,
                    usage=usage,
                    escalated=True,
                    stop_reason="refusal",
                    iterations=iteration,
                )

            if response.stop_reason == "pause_turn":
                # Una server tool se quedó a mitad de camino. Reenviamos el turno
                # pausado tal cual para que lo continúe.
                messages.append({"role": "assistant", "content": response.content})
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                break

            # El turno del assistant se agrega COMPLETO, incluidos los bloques de
            # thinking: sacarlos rompe la continuidad del razonamiento.
            messages.append({"role": "assistant", "content": response.content})

            results, iteration_calls, iteration_escalated = await self._execute_parallel(
                tool_uses, ctx
            )
            calls.extend(iteration_calls)
            escalated = escalated or iteration_escalated

            # TODOS los tool_result en UN solo mensaje user. Partirlos en varios
            # le enseña al modelo a dejar de paralelizar.
            messages.append({"role": "user", "content": results})
        else:
            log.warning("max_iterations_reached", limit=self.max_iterations)

        reply = _extract_text(response) or FALLBACK_REPLY
        log.info(
            "agent_reply",
            text=reply,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
        )
        return AgentResult(
            reply_text=reply,
            tool_calls=calls,
            usage=usage,
            escalated=escalated,
            stop_reason=getattr(response, "stop_reason", None),
            iterations=iteration,
        )

    # ── Ejecución en paralelo ───────────────────────────────────────────────

    async def _execute_parallel(
        self, tool_uses: list[Any], ctx: SkillContext
    ) -> tuple[list[dict[str, Any]], list[ToolCall], bool]:
        ctx.scratch["breakers"] = self.registry.breaker.snapshot()

        async def run_one(block: Any) -> tuple[dict[str, Any], ToolCall]:
            started = time.monotonic()
            result, is_error = await self.registry.dispatch(block.name, dict(block.input), ctx)
            latency = (time.monotonic() - started) * 1000
            call = ToolCall(
                name=block.name,
                input=dict(block.input),
                latency_ms=latency,
                is_error=is_error,
                error_type=(result or {}).get("error_type") if isinstance(result, dict) else None,
            )
            payload: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _as_text(result),
            }
            # Un tool_result de error igual se devuelve. Descartarlo dejaría un
            # tool_use sin respuesta y la API rechaza el siguiente request.
            if is_error:
                payload["is_error"] = True
            return payload, call

        pairs = await asyncio.gather(*(run_one(b) for b in tool_uses))
        results = [p[0] for p in pairs]
        calls = [p[1] for p in pairs]
        escalated = any(c.name == "escalate_to_human" and not c.is_error for c in calls)
        return results, calls, escalated

    # ── Request ─────────────────────────────────────────────────────────────

    async def _create(self, **kwargs: Any) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            **kwargs,
        }

        if self._server_fallbacks:
            try:
                return await self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **params
                )
            except TypeError as exc:
                # El SDK instalado no conoce `fallbacks`. Seguimos sin él en vez
                # de morir, pero lo decimos: es una red de seguridad menos.
                log.warning("server_fallbacks_unavailable", detail=str(exc))
                self._server_fallbacks = False

        return await self.client.beta.messages.create(**params)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _accumulate(usage: Usage, response: Any) -> None:
    raw = getattr(response, "usage", None)
    if raw is None:
        return
    usage.input_tokens = (usage.input_tokens or 0) + (getattr(raw, "input_tokens", 0) or 0)
    usage.output_tokens = (usage.output_tokens or 0) + (getattr(raw, "output_tokens", 0) or 0)
    usage.cache_read_tokens = (usage.cache_read_tokens or 0) + (
        getattr(raw, "cache_read_input_tokens", 0) or 0
    )
    usage.cache_write_tokens = (usage.cache_write_tokens or 0) + (
        getattr(raw, "cache_creation_input_tokens", 0) or 0
    )


def _extract_text(response: Any) -> str:
    if response is None:
        return ""
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "\n".join(p.strip() for p in parts if p and p.strip()).strip()


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)

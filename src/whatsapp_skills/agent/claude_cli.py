"""Backend de desarrollo: `claude -p` como subproceso.

Usa tu suscripción de Claude Code en vez de una API key, así podés iterar sobre
los SKILL.md sin gastar. Las tools llegan por un server MCP que expone el mismo
registry, así que se ejecutan exactamente igual que en producción.

## Aislamiento (leé esto antes de tocar nada acá)

Un mensaje de WhatsApp es input NO CONFIABLE: lo manda cualquiera que tenga el
número. Claude Code trae ~23 tools propias —Read, Glob, Grep, Bash, WebFetch,
CronCreate, SendMessage— y `--allowedTools` NO es una lista exclusiva: con
`--permission-mode dontAsk` sólo pre-aprueba, no restringe. O sea que el agente
tenía acceso al filesystem del repo, donde vive el `.env` con las credenciales
reales de Twilio, Supabase y Stripe.

Tres capas para cerrar eso:

  1. `BLOCKED_BUILTINS` — deny explícito de todas las built-in. El deny gana.
  2. `cwd` = un directorio temporal VACÍO, no el repo. Aunque una tool de
     lectura se filtre, no hay nada que leer.
  3. `_assert_tool_surface` — el evento `system` del stream declara qué tools
     quedaron activas. Si aparece una que no esperábamos, se loguea fuerte.
     Una deny list a mano se pudre cuando Claude Code agrega tools; esto hace
     que te enteres el mismo día en vez de dentro de seis meses.

## Lo que este backend NO puede hacer

El loop lo maneja Claude Code, así que no hay `count_tokens`, ni
`defer_loading`/`tool_search`, ni control del batching de tool_result, ni
breakpoints de prompt caching. Y un subproceso por mensaje cuesta 1-3s de
arranque. Para desarrollo está perfecto; para producción usá `messages_api`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..observability.logging import get_logger
from ..skills.base import SkillContext
from ..skills.registry import SkillRegistry, repo_root
from .backend import FALLBACK_REPLY, AgentResult, Conversation, ToolCall, Usage
from .prompt import cli_system_prompt

log = get_logger(__name__)

MCP_SERVER_NAME = "skills"

# Todas las tools built-in de Claude Code. El agente tiene que resolver con las
# mismas tools que en producción: cualquier otra es a la vez un agujero de
# seguridad y una divergencia entre backends que invalida la comparación.
#
# Si Claude Code agrega una tool nueva, esta lista queda incompleta — por eso
# existe _assert_tool_surface, que avisa en runtime.
BLOCKED_BUILTINS = [
    # Filesystem. El .env con credenciales reales vive en el repo.
    "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
    # Ejecución y delegación.
    "Bash", "BashOutput", "KillShell", "Task", "Workflow", "Skill", "SlashCommand",
    # Red y salida de datos.
    "WebFetch", "WebSearch", "RemoteTrigger", "PushNotification", "SendMessage",
    # Persistencia más allá de este mensaje.
    "CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "Monitor",
    # Descubrimiento de otras tools.
    "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool",
    # Varios del harness.
    "DesignSync", "EnterWorktree", "ExitWorktree", "TaskOutput", "TaskStop",
    "ReportFindings", "ExitPlanMode", "TodoWrite", "Artifact", "AskUserQuestion",
]


class ClaudeCLIBackend:
    name = "cli"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        cli_path: str = "claude",
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        timeout_s: float = 120.0,
        max_budget_usd: float = 0.50,
        max_concurrency: int = 4,
    ) -> None:
        self.registry = registry
        self.cli_path = cli_path
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        self.max_budget_usd = max_budget_usd
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # Workspace vacío y fuera del repo. Es la capa de aislamiento que no
        # depende de que la deny list esté completa.
        self._workspace = Path(tempfile.mkdtemp(prefix="wa-skills-workspace-"))
        self._expected_tools = {f"mcp__{MCP_SERVER_NAME}__{n}" for n in registry.tools}

    def close(self) -> None:
        shutil.rmtree(self._workspace, ignore_errors=True)

    # ── Run ─────────────────────────────────────────────────────────────────

    async def run(self, convo: Conversation, ctx: SkillContext) -> AgentResult:
        log.info("agent_start", backend=self.name, skills=len(self.registry.docs))

        async with self._semaphore:
            outcome = await self._invoke(convo, resume=convo.session_id)

            # Un session_id viejo (base restaurada, sesiones purgadas) hace
            # fallar el --resume. Reintentamos una vez sin él antes de rendirnos.
            if outcome is None and convo.session_id:
                log.warning("resume_failed", session_id=convo.session_id)
                outcome = await self._invoke(convo, resume=None)

        if outcome is None:
            return AgentResult(
                reply_text=FALLBACK_REPLY, escalated=True, stop_reason="cli_error"
            )

        payload, calls = outcome
        result = AgentResult(
            reply_text=(payload.get("result") or "").strip() or FALLBACK_REPLY,
            tool_calls=calls,
            usage=_usage_from(payload),
            session_id=payload.get("session_id"),
            stop_reason=payload.get("subtype") or payload.get("stop_reason"),
            iterations=int(payload.get("num_turns") or 1),
        )
        result.escalated = any(
            c.name == "escalate_to_human" and not c.is_error for c in calls
        )

        log.info(
            "agent_reply",
            text=result.reply_text,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
            cost_usd=result.usage.cost_usd,
        )
        return result

    async def complete(self, system: str, prompt: str) -> str:
        """Texto sin tools, con el mismo aislamiento que run().

        El prompt trae historial de clientes (input no confiable): sin tools
        built-in (`--tools ""` más el deny explícito), sin MCP y en el workspace
        vacío. Va por stdin: un historial largo no entra en la línea de comando
        de Windows (32 KB).
        """
        async with self._semaphore:
            process = await asyncio.create_subprocess_exec(
                *self._complete_argv(system),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
                env={**os.environ, "LOG_FORMAT": "json"},
            )
            try:
                out, err = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=self.timeout_s
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError("Claude Code no respondió a tiempo.") from None

        if process.returncode != 0:
            log.error("cli_complete_failed", returncode=process.returncode,
                      stderr=err.decode("utf-8", "replace")[-800:])
            raise RuntimeError("Claude Code devolvió un error.")
        payload = json.loads(out.decode("utf-8", "replace") or "{}")
        return (payload.get("result") or "").strip()

    def _complete_argv(self, system: str) -> list[str]:
        return [
            self.cli_path,
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--effort", "low",
            "--tools", "",
            "--disallowedTools", ",".join(BLOCKED_BUILTINS),
            "--mcp-config", json.dumps({"mcpServers": {}}),
            "--strict-mcp-config",
            "--setting-sources", "project",
            "--system-prompt", system,
            "--max-budget-usd", str(self.max_budget_usd),
            "--permission-mode", "dontAsk",
        ]

    # ── Subproceso ──────────────────────────────────────────────────────────

    async def _invoke(
        self, convo: Conversation, resume: str | None
    ) -> tuple[dict[str, Any], list[ToolCall]] | None:
        argv = self._build_argv(convo, resume)
        env = {
            **os.environ,
            "WA_SKILLS_PHONE": convo.phone,
            "WA_SKILLS_CLIENT_ID": (convo.client or {}).get("id") or "",
            "LOG_FORMAT": "json",
        }

        process = await asyncio.create_subprocess_exec(
            *argv,
            # Sin esto el subproceso hereda stdin y puede quedarse esperando
            # para siempre si algo intenta leer de ahí.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._workspace),
            env=env,
        )

        stderr_tail: deque[str] = deque(maxlen=25)
        try:
            # stdout y stderr en paralelo: si sólo leyeras stdout, el pipe de
            # stderr se llena y el subproceso queda bloqueado para siempre.
            (payload, calls), _ = await asyncio.wait_for(
                asyncio.gather(
                    self._consume_stream(process.stdout),
                    _drain(process.stderr, stderr_tail),
                ),
                timeout=self.timeout_s,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            log.error("cli_timeout", timeout_s=self.timeout_s)
            return None

        returncode = await process.wait()
        if returncode != 0 or payload is None:
            log.error(
                "cli_failed",
                returncode=returncode,
                stderr="\n".join(stderr_tail)[-800:],
            )
            return None

        return payload, calls

    async def _consume_stream(
        self, stream: asyncio.StreamReader
    ) -> tuple[dict[str, Any] | None, list[ToolCall]]:
        """Lee el stream-json y loguea cada tool call a medida que pasa.

        Sin esto, en modo cli no ves NINGÚN `Claude calling:`: las tools corren
        dentro del subproceso MCP y sus logs se van con él. La Capa 6 no existía
        en este backend.
        """
        calls: list[ToolCall] = []
        pending: dict[str, tuple[ToolCall, float]] = {}
        final: dict[str, Any] | None = None

        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = event.get("type")

            if kind == "system" and event.get("subtype") == "init":
                self._assert_tool_surface(event.get("tools") or [])
                _assert_mcp_healthy(event.get("mcp_servers") or [])

            elif kind == "assistant":
                for block in _content_blocks(event):
                    if block.get("type") != "tool_use":
                        continue
                    name = str(block.get("name", "")).removeprefix(
                        f"mcp__{MCP_SERVER_NAME}__"
                    )
                    call = ToolCall(name=name, input=block.get("input") or {})
                    calls.append(call)
                    pending[str(block.get("id"))] = (call, time.monotonic())
                    log.info("tool_call", tool=name, input=call.input)

            elif kind == "user":
                for block in _content_blocks(event):
                    if block.get("type") != "tool_result":
                        continue
                    entry = pending.pop(str(block.get("tool_use_id")), None)
                    is_error = bool(block.get("is_error"))
                    latency = (time.monotonic() - entry[1]) * 1000 if entry else 0.0
                    if entry is not None:
                        entry[0].is_error = is_error
                        entry[0].latency_ms = latency
                    log.info(
                        "tool_result",
                        tool=entry[0].name if entry else "?",
                        result=_unwrap(block.get("content")),
                        latency_ms=latency,
                        error_type="tool_error" if is_error else None,
                    )

            elif kind == "result":
                final = event

        return final, calls

    def _assert_tool_surface(self, available: list[str]) -> list[str]:
        """Devuelve (y loguea) las tools activas que no declaramos.

        Una deny list escrita a mano se pudre: Claude Code agrega tools y de
        golpe tu agente de WhatsApp puede leer archivos otra vez. Esto convierte
        esa degradación silenciosa en una línea de log y un valor testeable.
        """
        extra = sorted(set(available) - self._expected_tools)
        if extra:
            log.error(
                "unexpected_tools_available",
                tools=extra,
                detail=(
                    "El agente tiene tools que no declaramos. Agregalas a "
                    "BLOCKED_BUILTINS en agent/claude_cli.py. Hasta entonces, un "
                    "mensaje de WhatsApp malicioso podría usarlas."
                ),
            )
        return extra

    def _build_argv(self, convo: Conversation, resume: str | None) -> list[str]:
        allowed = ",".join(sorted(self._expected_tools))

        argv = [
            self.cli_path,
            "--print",
            # stream-json en vez de json: es lo que deja ver los tool_use y
            # tool_result a medida que pasan. Requiere --verbose.
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
            "--effort", self.effort,
            "--mcp-config", json.dumps(self._mcp_config()),
            # Sin esto el agente vería los servers MCP del usuario.
            "--strict-mcp-config",
            "--allowedTools", allowed,
            "--disallowedTools", ",".join(BLOCKED_BUILTINS),
            # Workspace vacío: sin settings de proyecto que cargar.
            "--setting-sources", "project",
            "--append-system-prompt",
            cli_system_prompt(self.registry.system_prompt_block(), convo),
            "--max-budget-usd", str(self.max_budget_usd),
            "--permission-mode", "dontAsk",
        ]
        if resume:
            argv += ["--resume", resume]
        # ponytail: va en la línea de comando (32 KB en Windows). Diez mensajes
        # entran de sobra; si se agranda HISTORY_LIMIT, pasarlo por stdin como complete().
        argv.append(convo.as_prompt())
        return argv

    def _mcp_config(self) -> dict[str, Any]:
        return {
            "mcpServers": {
                MCP_SERVER_NAME: {
                    "command": sys.executable,
                    "args": ["-m", "whatsapp_skills.agent.mcp_server"],
                    "env": {
                        "PYTHONPATH": str(Path(repo_root()) / "src"),
                        "PYTHONIOENCODING": "utf-8",
                    },
                }
            }
        }


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _drain(stream: asyncio.StreamReader, tail: deque[str]) -> None:
    """Vacía stderr para que el pipe no se llene y bloquee al subproceso."""
    while True:
        raw = await stream.readline()
        if not raw:
            break
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            tail.append(line)


def _assert_mcp_healthy(servers: list[dict[str, Any]]) -> list[str]:
    """Un server MCP caído deja al agente sin NINGUNA tool, en silencio.

    Pasó de verdad: al mover el cwd a un workspace vacío, el server dejó de
    encontrar el .env, murió al arrancar, y el agente respondió igual —
    escalando a un humano— sin una sola línea que dijera por qué.
    """
    caidos = [
        str(s.get("name"))
        for s in servers
        if str(s.get("status", "")).lower() not in {"connected", "ok", "ready"}
    ]
    if caidos:
        log.error(
            "mcp_server_failed",
            servers=caidos,
            detail=(
                "El agente está corriendo SIN TOOLS. Probá a mano: "
                "python -m whatsapp_skills.agent.mcp_server (con WA_SKILLS_PHONE seteado)."
            ),
        )
    return caidos


def _content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = (event.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _unwrap(content: Any, limit: int = 240) -> Any:
    """Saca el envoltorio del MCP para que el log sea legible.

    Un tool_result de MCP llega como [{"type":"text","text":"{\"result\": ...}"}],
    o sea el JSON de la tool serializado dos veces. Sin desanidarlo, el log se ve
    como una pared de barras invertidas.
    """
    if isinstance(content, list):
        content = " ".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict)
        )

    for _ in range(3):  # envoltorio MCP -> dict con "result" -> JSON de la tool
        if not isinstance(content, str):
            break
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            break
        content = parsed.get("result", parsed) if isinstance(parsed, dict) else parsed

    if isinstance(content, dict):
        return {k: _clip(v) for k, v in content.items()}
    return _clip(content, limit)


def _clip(value: Any, limit: int = 120) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _usage_from(payload: dict[str, Any]) -> Usage:
    raw = payload.get("usage") or {}
    return Usage(
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        cache_read_tokens=raw.get("cache_read_input_tokens"),
        cache_write_tokens=raw.get("cache_creation_input_tokens"),
        cost_usd=payload.get("total_cost_usd"),
    )

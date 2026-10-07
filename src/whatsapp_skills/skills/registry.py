"""El registry: descubre las skills y es el único camino de ejecución.

Todo lo que ejecuta una tool pasa por `SkillRegistry.dispatch`, sin importar si
la llamada vino de la Messages API o de `claude -p` vía MCP. Ese es el motivo de
que los dos backends se comporten igual: comparten timeout, circuit breaker,
rate limiter y logging.

Tres modos de exposición de tools, que es donde se juega el token overhead:

    full         → las 15 tools cargadas. El baseline.
    deferred     → tool_search + el resto con defer_loading. Claude descubre.
    progressive  → igual que deferred, pero las guías se leen a demanda.

`scripts/measure_tokens.py` mide los tres con count_tokens.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Literal

from ..observability.logging import get_logger
from ..resilience.circuit_breaker import BreakerState, CircuitBreaker, CircuitOpenError
from ..resilience.rate_limit import RateLimiter, RateLimitExceeded
from .base import BUILTIN_SKILL, SkillContext, SkillTool, registered_tools, skill_tool
from .loader import SkillDoc, load_skill_docs

log = get_logger(__name__)

ToolMode = Literal["full", "deferred", "progressive"]

# BM25 rankea mejor que regex sobre descripciones en lenguaje natural.
TOOL_SEARCH_TOOL: dict[str, Any] = {
    "type": "tool_search_tool_bm25_20251119",
    "name": "tool_search_tool_bm25",
}


def repo_root() -> Path:
    # src/whatsapp_skills/skills/registry.py -> sube 4 niveles
    return Path(__file__).resolve().parents[3]


def skills_dir() -> Path:
    return repo_root() / "skills"


# ── Tool built-in: progressive disclosure ───────────────────────────────────
# No vive en skills/ porque no es una skill de negocio: es la maquinaria que
# hace que las otras cinco sean baratas en contexto.

_SKILL_DOCS: dict[str, SkillDoc] = {}


@skill_tool(
    name="load_skill_guide",
    description=(
        "Leer la guía completa de una skill: precondiciones, orden de operaciones y "
        "manejo de errores. Usala ANTES de encadenar varias tools de una skill que no "
        "usaste todavía en esta conversación, o cuando una tool devuelva un error que "
        "no sepas resolver."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Nombre de la skill en kebab-case. Ej: client-management",
            }
        },
        "required": ["skill"],
        "additionalProperties": False,
    },
    timeout_s=1.0,
    skill=BUILTIN_SKILL,
)
async def load_skill_guide(ctx: SkillContext, skill: str) -> dict[str, Any]:
    doc = _SKILL_DOCS.get(skill)
    if doc is None:
        return {
            "found": False,
            "error": f"No existe la skill {skill!r}.",
            "available": sorted(_SKILL_DOCS),
        }
    return {"found": True, "skill": doc.name, "guide": doc.body}


class SkillRegistry:
    """Instanciado una vez por proceso, en el lifespan de FastAPI."""

    def __init__(
        self,
        *,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        directory: Path | None = None,
    ) -> None:
        self.directory = directory or skills_dir()
        self.docs: dict[str, SkillDoc] = load_skill_docs(self.directory)

        global _SKILL_DOCS
        _SKILL_DOCS = self.docs

        self._import_tool_modules()
        self.tools: dict[str, SkillTool] = registered_tools()
        self._validate_coverage()

        self.breaker = CircuitBreaker(
            threshold=breaker_threshold, cooldown_s=breaker_cooldown_s
        )
        self.limiter = RateLimiter()

    # ── Descubrimiento ──────────────────────────────────────────────────────

    def _import_tool_modules(self) -> None:
        """Importa cada skills/<nombre>/tools.py como módulo suelto.

        skills/ no es un paquete Python a propósito: tiene que poder copiarse
        tal cual a .claude/skills/ para Claude Code, y ahí un __init__.py sería
        ruido.
        """
        for tools_py in sorted(self.directory.glob("*/tools.py")):
            safe = tools_py.parent.name.replace("-", "_")
            module_name = f"whatsapp_skills._skills.{safe}"
            if module_name in sys.modules:
                continue
            spec = importlib.util.spec_from_file_location(module_name, tools_py)
            if spec is None or spec.loader is None:
                raise ImportError(f"No se pudo cargar {tools_py}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

    def _validate_coverage(self) -> None:
        """Cada skill declarada aporta al menos una tool, y viceversa."""
        by_skill: dict[str, list[str]] = {}
        for tool in self.tools.values():
            by_skill.setdefault(tool.skill, []).append(tool.name)

        for name in self.docs:
            if not by_skill.get(name):
                raise ValueError(
                    f"La skill {name!r} tiene SKILL.md pero ninguna tool registrada en "
                    f"{self.directory / name / 'tools.py'}. Una skill sin tools es "
                    "documentación, no una skill."
                )

        orphans = set(by_skill) - set(self.docs) - {BUILTIN_SKILL}
        if orphans:
            raise ValueError(
                f"Hay tools registradas en carpetas sin SKILL.md: {sorted(orphans)}. "
                "Cada carpeta en skills/ necesita su SKILL.md."
            )

    # ── Exposición ──────────────────────────────────────────────────────────

    def system_prompt_block(self) -> str:
        """Las descripciones de las skills. Costo fijo del system prompt.

        Orden alfabético estable: cualquier reordenamiento cambia el prefijo y
        tira el prompt cache.
        """
        lines = []
        for name in sorted(self.docs):
            doc = self.docs[name]
            tools = sorted(t.name for t in self.tools.values() if t.skill == name)
            lines.append(f"### {doc.name}\n{doc.description}\nTools: {', '.join(tools)}")
        return "\n\n".join(lines)

    def anthropic_tools(self, mode: ToolMode = "full") -> list[dict[str, Any]]:
        business = sorted(
            (t for t in self.tools.values() if t.name != "load_skill_guide"),
            key=lambda t: t.name,
        )
        guide = self.tools["load_skill_guide"]

        if mode == "full":
            return [t.to_anthropic() for t in business] + [guide.to_anthropic()]

        # deferred / progressive: la tool de búsqueda nunca se difiere, y al
        # menos una tool tiene que quedar cargada o la API devuelve 400
        # ("All tools have defer_loading set"). load_skill_guide es esa tool.
        return (
            [TOOL_SEARCH_TOOL, guide.to_anthropic()]
            + [t.to_anthropic(defer=True) for t in business]
        )

    def mcp_tools(self) -> list[dict[str, Any]]:
        return [t.to_mcp() for t in sorted(self.tools.values(), key=lambda t: t.name)]

    # ── Ejecución ───────────────────────────────────────────────────────────

    async def dispatch(
        self, name: str, tool_input: dict[str, Any], ctx: SkillContext
    ) -> tuple[Any, bool]:
        """Ejecuta una tool. Devuelve (resultado, is_error).

        Nunca levanta excepción hacia arriba: un fallo vuelve como resultado con
        is_error=True, porque la API exige un tool_result por cada tool_use.
        Descartar uno rompe la conversación.
        """
        tool = self.tools.get(name)
        if tool is None:
            return (
                {"error": f"Tool desconocida: {name!r}.", "available": sorted(self.tools)},
                True,
            )

        log.info("tool_call", tool=name, skill=tool.skill, input=tool_input)
        started = time.monotonic()

        def _elapsed_ms() -> float:
            return (time.monotonic() - started) * 1000

        def _fail(payload: dict[str, Any]) -> tuple[Any, bool]:
            log.warning(
                "tool_result",
                tool=name,
                result=payload,
                latency_ms=_elapsed_ms(),
                breaker=self.breaker.state_of(name).value,
                error_type=payload.get("error_type"),
            )
            return payload, True

        # 1. Rate limit: el chequeo más barato va primero.
        if tool.rate_limit:
            try:
                await self.limiter.acquire(name, tool.rate_limit)
            except RateLimitExceeded as exc:
                return _fail(
                    {
                        "error_type": "rate_limited",
                        "error": str(exc),
                        "retry_in_s": round(exc.retry_in_s, 1),
                        "hint": "Esperá, usá otra skill, o respondé con lo que ya tenés.",
                    }
                )

        # 2. Circuit breaker: falla rápido si el servicio viene caído.
        try:
            await self.breaker.before_call(name)
        except CircuitOpenError as exc:
            return _fail(
                {
                    "error_type": "circuit_open",
                    "error": str(exc),
                    "retry_in_s": round(exc.retry_in_s, 1),
                    "hint": (
                        "Esta tool viene fallando de forma consistente. No reintentes: "
                        "usá escalate_to_human si el pedido no se puede resolver sin ella."
                    ),
                }
            )

        # 3. La llamada real, con timeout.
        try:
            result = await asyncio.wait_for(
                tool.handler(ctx, **tool_input), timeout=tool.timeout_s
            )
        except TimeoutError:
            await self.breaker.record_failure(name)
            return _fail(
                {
                    "error_type": "timeout",
                    "error": f"{name!r} superó su timeout de {tool.timeout_s}s.",
                    "breaker": self.breaker.state_of(name).value,
                }
            )
        except TypeError as exc:
            # Argumentos que no matchean la firma: bug de schema, no del
            # servicio. No cuenta como fallo para el breaker.
            return _fail(
                {"error_type": "bad_arguments", "error": f"Argumentos inválidos: {exc}"}
            )
        except Exception as exc:  # noqa: BLE001 - el borde tiene que atrapar todo
            await self.breaker.record_failure(name)
            return _fail(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "breaker": self.breaker.state_of(name).value,
                }
            )

        await self.breaker.record_success(name)
        log.info(
            "tool_result",
            tool=name,
            result=result,
            latency_ms=_elapsed_ms(),
            breaker=BreakerState.CLOSED.value,
        )
        return result, False

    async def dispatch_json(
        self, name: str, tool_input: dict[str, Any], ctx: SkillContext
    ) -> tuple[str, bool]:
        """Igual que dispatch pero serializado: es lo que consume el server MCP."""
        result, is_error = await self.dispatch(name, tool_input, ctx)
        return json.dumps(result, ensure_ascii=False, default=str), is_error

    def health(self) -> dict[str, Any]:
        return {
            "skills": sorted(self.docs),
            "tools": len(self.tools),
            "breakers": self.breaker.snapshot(),
            "rate_limit_tokens": self.limiter.snapshot(),
        }

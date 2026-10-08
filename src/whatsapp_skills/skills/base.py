"""El contrato de una tool de skill.

Una Skill es una carpeta con:

    SKILL.md   ← frontmatter (name, description) + la guía en el cuerpo
    tools.py   ← las funciones, decoradas con @skill_tool

El decorador no ejecuta nada: sólo registra metadata. Quien ejecuta es
`registry.dispatch`, que envuelve cada llamada en timeout + circuit breaker +
rate limiter + logging. Un único camino de ejecución para los dos backends —
por eso el backend de Messages API y el de `claude -p` se comportan igual.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..resilience.rate_limit import parse_rate

# Los handlers reciben (ctx, **input) y devuelven algo serializable a JSON.
SkillHandler = Callable[..., Awaitable[Any]]

# Tools de infraestructura (no de negocio). No se les exige un SKILL.md.
BUILTIN_SKILL = "__builtin__"

# Registro global, poblado al importar cada skills/*/tools.py.
_REGISTERED: dict[str, SkillTool] = {}


@dataclass(frozen=True)
class SkillTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: SkillHandler
    skill: str = "unknown"
    strict: bool = True
    timeout_s: float = 5.0
    rate_limit: str | None = None
    defer_loading: bool = False

    def to_anthropic(self, *, defer: bool | None = None) -> dict[str, Any]:
        """Definición para el parámetro `tools` de la Messages API."""
        tool: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        # strict:true exige additionalProperties:false + required en el schema.
        if self.strict:
            tool["strict"] = True
        if defer if defer is not None else self.defer_loading:
            tool["defer_loading"] = True
        return tool

    def to_mcp(self) -> dict[str, Any]:
        """Definición en formato MCP, para el backend `claude -p`."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _infer_skill_name(fn: SkillHandler) -> str:
    """El nombre de la skill sale de la carpeta que contiene el tools.py."""
    module = inspect.getmodule(fn)
    if module is not None and getattr(module, "__file__", None):
        return Path(module.__file__).parent.name
    return "unknown"


def _validate_schema(name: str, schema: dict[str, Any], strict: bool) -> None:
    if schema.get("type") != "object":
        raise ValueError(f"{name}: input_schema.type debe ser 'object'.")
    if strict:
        # La API rechaza strict:true sin estas dos claves.
        if schema.get("additionalProperties") is not False:
            raise ValueError(
                f"{name}: strict=True exige 'additionalProperties': False en el schema."
            )
        if "required" not in schema:
            raise ValueError(f"{name}: strict=True exige la clave 'required' en el schema.")


def skill_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    strict: bool = True,
    timeout_s: float = 5.0,
    rate_limit: str | None = None,
    defer_loading: bool = False,
    skill: str | None = None,
) -> Callable[[SkillHandler], SkillHandler]:
    """Registra una función async como tool de la skill que la contiene.

    El nombre de la skill se infiere del nombre de la carpeta que contiene el
    módulo, así que no hay que repetirlo en cada tool.
    """

    def decorator(fn: SkillHandler) -> SkillHandler:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"{name}: los handlers tienen que ser async. Todo el pipeline es "
                "asyncio y una función sync bloquea el event loop entero."
            )
        if name in _REGISTERED:
            raise ValueError(
                f"Ya hay una tool registrada con el nombre '{name}' "
                f"(en la skill '{_REGISTERED[name].skill}'). Los nombres son globales."
            )
        _validate_schema(name, input_schema, strict)
        if rate_limit is not None:
            parse_rate(rate_limit)  # falla al importar, no en producción

        skill_name = skill or _infer_skill_name(fn)

        _REGISTERED[name] = SkillTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=fn,
            skill=skill_name,
            strict=strict,
            timeout_s=timeout_s,
            rate_limit=rate_limit,
            defer_loading=defer_loading,
        )
        return fn

    return decorator


def registered_tools() -> dict[str, SkillTool]:
    return dict(_REGISTERED)


def clear_registry() -> None:
    """Sólo para tests."""
    _REGISTERED.clear()


@dataclass
class SkillContext:
    """Todo lo que un handler necesita para hacer su trabajo.

    Se arma una vez por mensaje entrante y se pasa a cada tool. Es lo que en el
    video se llama "el estado vive adentro de la Skill": las tools no se hablan
    entre ellas, comparten este contexto.
    """

    phone: str
    settings: Any
    db: Any = None
    notifier: Any = None
    client_id: str | None = None
    conversation: list[dict[str, Any]] = field(default_factory=list)
    scratch: dict[str, Any] = field(default_factory=dict)

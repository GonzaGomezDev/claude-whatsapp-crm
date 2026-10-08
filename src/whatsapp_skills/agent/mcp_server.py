"""Server MCP stdio que expone el registry a `claude -p`.

Lo levanta el backend cli como subproceso. Las tools que ve Claude Code acá son
exactamente las mismas que ve la Messages API, y se ejecutan por el mismo
`registry.dispatch` — mismo timeout, mismo circuit breaker, mismo rate limiter,
mismos logs.

El registry guarda los schemas como JSON Schema. El SDK de MCP construye los
suyos a partir de firmas de Python. En vez de duplicar las definiciones (que se
desincronizarían al primer cambio), sintetizamos la firma de Python desde el
JSON Schema. El registry sigue siendo la única fuente de verdad.

Se ejecuta así:
    python -m whatsapp_skills.agent.mcp_server

Y lee de variables de entorno con quién está hablando:
    WA_SKILLS_PHONE      teléfono del cliente (obligatorio)
    WA_SKILLS_CLIENT_ID  UUID si ya se conoce (opcional)
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Annotated, Any

from pydantic import Field

from ..config import get_settings
from ..integrations.notifications import build_notifier
from ..integrations.supabase_client import Database
from ..integrations.twilio_client import WhatsAppClient
from ..observability.logging import configure_logging, get_logger
from ..skills.base import SkillContext, SkillTool
from ..skills.registry import SkillRegistry

log = get_logger(__name__)

SERVER_NAME = "skills"

# JSON Schema -> tipo de Python. Sólo los tipos que usan las skills; cualquier
# otro explota fuerte al arrancar, que es donde querés enterarte.
_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _annotation_for(spec: dict[str, Any]) -> Any:
    raw = spec.get("type", "string")

    if isinstance(raw, list):
        non_null = [t for t in raw if t != "null"]
        base = _TYPE_MAP[non_null[0]] if non_null else str
        return base | None if "null" in raw else base

    if raw not in _TYPE_MAP:
        raise ValueError(f"Tipo JSON Schema no soportado en el server MCP: {raw!r}")
    return _TYPE_MAP[raw]


def _build_signature(schema: dict[str, Any]) -> tuple[inspect.Signature, dict[str, Any]]:
    """Firma de Python + anotaciones a partir del input_schema de la tool."""
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = list(schema.get("required", []))

    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    # Los obligatorios van primero: Python no acepta un parámetro sin default
    # después de uno con default.
    ordered = [n for n in properties if n in required] + [
        n for n in properties if n not in required
    ]

    for prop_name in ordered:
        spec = properties[prop_name]
        # enum, minimum y compañía no tienen equivalente en una anotación de
        # Python. Van como json_schema_extra para que el schema que ve Claude
        # Code sea equivalente al que ve la Messages API — si no, los dos
        # backends validarían distinto y la comparación dejaría de servir.
        extra = {
            key: spec[key]
            for key in ("enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
            if key in spec
        }
        annotation = Annotated[
            _annotation_for(spec),
            Field(
                description=spec.get("description") or prop_name,
                json_schema_extra=extra or None,
            ),
        ]
        annotations[prop_name] = annotation
        params.append(
            inspect.Parameter(
                prop_name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=inspect.Parameter.empty if prop_name in required else None,
            )
        )

    annotations["return"] = str
    return inspect.Signature(params, return_annotation=str), annotations


def _make_handler(tool: SkillTool, registry: SkillRegistry, ctx: SkillContext) -> Any:
    """Envuelve una SkillTool en una función que el SDK de MCP sepa introspeccionar."""

    required = set(tool.input_schema.get("required", []))

    async def handler(**kwargs: Any) -> str:
        # Los opcionales que no vinieron llegan como None por el default de la
        # firma; los sacamos para que el handler use sus propios defaults. Un
        # obligatorio nullable (`company: null`) sí se pasa: es un valor.
        payload = {k: v for k, v in kwargs.items() if v is not None or k in required}
        text, _is_error = await registry.dispatch_json(tool.name, payload, ctx)
        return text

    signature, annotations = _build_signature(tool.input_schema)
    handler.__signature__ = signature  # type: ignore[attr-defined]
    handler.__annotations__ = annotations
    handler.__name__ = tool.name
    handler.__doc__ = tool.description
    return handler


def build_server(registry: SkillRegistry, ctx: SkillContext) -> Any:
    from mcp.server import MCPServer

    server = MCPServer(
        name=SERVER_NAME,
        instructions=(
            "Tools de las skills del agente de WhatsApp. Los schemas y la ejecución "
            "vienen del mismo registry que usa el backend de la Messages API."
        ),
    )

    for tool in sorted(registry.tools.values(), key=lambda t: t.name):
        server.add_tool(
            _make_handler(tool, registry, ctx),
            name=tool.name,
            description=tool.description,
        )

    return server


def main() -> None:
    settings = get_settings()
    # El log va a stderr: stdout es el transporte JSON-RPC del MCP y cualquier
    # línea suelta ahí rompe la sesión entera.
    configure_logging(settings.log_level, "json", stream=sys.stderr)

    phone = os.environ.get("WA_SKILLS_PHONE")
    if not phone:
        raise SystemExit(
            "Falta WA_SKILLS_PHONE. El server MCP necesita saber con qué cliente "
            "está hablando; lo setea el backend cli al lanzarlo."
        )

    registry = SkillRegistry(
        breaker_threshold=settings.circuit_breaker_threshold,
        breaker_cooldown_s=settings.circuit_breaker_cooldown_s,
    )
    ctx = SkillContext(
        phone=phone,
        settings=settings,
        db=Database(settings.supabase_url, settings.supabase_secret_key),
        notifier=build_notifier(
            settings,
            WhatsAppClient(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.twilio_whatsapp_from,
            ),
        ),
        client_id=os.environ.get("WA_SKILLS_CLIENT_ID") or None,
    )

    build_server(registry, ctx).run(transport="stdio")


if __name__ == "__main__":
    main()

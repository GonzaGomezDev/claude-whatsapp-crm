"""Capa 6: logging estructurado.

Dos renderers sobre el mismo evento:

  demo → el formato que se ve en el video, legible en cámara
         [5:23:15 PM] Claude calling: find_client("+54-911-234-5678")
         [5:23:16 PM] Result: { found: false }  (340ms · breaker=closed)

  json → una línea JSON por evento, para mandar a un agregador

Cada llamada a una tool loguea latencia, estado del breaker, tipo de error y
tokens. Ese es el punto 3 de "lo que cambiaría" del video, resuelto de entrada:
si no medís por skill, no sabés cuál es tu cuello de botella.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any

import structlog

# Eventos que el renderer "demo" sabe dibujar lindo. El resto cae al formato
# genérico, así agregar un log nuevo nunca rompe la salida.
_DEMO_EVENTS = {"tool_call", "tool_result", "agent_start", "agent_reply", "inbound", "outbound"}


def _fmt_value(value: Any) -> str:
    """Serializa como JS-ish, que es como se ve en el video: { found: false }."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt_value(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{k}: {_fmt_value(v)}" for k, v in value.items())
        return "{ " + inner + " }" if inner else "{}"
    return _fmt_value(str(value))


def _truncate(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def demo_renderer(_logger: Any, _name: str, event_dict: dict[str, Any]) -> str:
    event = event_dict.pop("event", "")
    ts = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
    head = f"[{ts}] "

    if event not in _DEMO_EVENTS:
        extras = " ".join(f"{k}={_fmt_value(v)}" for k, v in event_dict.items() if k != "level")
        return f"{head}{event}{(' ' + extras) if extras else ''}"

    if event == "inbound":
        return (
            f"{head}Message from {event_dict.get('phone')}: "
            f"{_fmt_value(_truncate(str(event_dict.get('body', ''))))}"
        )

    if event == "agent_start":
        backend = event_dict.get("backend")
        n = event_dict.get("skills", 0)
        return f"{head}Running Claude ({backend}) with {n} Skills"

    if event == "tool_call":
        args = event_dict.get("input") or {}
        rendered = ", ".join(_fmt_value(v) for v in args.values()) if isinstance(args, dict) else ""
        return f"{head}Claude calling: {event_dict.get('tool')}({_truncate(rendered, 120)})"

    if event == "tool_result":
        meta = [f"{int(event_dict.get('latency_ms', 0))}ms"]
        if (breaker := event_dict.get("breaker")) is not None:
            meta.append(f"breaker={breaker}")
        if (err := event_dict.get("error_type")) is not None:
            meta.append(f"error={err}")
        result = event_dict.get("result")
        body = _truncate(_fmt_value(result), 200)
        return f"{head}Result: {body}  ({' · '.join(meta)})"

    if event == "agent_reply":
        parts = []
        if (u := event_dict.get("input_tokens")) is not None:
            parts.append(f"in={u}")
        if (u := event_dict.get("output_tokens")) is not None:
            parts.append(f"out={u}")
        if (u := event_dict.get("cache_read_tokens")) is not None:
            parts.append(f"cache_read={u}")
        if (u := event_dict.get("cost_usd")) is not None:
            parts.append(f"cost=${u:.4f}")
        suffix = f"  ({' · '.join(parts)})" if parts else ""
        return f"{head}Claude response: {_fmt_value(event_dict.get('text', ''))}{suffix}"

    # outbound
    return f"{head}Sending to WhatsApp… sid={event_dict.get('sid')}"


def force_utf8_output() -> None:
    """Windows usa cp1252 por defecto y revienta con acentos.

    No es cosmético: un UnicodeEncodeError tira abajo el proceso a mitad de un
    print. Todo este repo escribe en español, así que sin esto no arranca en la
    mitad de las máquinas donde se va a clonar.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # stream ya cerrado o redirigido raro
            pass


def configure_logging(
    level: str = "INFO", fmt: str = "demo", stream: Any = None
) -> None:
    """stream=sys.stderr es obligatorio en el server MCP: stdout es el
    transporte JSON-RPC y cualquier línea suelta ahí rompe la sesión."""
    force_utf8_output()
    logging.basicConfig(
        format="%(message)s", stream=stream or sys.stdout, level=level.upper(), force=True
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
    ]
    if fmt == "json":
        processors += [
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors.append(demo_renderer)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "whatsapp_skills") -> Any:
    return structlog.get_logger(name)

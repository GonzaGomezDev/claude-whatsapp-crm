"""Capa 2: routing barato, sin llamar a Claude.

No todo mensaje merece una llamada al modelo. Un "gracias!" no necesita cinco
skills ni ocho segundos de latencia, y un audio no lo podemos procesar de todas
formas. Esta capa resuelve en microsegundos lo que se pueda, y deja pasar el
resto.

Es la optimización de costo más aburrida y más efectiva del sistema: cada
mensaje que no llega a la Capa 4 es un request entero que no se paga.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Route(StrEnum):
    AGENT = "agent"          # va al modelo
    DIRECT_REPLY = "direct"  # respuesta fija, sin modelo
    IGNORE = "ignore"        # ni se responde


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    reply: str | None = None
    reason: str = ""


# Palabras sueltas de cortesía. Si el mensaje es sólo esto, no hay nada que
# razonar. El \b y el ancla evitan matchear "gracias por nada, quiero hablar
# con alguien".
_COURTESY = re.compile(
    r"^(gracias|muchas gracias|mil gracias|ok|oka?y|dale|listo|perfecto|joya|"
    r"barbaro|bárbaro|genial|buenisimo|buenísimo|👍|🙏|❤️|👌)[\s!.,]*$",
    re.IGNORECASE,
)

_OPT_OUT = re.compile(r"^(stop|baja|unsubscribe|cancelar suscripcion)[\s!.,]*$", re.IGNORECASE)

COURTESY_REPLY = "De nada. Cualquier cosa escribime."
OPT_OUT_REPLY = "Listo, no te escribimos más por acá."
MEDIA_REPLY = (
    "Por ahora sólo puedo leer mensajes de texto. ¿Me contás por escrito qué necesitás?"
)


def route_message(body: str, num_media: int = 0) -> RouteDecision:
    text = (body or "").strip()

    if num_media > 0 and not text:
        return RouteDecision(Route.DIRECT_REPLY, MEDIA_REPLY, "media_sin_texto")

    if not text:
        return RouteDecision(Route.IGNORE, reason="mensaje_vacio")

    if _OPT_OUT.match(text):
        return RouteDecision(Route.DIRECT_REPLY, OPT_OUT_REPLY, "opt_out")

    if _COURTESY.match(text):
        return RouteDecision(Route.DIRECT_REPLY, COURTESY_REPLY, "cortesia")

    return RouteDecision(Route.AGENT, reason="requiere_agente")

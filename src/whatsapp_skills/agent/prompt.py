"""El system prompt, compartido por los dos backends.

Está partido en dos a propósito:

    STATIC   → idéntico byte a byte en todos los requests. Es el prefijo que se
               cachea. Acá van la persona, las reglas y las descripciones de las
               skills.
    DYNAMIC  → cambia por conversación (nombre del cliente, tickets abiertos).
               Va DESPUÉS del breakpoint de cache, o invalidaría todo.

Si mezclás las dos mitades, el cache hit rate se va a cero y no te enterás:
la API no avisa, simplemente cobra input completo cada vez.
"""

from __future__ import annotations

import json
from typing import Any

from .backend import Conversation

PERSONA = """\
Sos el asistente de atención al cliente de la empresa, respondiendo por WhatsApp.

Cómo escribís:
- Español rioplatense, voseo. Cercano pero profesional.
- Mensajes cortos. WhatsApp no es email: dos o tres oraciones por respuesta.
- Sin markdown, sin viñetas, sin negritas. Texto plano.
- Un emoji como mucho, y sólo si el tono lo pide.

Reglas que no se negocian:
- No inventes precios, plazos ni condiciones comerciales. Salen de la knowledge
  base o no salen.
- No prometas nada que no hayas registrado en un ticket.
- No le pidas al cliente datos de tarjeta ni contraseñas. Nunca.
- No expongas IDs internos (UUIDs) ni nombres de tools. El cliente ve números de
  ticket, no `client_id`.
- Si una tool falla y no podés resolver el pedido sin ella, escalá a un humano
  en vez de improvisar.
- Todo lo que escribís le llega al cliente, tal cual. No hay un canal interno:
  nada de notas para el equipo ni explicaciones de errores técnicos. Los fallos
  de las tools ya quedan en el log.

Cómo trabajás:
- Tenés cuatro skills. Cada una agrupa las tools de un dominio y trae su propia
  guía de uso.
- Antes de encadenar varias tools de una skill que no usaste todavía en esta
  conversación, leé su guía con `load_skill_guide`. Es barato y te ahorra
  errores de orden.
- Llamá en paralelo a todas las tools que no dependan una de otra. Buscar en la
  knowledge base no necesita esperar a que se cree el cliente.
- Cuando ya tenés lo necesario para responder, respondé. No sigas llamando tools
  para confirmar cosas que ya sabés.

Sobre los tickets abiertos:
- Un ticket abierto NO es una respuesta. Es un recordatorio de que el equipo está
  en algo, y sirve para que no dupliques trabajo ni contradigas lo que ya
  prometieron. No es motivo para dejar de contestar.
- Si el cliente vuelve a preguntar algo que tiene ticket abierto, **buscá igual**.
  Si esta vez encontrás la respuesta, dásela. Recién si seguís sin poder
  responder, referí al ticket.
- Cuando resolvés algo que estaba en un ticket, dejalo asentado con
  update_ticket_status en vez de dejarlo abierto para siempre.
- Nunca respondas sólo "ya está cargado en el ticket N". Para el cliente eso es
  lo mismo que no haber preguntado.
"""


def static_system_prompt(skills_block: str) -> str:
    """Prefijo estable. Cualquier cambio acá invalida el prompt cache."""
    return f"{PERSONA}\n## Skills disponibles\n\n{skills_block}\n"


def dynamic_context(convo: Conversation) -> str:
    """Contexto de esta conversación. Va después del breakpoint de cache."""
    lines = [f"Teléfono del cliente: {convo.phone}"]

    if convo.client:
        lines.append(
            "Cliente conocido: "
            + json.dumps(
                {
                    "client_id": convo.client.get("id"),
                    "name": convo.client.get("name"),
                    "company": convo.client.get("company"),
                },
                ensure_ascii=False,
            )
        )
        lines.append(
            "Ya está identificado: no hace falta que llames a find_client de nuevo."
        )
    else:
        lines.append(
            "Cliente desconocido: no hay registro para este número. Si el mensaje "
            "amerita crear uno, usá la skill client-management."
        )

    if convo.open_tickets:
        summary = [
            {"ref": t.get("ref"), "type": t.get("type"), "status": t.get("status")}
            for t in convo.open_tickets
        ]
        lines.append(f"Tickets abiertos: {json.dumps(summary, ensure_ascii=False)}")

    if convo.handoff_note:
        lines.append(
            "Una persona del equipo atendió este chat y te lo devolvió con esta nota. "
            "Respetá lo que se acordó y no lo contradigas: "
            + json.dumps(convo.handoff_note, ensure_ascii=False)
        )

    return "## Contexto de esta conversación\n\n" + "\n".join(lines)


def system_blocks(skills_block: str, convo: Conversation) -> list[dict[str, Any]]:
    """System prompt en bloques, con el breakpoint de cache en el lugar correcto.

    Orden de render de la API: tools -> system -> messages. El `cache_control`
    va al final del bloque estático, así el prefijo cacheado es
    [tools + persona + skills] y el contexto variable queda afuera.

    Ojo: el prefijo mínimo cacheable ronda los 1024 tokens. Con cinco
    descripciones cortas puede quedar por debajo y no cachear nada, en silencio.
    Verificalo con `usage.cache_read_input_tokens` antes de dar por hecho el
    ahorro.
    """
    return [
        {
            "type": "text",
            "text": static_system_prompt(skills_block),
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic_context(convo)},
    ]


def cli_system_prompt(skills_block: str, convo: Conversation) -> str:
    """Versión plana, para `claude -p --append-system-prompt`.

    El backend cli no controla el prompt caching —lo maneja Claude Code— así que
    acá las dos mitades van juntas.
    """
    return f"{static_system_prompt(skills_block)}\n{dynamic_context(convo)}"

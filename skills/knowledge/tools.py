"""Skill 3: Knowledge.

Full-text search de Postgres, sin embeddings. Los números que devuelve salen del
motor de búsqueda, no del modelo: `confidence` es ts_rank normalizado y
`matched_terms` es cuántos términos de la consulta aparecen en el documento.

La RPC hace dos pasadas: primero exige todos los términos (AND) y, si eso no
devuelve nada, reintenta con cualquiera (OR) ordenando por cuántos matchearon.
Sin ese fallback, "lista de precios actuales" devolvía cero documentos porque
ninguno contiene la palabra "actual".
"""

from __future__ import annotations

from typing import Any

from whatsapp_skills.skills.base import SkillContext, skill_tool


@skill_tool(
    name="knowledge_search",
    description=(
        "Buscar en la base de conocimiento interna (precios, políticas, plazos, docs "
        "de producto). Devuelve los documentos con su contenido y cuántos términos de "
        "la consulta matchearon."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Palabras clave en español. Es búsqueda léxica con stemming, no "
                    "semántica: usá los términos que esperás encontrar escritos en el "
                    "documento, no una pregunta completa."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Cuántos documentos traer. Entre 1 y 10.",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query", "limit"],
        "additionalProperties": False,
    },
    timeout_s=2.5,
    rate_limit="50/minute",
)
async def knowledge_search(ctx: SkillContext, query: str, limit: int) -> dict[str, Any]:
    rows = await ctx.db.search_knowledge(query, limit)

    # La RPC vieja devolvía `excerpt` (un fragmento de ts_headline) en vez de
    # `content`. Sin este chequeo el fallo es un KeyError que no le dice a nadie
    # qué hacer, y el agente termina escalando a un humano por un schema viejo.
    if rows and "content" not in rows[0]:
        raise RuntimeError(
            "La función search_knowledge de tu base está desactualizada: devuelve "
            f"{sorted(rows[0])} y falta 'content'. Volvé a correr supabase/schema.sql "
            "entero en el SQL Editor."
        )

    docs = [
        {
            "title": r["title"],
            "source": r.get("source"),
            "content": r["content"],
            "matched_terms": r.get("matched_terms"),
            "query_terms": r.get("query_terms"),
            "confidence": round(float(r.get("confidence") or 0.0), 3),
            # Si es True el documento sigue más allá de lo que estás viendo. No
            # afirmes que tenés la información completa.
            "truncated": r.get("truncated", False),
        }
        for r in rows
    ]

    mode = rows[0].get("match_mode") if rows else None
    return {
        "query": query,
        "count": len(docs),
        "match_mode": mode,
        "docs": docs,
        "guidance": _guidance(docs, mode),
    }


def _guidance(docs: list[dict[str, Any]], mode: str | None) -> str:
    """Le dice al modelo qué hacer con lo que recibió.

    Un resultado que se explica solo ahorra una vuelta entera del loop agéntico.
    """
    if not docs:
        return (
            "Sin resultados: ningún término de tu consulta aparece en la base. "
            "Reformulá con sinónimos (precio/cotización/tarifa, envío/entrega/plazo) "
            "una vez más. Si sigue vacío, creá un ticket de tipo quotation en vez de "
            "inventar un dato."
        )

    top = docs[0]
    partes: list[str] = []

    if mode == "any_term":
        partes.append(
            f"La búsqueda exacta no encontró nada, así que se reintentó con términos "
            f"sueltos. El mejor documento matcheó {top['matched_terms']} de "
            f"{top['query_terms']} términos: leelo antes de citarlo, puede no ser "
            f"sobre lo que preguntaste."
        )
    else:
        partes.append(
            f"Todos los términos de la consulta aparecen en {top['title']!r}. "
            f"Respondé con esto y citá el documento."
        )

    if any(d["truncated"] for d in docs):
        partes.append(
            "Ojo: hay documentos truncados. No digas que tenés la información "
            "completa — si te falta el detalle, decilo o creá un ticket."
        )

    return " ".join(partes)

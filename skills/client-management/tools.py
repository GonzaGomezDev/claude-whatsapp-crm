"""Skill 1: ClientManagement.

Las tools son finitas y aburridas a propósito. Toda la prosa sobre cuándo usar
cada una vive en SKILL.md, que se carga a demanda — no en las descripciones, que
se pagan en cada request.
"""

from __future__ import annotations

from typing import Any

from whatsapp_skills.skills.base import SkillContext, skill_tool


@skill_tool(
    name="find_client",
    description="Buscar un cliente por número de teléfono (exacto) o por nombre (parcial).",
    input_schema={
        "type": "object",
        "properties": {
            "phone": {
                "type": "string",
                "description": (
                    "Teléfono en formato E.164, ej: +5491123456789. Es la búsqueda "
                    "preferida: el teléfono es único."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Nombre parcial. Devuelve varias coincidencias posibles; usalo "
                    "sólo si no tenés el teléfono."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    timeout_s=2.0,
    rate_limit="5/minute",
)
async def find_client(
    ctx: SkillContext, phone: str | None = None, name: str | None = None
) -> dict[str, Any]:
    if not phone and not name:
        # Sin argumentos, el teléfono del remitente es la intención obvia.
        phone = ctx.phone

    if phone:
        row = await ctx.db.find_client_by_phone(phone)
        if row is None:
            return {"found": False, "searched_by": "phone", "phone": phone}
        ctx.client_id = row["id"]
        return {
            "found": True,
            "client_id": row["id"],
            "name": row.get("name"),
            "company": row.get("company"),
            "last_interaction": row.get("updated_at"),
        }

    matches = await ctx.db.find_clients_by_name(name or "")
    return {
        "found": bool(matches),
        "searched_by": "name",
        "match_count": len(matches),
        "matches": [
            {
                "client_id": m["id"],
                "name": m.get("name"),
                "company": m.get("company"),
                # Parcial: no filtramos teléfonos completos a partir de una
                # búsqueda por nombre, que puede venir de otra persona.
                "phone_hint": (m.get("phone") or "")[-4:],
            }
            for m in matches
        ],
        "note": "Confirmá con el cliente cuál es antes de escribir sobre ese registro.",
    }


@skill_tool(
    name="create_client",
    description=(
        "Crear un cliente nuevo. Hace upsert sobre el teléfono: es seguro llamarla "
        "aunque no estés seguro de si el cliente ya existía."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "phone": {"type": "string", "description": "Teléfono en E.164."},
            "name": {
                "type": ["string", "null"],
                "description": "Nombre, si el cliente lo dijo. null si todavía no lo sabés.",
            },
            "company": {
                "type": ["string", "null"],
                "description": "Empresa, sólo si el cliente la mencionó explícitamente.",
            },
        },
        "required": ["phone", "name", "company"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="10/minute",
)
async def create_client(
    ctx: SkillContext, phone: str, name: str | None, company: str | None
) -> dict[str, Any]:
    row = await ctx.db.create_client_row(phone=phone, name=name, company=company)
    ctx.client_id = row["id"]
    return {
        "client_id": row["id"],
        "created": True,
        "name": row.get("name"),
        "company": row.get("company"),
    }


@skill_tool(
    name="update_client",
    description=(
        "Actualizar datos de un cliente existente. Usala sólo con datos que el cliente "
        "dijo explícitamente en la conversación."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "UUID devuelto por find/create."},
            "name": {
                "type": ["string", "null"],
                "description": "Nombre corregido, o null para no tocarlo.",
            },
            "company": {
                "type": ["string", "null"],
                "description": "Empresa que el cliente mencionó, o null para no tocarla.",
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Dato suelto para guardar en metadata. Ej: CUIT, dirección.",
            },
        },
        "required": ["client_id", "name", "company", "notes"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="10/minute",
)
async def update_client(
    ctx: SkillContext,
    client_id: str,
    name: str | None,
    company: str | None,
    notes: str | None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if name:
        patch["name"] = name
    if company:
        patch["company"] = company
    if notes:
        current = await ctx.db.find_client_by_phone(ctx.phone)
        metadata = dict((current or {}).get("metadata") or {})
        metadata.setdefault("notes", [])
        metadata["notes"].append(notes)
        patch["metadata"] = metadata

    if not patch:
        return {"updated": False, "reason": "No mandaste ningún campo con valor."}

    row = await ctx.db.update_client_row(client_id, patch)
    return {
        "updated": True,
        "client_id": row["id"],
        "fields": sorted(patch),
    }

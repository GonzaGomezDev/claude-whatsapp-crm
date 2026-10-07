"""Bandeja del operador: la vuelta del human-in-the-loop.

El agente crea tickets y escala a un humano. Sin esto, ese humano no tiene forma
de contestarle al cliente ni de cerrar el ticket, y la cola crece para siempre.

    python scripts/inbox.py list
    python scripts/inbox.py show 4001
    python scripts/inbox.py reply 4001 "Te paso la cotización: USD 9.60 la unidad."
    python scripts/inbox.py close 4001 --note "Cotización enviada por mail"

Todo lo que mandás por acá queda registrado como mensaje `outbound` en la misma
tabla que usa el agente. Eso importa: la Capa 3 le pasa los últimos 10 mensajes
al modelo, así que en el próximo mensaje del cliente el agente ya sabe qué
contestó el equipo y no lo contradice.

## La ventana de 24 horas

WhatsApp sólo deja mandar mensajes libres dentro de las 24 h desde el último
mensaje del cliente. Pasado ese plazo hace falta una plantilla aprobada, y
Twilio devuelve el error 63016. Este script chequea la ventana ANTES de intentar
y te avisa, en vez de que te enteres por un stack trace.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatsapp_skills.config import get_settings  # noqa: E402
from whatsapp_skills.integrations.supabase_client import Database  # noqa: E402
from whatsapp_skills.integrations.twilio_client import WhatsAppClient  # noqa: E402
from whatsapp_skills.observability.logging import force_utf8_output  # noqa: E402

WINDOW = timedelta(hours=24)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def window_remaining(last_inbound: str | None, now: datetime | None = None) -> timedelta | None:
    """Cuánto queda de la ventana de 24 h. None si ya se cerró o nunca escribió."""
    started = _parse_ts(last_inbound)
    if started is None:
        return None
    left = (started + WINDOW) - (now or datetime.now(UTC))
    return left if left > timedelta(0) else None


def _fmt_window(left: timedelta | None) -> str:
    if left is None:
        return "CERRADA — hace falta plantilla aprobada"
    horas, resto = divmod(int(left.total_seconds()), 3600)
    return f"abierta, quedan {horas}h {resto // 60}m"


def _who(row: dict[str, Any]) -> str:
    cliente = row.get("clients") or {}
    nombre = cliente.get("name") or "(sin nombre)"
    empresa = f" · {cliente['company']}" if cliente.get("company") else ""
    return f"{nombre}{empresa} · {cliente.get('phone', '?')}"


def _build() -> tuple[Any, Database, WhatsAppClient]:
    settings = get_settings()
    db = Database(settings.supabase_url, settings.supabase_service_role_key)
    wa = WhatsAppClient(
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_whatsapp_from,
    )
    return settings, db, wa


# ── Comandos ────────────────────────────────────────────────────────────────


async def cmd_list(_args: argparse.Namespace) -> int:
    _, db, _wa = _build()
    tickets, escalados = await asyncio.gather(
        db.list_open_tickets(), db.list_pending_escalations()
    )

    if not tickets:
        print("No hay tickets abiertos.")
    else:
        print(f"\nTICKETS ABIERTOS ({len(tickets)})\n")
        print(f"{'ref':>6}  {'tipo':<10} {'estado':<15} {'prio':<7} asunto")
        print("─" * 92)
        for t in tickets:
            asunto = (t.get("subject") or "")[:38]
            print(
                f"{t['ref']:>6}  {t['type']:<10} {t['status']:<15} "
                f"{t['priority']:<7} {asunto}"
            )
            print(f"{'':>6}  {_who(t)}")

    if escalados:
        print(f"\nESCALADOS PENDIENTES ({len(escalados)})\n")
        for e in escalados:
            cliente = (e.get("clients") or {}).get("phone", "?")
            print(f"  [{e['reason']}] {cliente}")
            print(f"    {(e.get('summary') or '')[:150]}")

    print()
    return 0


async def cmd_show(args: argparse.Namespace) -> int:
    _, db, _wa = _build()
    ticket = await db.get_ticket_by_ref(args.ref)
    if ticket is None:
        print(f"No existe el ticket {args.ref}.", file=sys.stderr)
        return 1

    cliente = ticket.get("clients") or {}
    historial, ultimo = await asyncio.gather(
        db.recent_messages(cliente["id"], 10) if cliente.get("id") else _empty(),
        db.last_inbound_at(cliente["id"]) if cliente.get("id") else _none(),
    )

    print(f"\nTICKET {ticket['ref']}  ·  {ticket['type']}  ·  {ticket['status']}"
          f"  ·  prioridad {ticket['priority']}")
    print(f"Cliente : {_who(ticket)}")
    print(f"Asunto  : {ticket.get('subject') or '(sin asunto)'}")
    print(f"Creado  : {ticket.get('created_at')}")
    print(f"Ventana : {_fmt_window(window_remaining(ultimo))}")

    metadata = ticket.get("metadata") or {}
    if metadata.get("details"):
        print(f"Detalle : {metadata['details']}")
    if metadata.get("last_note"):
        print(f"Nota    : {metadata['last_note']}")

    if historial:
        print("\nÚLTIMOS MENSAJES\n")
        for m in historial:
            quien = "cliente " if m["direction"] == "inbound" else "nosotros"
            print(f"  [{quien}] {m['body'][:160]}")
    print()
    return 0


async def cmd_reply(args: argparse.Namespace) -> int:
    _, db, wa = _build()
    ticket = await db.get_ticket_by_ref(args.ref)
    if ticket is None:
        print(f"No existe el ticket {args.ref}.", file=sys.stderr)
        return 1

    cliente = ticket.get("clients") or {}
    if not cliente.get("phone"):
        print(f"El ticket {args.ref} no tiene un cliente con teléfono.", file=sys.stderr)
        return 1

    restante = window_remaining(await db.last_inbound_at(cliente["id"]))
    if restante is None and not args.force:
        print(
            f"La ventana de 24 h con {cliente['phone']} está CERRADA.\n\n"
            "WhatsApp no acepta mensajes libres fuera de ella: hace falta una "
            "plantilla aprobada. Twilio va a devolver el error 63016.\n\n"
            "Usá --force si querés intentarlo igual (por ejemplo si ya tenés una "
            "plantilla configurada del lado de Twilio).",
            file=sys.stderr,
        )
        return 2

    try:
        sids = await wa.send(cliente["phone"], args.text)
    except Exception as exc:  # noqa: BLE001
        detalle = str(exc)
        if "63016" in detalle:
            detalle += (
                "\n\nEs la ventana de 24 h: el cliente no escribe hace más de un día. "
                "Necesitás una plantilla aprobada en Twilio."
            )
        print(f"No se pudo enviar: {detalle}", file=sys.stderr)
        return 1

    # Queda en el historial que ve el agente. Sin esto, en el próximo mensaje
    # del cliente el agente no sabe que el equipo ya contestó — y lo contradice.
    await db.record_message(
        client_id=cliente["id"],
        direction="outbound",
        body=args.text,
        twilio_sid=sids[0] if sids else None,
        metadata={"source": "operator", "ticket_ref": args.ref},
    )

    if ticket["status"] == "open":
        await db.update_ticket_row(args.ref, {"status": "in_progress"})

    print(f"Enviado a {cliente['phone']} · ticket {args.ref} → in_progress")
    return 0


async def cmd_close(args: argparse.Namespace) -> int:
    _, db, wa = _build()
    ticket = await db.get_ticket_by_ref(args.ref)
    if ticket is None:
        print(f"No existe el ticket {args.ref}.", file=sys.stderr)
        return 1

    cliente = ticket.get("clients") or {}

    if args.message:
        restante = window_remaining(await db.last_inbound_at(cliente["id"]))
        if restante is None and not args.force:
            print(
                "La ventana de 24 h está cerrada: no se puede avisar al cliente.\n"
                "Cerrá sin --message, o usá --force si tenés plantilla.",
                file=sys.stderr,
            )
            return 2
        sids = await wa.send(cliente["phone"], args.message)
        await db.record_message(
            client_id=cliente["id"],
            direction="outbound",
            body=args.message,
            twilio_sid=sids[0] if sids else None,
            metadata={"source": "operator", "ticket_ref": args.ref},
        )
        print(f"Avisado a {cliente['phone']}")

    await db.update_ticket_row(
        args.ref,
        {"status": "closed"},
        metadata_patch={"closed_note": args.note} if args.note else None,
    )

    # Un escalado que queda pendiente para siempre hace que el equipo deje de
    # mirar la cola.
    resueltos = await db.resolve_escalations_for_ticket(ticket["id"])

    extra = f" · {resueltos} escalado(s) resuelto(s)" if resueltos else ""
    print(f"Ticket {args.ref} cerrado{extra}")
    return 0


async def _empty() -> list[Any]:
    return []


async def _none() -> None:
    return None


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(
        prog="inbox",
        description="Bandeja del operador: contestar y cerrar tickets.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Tickets abiertos y escalados pendientes")

    p_show = sub.add_parser("show", help="Detalle de un ticket y su conversación")
    p_show.add_argument("ref", type=int)

    p_reply = sub.add_parser("reply", help="Contestarle al cliente por WhatsApp")
    p_reply.add_argument("ref", type=int)
    p_reply.add_argument("text")
    p_reply.add_argument("--force", action="store_true",
                         help="Intentar aunque la ventana de 24 h esté cerrada")

    p_close = sub.add_parser("close", help="Cerrar el ticket")
    p_close.add_argument("ref", type=int)
    p_close.add_argument("--note", help="Nota interna, se guarda en metadata")
    p_close.add_argument("--message", help="Aviso final al cliente antes de cerrar")
    p_close.add_argument("--force", action="store_true")

    args = parser.parse_args()
    handlers = {
        "list": cmd_list, "show": cmd_show, "reply": cmd_reply, "close": cmd_close
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    raise SystemExit(main())

"""La ventana de 24 h de WhatsApp.

WhatsApp sólo deja mandar mensajes libres dentro de las 24 h desde el último
mensaje del cliente. Pasado ese plazo hace falta una plantilla aprobada y Twilio
devuelve el error 63016. La usan la bandeja de consola y el panel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

WINDOW = timedelta(hours=24)


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

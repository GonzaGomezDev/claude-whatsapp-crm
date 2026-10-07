"""Rate limiting por tool, no por usuario.

Punto 2 de "lo que cambiaría" del video. Limitar a "10 llamadas a Claude por
usuario por minuto" es demasiado grueso: mete en la misma bolsa una query cara
a la DB y una búsqueda barata en la KB.

Acá cada tool declara su propio presupuesto en su decorador:

    find_client       →  "5/minute"    (pega a Supabase, es cara)
    knowledge_search  → "50/minute"    (índice GIN, es barata)

Token bucket clásico: capacidad = el número declarado, y se recarga de forma
continua (no en saltos por ventana), así no hay efecto manada al cambiar de
minuto.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

_PERIODS = {
    "second": 1.0,
    "sec": 1.0,
    "s": 1.0,
    "minute": 60.0,
    "min": 60.0,
    "m": 60.0,
    "hour": 3600.0,
    "h": 3600.0,
}


class RateLimitExceeded(RuntimeError):
    def __init__(self, tool: str, spec: str, retry_in_s: float) -> None:
        self.tool = tool
        self.retry_in_s = retry_in_s
        super().__init__(
            f"Rate limit de '{tool}' ({spec}) agotado. Reintentable en {retry_in_s:.1f}s."
        )


def parse_rate(spec: str) -> tuple[float, float]:
    """'5/minute' -> (5.0, 60.0). Levanta ValueError si el spec está mal escrito."""
    try:
        raw_count, raw_period = spec.split("/", 1)
        count = float(raw_count.strip())
        period = _PERIODS[raw_period.strip().lower()]
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"Rate limit inválido: {spec!r}. Se espera algo como '5/minute' "
            f"(períodos válidos: {', '.join(sorted(set(_PERIODS)))})."
        ) from exc
    if count <= 0:
        raise ValueError(f"Rate limit inválido: {spec!r}. El contador debe ser > 0.")
    return count, period


@dataclass
class _Bucket:
    capacity: float
    refill_per_s: float
    tokens: float
    updated_at: float


@dataclass
class RateLimiter:
    """Un bucket por tool. In-process, igual que el circuit breaker."""

    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self, tool: str, spec: str) -> None:
        """Consume un token o levanta RateLimitExceeded. No bloquea nunca.

        Deliberadamente no espera: preferimos devolverle a Claude un error
        explícito y que decida (reintentar más tarde, usar otra skill, escalar)
        antes que quedarnos dormidos adentro del presupuesto de latencia.
        """
        capacity, period = parse_rate(spec)
        refill = capacity / period
        now = time.monotonic()

        async with self._lock:
            bucket = self._buckets.get(tool)
            if bucket is None or bucket.capacity != capacity:
                bucket = _Bucket(capacity, refill, capacity, now)
                self._buckets[tool] = bucket

            elapsed = now - bucket.updated_at
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_per_s)
            bucket.updated_at = now

            if bucket.tokens < 1.0:
                deficit = 1.0 - bucket.tokens
                raise RateLimitExceeded(tool, spec, deficit / bucket.refill_per_s)

            bucket.tokens -= 1.0

    def snapshot(self) -> dict[str, float]:
        return {tool: round(b.tokens, 2) for tool, b in self._buckets.items()}

"""Circuit breaker por tool.

En el video esto figura como backlog. Está implementado igual, porque sin él el
escenario de fallo del minuto 8 no se sostiene: si Supabase se pone lento, un
agente sin breaker sigue reintentando contra un servicio caído, quema el
presupuesto de latencia y termina sin responderle al cliente.

Con breaker: a los N fallos la tool deja de intentarse por un rato, Claude ve un
error inmediato y explícito, y puede decidir escalar a un humano. La skill que
falla no arrastra a las otras cuatro.

Estados:
    closed    → todo normal, las llamadas pasan
    open      → cortado; falla rápido sin tocar el servicio
    half_open → pasa UNA llamada de prueba; si anda vuelve a closed, si no reabre
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """La tool está cortada; ni se intentó llamar al servicio."""

    def __init__(self, tool: str, retry_in_s: float) -> None:
        self.tool = tool
        self.retry_in_s = retry_in_s
        super().__init__(
            f"Circuito abierto para '{tool}'. Reintentable en {retry_in_s:.1f}s."
        )


@dataclass
class _Circuit:
    failures: int = 0
    opened_at: float | None = None
    state: BreakerState = BreakerState.CLOSED
    half_open_in_flight: bool = False


@dataclass
class CircuitBreaker:
    """Registro de circuitos, uno por nombre de tool.

    Es in-process a propósito: sin dependencias externas, y el estado se pierde
    al reiniciar. Con varios workers cada uno tiene su propio criterio. Para
    estado compartido entre réplicas hace falta Redis — está anotado en el
    README como límite conocido, no lo vendemos como distribuido.
    """

    threshold: int = 3
    cooldown_s: float = 30.0
    _circuits: dict[str, _Circuit] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _get(self, tool: str) -> _Circuit:
        return self._circuits.setdefault(tool, _Circuit())

    def state_of(self, tool: str) -> BreakerState:
        return self._get(tool).state

    async def before_call(self, tool: str) -> None:
        """Levanta CircuitOpenError si la tool está cortada."""
        async with self._lock:
            c = self._get(tool)
            if c.state is BreakerState.CLOSED:
                return

            if c.state is BreakerState.OPEN:
                elapsed = time.monotonic() - (c.opened_at or 0.0)
                if elapsed < self.cooldown_s:
                    raise CircuitOpenError(tool, self.cooldown_s - elapsed)
                # Se cumplió el cooldown: dejamos pasar una sonda.
                c.state = BreakerState.HALF_OPEN
                c.half_open_in_flight = True
                return

            # HALF_OPEN: sólo una sonda a la vez, el resto sigue fallando rápido.
            if c.half_open_in_flight:
                raise CircuitOpenError(tool, self.cooldown_s)
            c.half_open_in_flight = True

    async def record_success(self, tool: str) -> None:
        async with self._lock:
            c = self._get(tool)
            c.failures = 0
            c.opened_at = None
            c.state = BreakerState.CLOSED
            c.half_open_in_flight = False

    async def record_failure(self, tool: str) -> None:
        async with self._lock:
            c = self._get(tool)
            c.half_open_in_flight = False

            # Un fallo durante la sonda reabre de una, sin volver a contar hasta N.
            if c.state is BreakerState.HALF_OPEN:
                c.state = BreakerState.OPEN
                c.opened_at = time.monotonic()
                return

            c.failures += 1
            if c.failures >= self.threshold:
                c.state = BreakerState.OPEN
                c.opened_at = time.monotonic()

    def snapshot(self) -> dict[str, str]:
        """Estado de todos los circuitos, para el endpoint /health."""
        return {tool: c.state.value for tool, c in self._circuits.items()}

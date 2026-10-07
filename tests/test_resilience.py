"""Circuit breaker y rate limiter.

Son los dos mecanismos que en el video figuran como backlog. Sin tests que fijen
su comportamiento, el escenario de fallo del minuto 8 es una casualidad.
"""

from __future__ import annotations

import asyncio

import pytest

from whatsapp_skills.resilience.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
)
from whatsapp_skills.resilience.rate_limit import (
    RateLimiter,
    RateLimitExceeded,
    parse_rate,
)

# ── Circuit breaker ─────────────────────────────────────────────────────────


async def test_abre_recien_al_llegar_al_umbral():
    breaker = CircuitBreaker(threshold=3, cooldown_s=30)

    for _ in range(2):
        await breaker.before_call("find_client")  # todavía pasa
        await breaker.record_failure("find_client")
    assert breaker.state_of("find_client") is BreakerState.CLOSED

    await breaker.before_call("find_client")
    await breaker.record_failure("find_client")
    assert breaker.state_of("find_client") is BreakerState.OPEN


async def test_abierto_falla_rapido_sin_tocar_el_servicio():
    breaker = CircuitBreaker(threshold=1, cooldown_s=30)
    await breaker.record_failure("x")

    with pytest.raises(CircuitOpenError) as exc:
        await breaker.before_call("x")
    assert exc.value.retry_in_s > 0


async def test_un_exito_resetea_el_contador():
    breaker = CircuitBreaker(threshold=3, cooldown_s=30)
    await breaker.record_failure("x")
    await breaker.record_failure("x")
    await breaker.record_success("x")
    await breaker.record_failure("x")
    # Sin el reset, este tercer fallo habría abierto el circuito.
    assert breaker.state_of("x") is BreakerState.CLOSED


async def test_pasa_a_half_open_cuando_vence_el_cooldown():
    breaker = CircuitBreaker(threshold=1, cooldown_s=0.05)
    await breaker.record_failure("x")
    assert breaker.state_of("x") is BreakerState.OPEN

    await asyncio.sleep(0.06)
    await breaker.before_call("x")  # la sonda pasa
    assert breaker.state_of("x") is BreakerState.HALF_OPEN


async def test_half_open_deja_pasar_una_sola_sonda():
    breaker = CircuitBreaker(threshold=1, cooldown_s=0.05)
    await breaker.record_failure("x")
    await asyncio.sleep(0.06)

    await breaker.before_call("x")
    with pytest.raises(CircuitOpenError):
        await breaker.before_call("x")


async def test_un_fallo_en_half_open_reabre_de_inmediato():
    """No se vuelve a contar hasta el umbral: el servicio ya demostró que sigue mal."""
    breaker = CircuitBreaker(threshold=3, cooldown_s=0.05)
    for _ in range(3):
        await breaker.record_failure("x")
    await asyncio.sleep(0.06)

    await breaker.before_call("x")
    await breaker.record_failure("x")
    assert breaker.state_of("x") is BreakerState.OPEN


async def test_una_sonda_exitosa_cierra_el_circuito():
    breaker = CircuitBreaker(threshold=1, cooldown_s=0.05)
    await breaker.record_failure("x")
    await asyncio.sleep(0.06)

    await breaker.before_call("x")
    await breaker.record_success("x")
    assert breaker.state_of("x") is BreakerState.CLOSED


async def test_los_circuitos_son_independientes_por_tool():
    """Que se caiga una skill no puede arrastrar a las otras cuatro."""
    breaker = CircuitBreaker(threshold=1, cooldown_s=30)
    await breaker.record_failure("find_client")

    assert breaker.state_of("find_client") is BreakerState.OPEN
    assert breaker.state_of("knowledge_search") is BreakerState.CLOSED
    await breaker.before_call("knowledge_search")  # no levanta


# ── Rate limiter ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spec", "esperado"),
    [("5/minute", (5.0, 60.0)), ("50/min", (50.0, 60.0)), ("2/s", (2.0, 1.0))],
)
def test_parse_rate(spec, esperado):
    assert parse_rate(spec) == esperado


@pytest.mark.parametrize("spec", ["5", "5/decade", "0/minute", "-1/minute", "abc/minute"])
def test_parse_rate_rechaza_specs_invalidos(spec):
    """Falla al importar la skill, no en producción."""
    with pytest.raises(ValueError):
        parse_rate(spec)


async def test_permite_hasta_la_capacidad_y_despues_corta():
    limiter = RateLimiter()
    for _ in range(5):
        await limiter.acquire("find_client", "5/minute")

    with pytest.raises(RateLimitExceeded) as exc:
        await limiter.acquire("find_client", "5/minute")
    assert exc.value.retry_in_s > 0


async def test_los_presupuestos_son_por_tool():
    """El punto 2 de 'lo que cambiaría': la tool cara no consume el cupo de la barata."""
    limiter = RateLimiter()
    for _ in range(5):
        await limiter.acquire("find_client", "5/minute")

    with pytest.raises(RateLimitExceeded):
        await limiter.acquire("find_client", "5/minute")

    await limiter.acquire("knowledge_search", "50/minute")  # intacta


async def test_el_bucket_se_recarga_de_forma_continua():
    limiter = RateLimiter()
    await limiter.acquire("x", "10/s")  # recarga: 10 tokens por segundo
    for _ in range(9):
        await limiter.acquire("x", "10/s")

    with pytest.raises(RateLimitExceeded):
        await limiter.acquire("x", "10/s")

    await asyncio.sleep(0.15)  # alcanza para ~1.5 tokens
    await limiter.acquire("x", "10/s")


async def test_no_bloquea_nunca():
    """Devuelve el error para que Claude decida; dormirse comería el presupuesto de latencia."""
    limiter = RateLimiter()
    await limiter.acquire("x", "1/hour")

    started = asyncio.get_running_loop().time()
    with pytest.raises(RateLimitExceeded):
        await limiter.acquire("x", "1/hour")
    assert asyncio.get_running_loop().time() - started < 0.1

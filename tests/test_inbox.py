"""La bandeja del operador y la ventana de 24 h de WhatsApp.

La ventana es la regla que más sorprende en producción: podés contestar un
ticket a la mañana siguiente y el mensaje simplemente no sale. Mejor enterarse
por un chequeo explícito que por un error 63016 de Twilio.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from inbox import _fmt_window, _parse_ts, _who, window_remaining  # noqa: E402

AHORA = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)


# ── Ventana de 24 h ─────────────────────────────────────────────────────────


def test_recien_escribio_la_ventana_esta_abierta():
    restante = window_remaining("2026-08-20T17:30:00+00:00", now=AHORA)
    assert restante is not None
    assert restante > timedelta(hours=23)


def test_a_las_23_horas_todavia_queda_margen():
    # 19:00 del día anterior + 24 h = 19:00 de hoy. Son las 18:00 -> queda 1 h.
    restante = window_remaining("2026-08-19T19:00:00+00:00", now=AHORA)
    assert restante == timedelta(hours=1)


def test_pasadas_las_24_horas_la_ventana_esta_cerrada():
    assert window_remaining("2026-08-19T17:00:00+00:00", now=AHORA) is None


def test_justo_en_el_limite_cuenta_como_cerrada():
    assert window_remaining("2026-08-19T18:00:00+00:00", now=AHORA) is None


def test_un_cliente_que_nunca_escribio_no_tiene_ventana():
    assert window_remaining(None, now=AHORA) is None


@pytest.mark.parametrize(
    "ts",
    [
        "2026-08-20T17:30:00Z",        # sufijo Z
        "2026-08-20T17:30:00+00:00",   # offset explícito
        "2026-08-20T17:30:00",         # sin tz: se asume UTC
    ],
)
def test_acepta_los_formatos_que_devuelve_supabase(ts):
    assert window_remaining(ts, now=AHORA) is not None


def test_una_fecha_ilegible_no_rompe_el_cli():
    """Preferimos decir 'ventana cerrada' antes que tirar una excepción."""
    assert _parse_ts("mañana a la tarde") is None
    assert window_remaining("mañana a la tarde", now=AHORA) is None


# ── Presentación ────────────────────────────────────────────────────────────


def test_el_mensaje_de_ventana_cerrada_explica_que_hacer():
    texto = _fmt_window(None)
    assert "CERRADA" in texto
    assert "plantilla" in texto


def test_el_mensaje_de_ventana_abierta_muestra_cuanto_queda():
    assert _fmt_window(timedelta(hours=5, minutes=30)) == "abierta, quedan 5h 30m"


def test_muestra_al_cliente_con_lo_que_haya():
    assert "Gonzalo" in _who({"clients": {"name": "Gonzalo", "phone": "+549"}})
    assert "GG Code" in _who(
        {"clients": {"name": "G", "company": "GG Code", "phone": "+549"}}
    )
    # Un cliente recién creado puede no tener nombre todavía.
    assert "(sin nombre)" in _who({"clients": {"phone": "+549"}})

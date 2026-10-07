"""Capa 2 y el splitter de salida.

El router decide qué mensajes NO llegan al modelo. Cada falso positivo acá es un
cliente real que recibe una respuesta enlatada, así que conviene que sea
conservador: ante la duda, que pase al agente.
"""

from __future__ import annotations

import pytest

from whatsapp_skills.integrations.twilio_client import _split, strip_whatsapp
from whatsapp_skills.router import Route, route_message

# ── Router ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        "Hola, soy Juan Pérez, necesito una cotización para 500 unidades de X",
        "gracias pero necesito hablar con alguien",
        "ok, y cuánto sale el envío?",
        "Listo el pago, te paso el comprobante",
    ],
)
def test_los_mensajes_con_contenido_van_al_agente(texto):
    assert route_message(texto).route is Route.AGENT


@pytest.mark.parametrize("texto", ["gracias", "Gracias!", "  dale  ", "ok", "👍", "joya"])
def test_la_cortesia_sola_se_responde_sin_modelo(texto):
    decision = route_message(texto)
    assert decision.route is Route.DIRECT_REPLY
    assert decision.reason == "cortesia"


@pytest.mark.parametrize("texto", ["STOP", "baja", "Unsubscribe"])
def test_el_opt_out_se_resuelve_sin_modelo(texto):
    decision = route_message(texto)
    assert decision.route is Route.DIRECT_REPLY
    assert decision.reason == "opt_out"


def test_un_mensaje_vacio_se_ignora():
    assert route_message("   ").route is Route.IGNORE


def test_media_sin_texto_recibe_una_explicacion():
    decision = route_message("", num_media=1)
    assert decision.route is Route.DIRECT_REPLY
    assert "texto" in (decision.reply or "")


def test_media_con_texto_va_al_agente():
    """El caption puede tener el pedido real."""
    assert route_message("acá va el comprobante", num_media=1).route is Route.AGENT


# ── Normalización de números ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("whatsapp:+5491123456789", "+5491123456789"),
        ("+5491123456789", "+5491123456789"),
        ("  whatsapp:+549  ", "+549"),
    ],
)
def test_strip_whatsapp(entrada, esperado):
    assert strip_whatsapp(entrada) == esperado


# ── Splitter de mensajes salientes ──────────────────────────────────────────


def test_un_mensaje_corto_no_se_parte():
    assert _split("hola", 100) == ["hola"]


def test_un_mensaje_vacio_no_produce_un_envio_vacio():
    """Twilio rechaza un body vacío."""
    assert _split("", 100) == ["…"]


def test_parte_por_parrafo_antes_que_por_oracion():
    texto = "Primer párrafo.\n\nSegundo párrafo."
    partes = _split(texto, 20)
    assert partes == ["Primer párrafo.", "Segundo párrafo."]


def test_ninguna_parte_supera_el_limite():
    texto = " ".join(f"Oración número {i} con algo de relleno." for i in range(60))
    partes = _split(texto, 200)
    assert len(partes) > 1
    assert all(len(p) <= 200 for p in partes)


def test_no_se_pierde_contenido_al_partir():
    texto = "Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete. Ocho."
    unido = " ".join(_split(texto, 20)).replace("  ", " ")
    for palabra in ("Uno", "Cinco", "Ocho"):
        assert palabra in unido

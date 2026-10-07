"""Skill 3.

Estos tests son una regresión de dos bugs reales que aparecieron con el agente
conversando de verdad por WhatsApp:

1. `websearch_to_tsquery` une los términos con AND. "lista de precios actuales"
   devolvía CERO documentos porque ninguno contiene la palabra "actual" — aunque
   la lista de precios estaba ahí y matcheaba 2 de 3 términos.

2. `ts_headline` devolvía fragmentos, no documentos. El modelo veía el 40% de la
   política de pagos, cortada a mitad de oración, y respondía —correctamente—
   que no tenía el detalle completo.

El fallback a OR y el contenido completo viven en la RPC (`supabase/schema.sql`);
lo que se prueba acá es que la skill le transmita al modelo qué recibió.
"""

from __future__ import annotations

from typing import Any

import pytest

from whatsapp_skills.skills.base import SkillContext


class FakeDB:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int]] = []

    async def search_knowledge(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append((query, limit))
        return self.rows


def row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Lista de precios 2026",
        "source": "pricelist_2026.pdf",
        "content": "El producto X cuesta USD 12 la unidad.",
        "truncated": False,
        "matched_terms": 3,
        "query_terms": 3,
        "confidence": 0.42,
        "match_mode": "all_terms",
    }
    return {**base, **overrides}


async def _search(registry, rows: list[dict[str, Any]], query: str = "precios lista"):
    ctx = SkillContext(phone="+5491100000000", settings=None, db=FakeDB(rows))
    result, is_error = await registry.dispatch(
        "knowledge_search", {"query": query, "limit": 5}, ctx
    )
    assert is_error is False
    return result


async def test_un_match_completo_dice_que_se_puede_citar(registry):
    result = await _search(registry, [row()])
    assert result["count"] == 1
    assert result["match_mode"] == "all_terms"
    assert "citá el documento" in result["guidance"]
    assert result["docs"][0]["content"] == "El producto X cuesta USD 12 la unidad."


async def test_sin_resultados_manda_a_reformular_y_despues_al_ticket(registry):
    result = await _search(registry, [])
    assert result["count"] == 0
    assert "sinónimos" in result["guidance"]
    assert "quotation" in result["guidance"]
    # Lo que NO tiene que decir: que responda igual.
    assert "inventar" in result["guidance"]


async def test_el_modo_any_term_avisa_que_el_match_es_parcial(registry):
    """Bug 1: sin este aviso, el modelo cita un documento que matcheó 1 de 4."""
    result = await _search(
        registry,
        [row(match_mode="any_term", matched_terms=2, query_terms=4)],
        query="lista de precios actuales vigentes",
    )
    assert result["match_mode"] == "any_term"
    assert "2 de 4" in result["guidance"]
    assert "puede no ser sobre lo que preguntaste" in result["guidance"]


async def test_un_documento_truncado_avisa_que_falta_contenido(registry):
    """Bug 2: el modelo tiene que saber que está viendo un pedazo."""
    result = await _search(registry, [row(truncated=True)])
    assert result["docs"][0]["truncated"] is True
    assert "truncados" in result["guidance"]
    assert "completa" in result["guidance"]


async def test_el_contenido_completo_llega_sin_recortar(registry):
    """La skill no vuelve a recortar lo que la RPC ya decidió mandar entero."""
    largo = "Aceptamos tarjeta de credito. " * 40
    result = await _search(registry, [row(content=largo, truncated=False)])
    assert result["docs"][0]["content"] == largo


async def test_los_numeros_vienen_del_motor_no_del_modelo(registry):
    result = await _search(registry, [row(confidence=0.4962, matched_terms=2, query_terms=3)])
    doc = result["docs"][0]
    assert doc["confidence"] == 0.496
    assert doc["matched_terms"] == 2
    assert doc["query_terms"] == 3


async def test_los_documentos_conservan_el_orden_de_la_rpc(registry):
    """La RPC ordena por matched_terms y después por rank. No lo reordenamos."""
    result = await _search(
        registry,
        [
            row(title="Lista de precios 2026", matched_terms=2, confidence=0.305),
            row(title="Descuentos por volumen", matched_terms=2, confidence=0.139),
        ],
    )
    assert [d["title"] for d in result["docs"]] == [
        "Lista de precios 2026",
        "Descuentos por volumen",
    ]


@pytest.mark.parametrize("faltante", ["matched_terms", "query_terms", "confidence"])
async def test_tolera_columnas_opcionales_faltantes(registry, faltante):
    """Una columna de metadata que falte degrada; no tumba la búsqueda."""
    incompleta = row()
    del incompleta[faltante]
    result = await _search(registry, [incompleta])
    assert result["count"] == 1


async def test_una_rpc_vieja_dice_exactamente_que_hacer(registry):
    """La RPC anterior devolvía `excerpt` en vez de `content`.

    Sin este chequeo el fallo era un KeyError sin contexto, la tool se marcaba
    como caída y el agente escalaba a un humano — todo por no haber corrido el
    schema actualizado.
    """
    vieja = {
        "id": "x",
        "title": "Lista de precios 2026",
        "source": "pricelist_2026.pdf",
        "excerpt": "fragmento cortado a mitad de",
        "confidence": 0.42,
    }
    ctx = SkillContext(phone="+5491100000000", settings=None, db=FakeDB([vieja]))
    result, is_error = await registry.dispatch(
        "knowledge_search", {"query": "precios", "limit": 5}, ctx
    )
    assert is_error is True
    assert "schema.sql" in result["error"]
    assert "desactualizada" in result["error"]

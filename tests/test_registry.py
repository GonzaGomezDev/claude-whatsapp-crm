"""El registry es el punto único de ejecución. Si se rompe, se rompe todo."""

from __future__ import annotations

import pytest

from whatsapp_skills.skills.base import BUILTIN_SKILL, SkillContext
from whatsapp_skills.skills.registry import TOOL_SEARCH_TOOL

EXPECTED_SKILLS = {
    "client-management",
    "ticketing",
    "knowledge",
    "human-handoff",
}


def test_descubre_las_cinco_skills(registry):
    assert set(registry.docs) == EXPECTED_SKILLS


def test_cada_skill_aporta_al_menos_una_tool(registry):
    por_skill = {}
    for tool in registry.tools.values():
        por_skill.setdefault(tool.skill, []).append(tool.name)
    for skill in EXPECTED_SKILLS:
        assert por_skill.get(skill), f"{skill} no registró ninguna tool"


def test_los_schemas_cumplen_lo_que_exige_strict(registry):
    """strict=True es rechazado por la API sin additionalProperties ni required."""
    for tool in registry.tools.values():
        if not tool.strict:
            continue
        schema = tool.input_schema
        assert schema["type"] == "object", tool.name
        assert schema.get("additionalProperties") is False, tool.name
        assert "required" in schema, tool.name


def test_los_required_existen_en_properties(registry):
    for tool in registry.tools.values():
        properties = set(tool.input_schema.get("properties", {}))
        faltantes = set(tool.input_schema.get("required", [])) - properties
        assert not faltantes, f"{tool.name}: required sin property: {faltantes}"


def test_modo_full_carga_todo_sin_diferir(registry):
    tools = registry.anthropic_tools("full")
    assert len(tools) == len(registry.tools)
    assert not any(t.get("defer_loading") for t in tools)


def test_modo_deferred_respeta_las_reglas_de_la_api(registry):
    """La tool de búsqueda no se difiere, y al menos una tool queda cargada.

    Si las dos condiciones no se cumplen, la API devuelve 400.
    """
    tools = registry.anthropic_tools("deferred")

    search = [t for t in tools if t.get("type", "").startswith("tool_search_tool")]
    assert len(search) == 1
    assert not search[0].get("defer_loading")

    cargadas = [t for t in tools if not t.get("defer_loading")]
    assert len(cargadas) >= 1, "la API rechaza un request con todas las tools diferidas"
    assert TOOL_SEARCH_TOOL in tools


def test_el_orden_de_las_tools_es_estable(registry):
    """El prefijo se cachea. Reordenar las tools lo invalida en silencio."""
    assert registry.anthropic_tools("full") == registry.anthropic_tools("full")
    assert registry.system_prompt_block() == registry.system_prompt_block()


def test_load_skill_guide_es_builtin_y_no_pide_su_propio_skill_md(registry):
    assert registry.tools["load_skill_guide"].skill == BUILTIN_SKILL


async def test_load_skill_guide_devuelve_el_cuerpo(registry):
    ctx = SkillContext(phone="+5491100000000", settings=None)
    result, is_error = await registry.dispatch(
        "load_skill_guide", {"skill": "knowledge"}, ctx
    )
    assert is_error is False
    assert result["found"] is True
    assert "confidence" in result["guide"]


async def test_load_skill_guide_con_skill_inexistente_no_es_excepcion(registry):
    ctx = SkillContext(phone="+5491100000000", settings=None)
    result, is_error = await registry.dispatch(
        "load_skill_guide", {"skill": "no-existe"}, ctx
    )
    assert is_error is False
    assert result["found"] is False
    assert sorted(result["available"]) == sorted(EXPECTED_SKILLS)


async def test_tool_desconocida_devuelve_error_sin_levantar(registry):
    ctx = SkillContext(phone="+5491100000000", settings=None)
    result, is_error = await registry.dispatch("no_existe", {}, ctx)
    assert is_error is True
    assert "available" in result


async def test_una_excepcion_del_handler_vuelve_como_tool_result(registry):
    """La API exige un tool_result por cada tool_use. dispatch nunca propaga."""

    class BaseExplosiva:
        async def find_client_by_phone(self, phone):
            raise ConnectionError("la base se cayó")

    ctx = SkillContext(phone="+5491100000000", settings=None, db=BaseExplosiva())
    result, is_error = await registry.dispatch("find_client", {"phone": "+549110"}, ctx)

    assert is_error is True
    assert result["error_type"] == "ConnectionError"
    assert "la base se cayó" in result["error"]


async def test_argumentos_invalidos_no_cuentan_para_el_breaker(registry):
    """Un schema mal armado es un bug nuestro, no un servicio caído."""
    ctx = SkillContext(phone="+5491100000000", settings=None)
    result, is_error = await registry.dispatch(
        "load_skill_guide", {"parametro_inexistente": 1}, ctx
    )
    assert is_error is True
    assert result["error_type"] == "bad_arguments"
    assert registry.breaker.state_of("load_skill_guide").value == "closed"


@pytest.mark.parametrize("mode", ["full", "deferred", "progressive"])
def test_todas_las_tools_expuestas_tienen_nombre_y_descripcion(registry, mode):
    for tool in registry.anthropic_tools(mode):
        assert tool.get("name")
        if "type" not in tool:  # las server tools no llevan description
            assert len(tool.get("description", "")) > 20

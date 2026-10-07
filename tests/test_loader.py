"""El parser de SKILL.md.

Tiene que fallar ruidoso y con un mensaje que diga qué arreglar. Un SKILL.md mal
formado que carga a medias es peor que uno que no carga.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whatsapp_skills.skills.loader import SkillLoadError, load_skill_docs, parse_skill_md

VALIDO = """\
---
name: mi-skill
description: >-
  Hace algo concreto y explica cuándo conviene usarla, con detalle suficiente
  para que el modelo pueda decidir solo.
---

# Mi Skill

Cuerpo de la guía.
"""


def _parse(text: str, name: str = "mi-skill"):
    return parse_skill_md(text, Path(f"skills/{name}/SKILL.md"))


def test_parsea_frontmatter_y_cuerpo():
    doc = _parse(VALIDO)
    assert doc.name == "mi-skill"
    assert doc.description.startswith("Hace algo concreto")
    assert doc.body.startswith("# Mi Skill")


def test_la_description_se_normaliza_a_una_linea():
    """El block scalar del YAML viene con saltos; el system prompt los quiere planos."""
    assert "\n" not in _parse(VALIDO).description


def test_sin_frontmatter_falla_con_instrucciones():
    with pytest.raises(SkillLoadError, match="frontmatter"):
        _parse("# Sin frontmatter\n\ntexto")


@pytest.mark.parametrize("campo", ["name", "description"])
def test_faltar_un_campo_obligatorio_falla(campo):
    texto = VALIDO.replace(f"{campo}:", f"x_{campo}:")
    with pytest.raises(SkillLoadError, match=campo):
        _parse(texto)


def test_el_name_tiene_que_coincidir_con_la_carpeta():
    """Si no coinciden, Claude Code no descubre bien la skill."""
    with pytest.raises(SkillLoadError, match="no coincide"):
        _parse(VALIDO, name="otra-carpeta")


@pytest.mark.parametrize("nombre", ["MiSkill", "mi_skill", "mi skill", "Mi-Skill"])
def test_el_name_tiene_que_ser_kebab_case(nombre):
    texto = VALIDO.replace("name: mi-skill", f"name: {nombre}")
    with pytest.raises(SkillLoadError, match="kebab-case"):
        parse_skill_md(texto, Path(f"skills/{nombre}/SKILL.md"))


def test_una_description_corta_se_rechaza():
    """Es lo único que Claude ve para decidir si activa la skill."""
    largo = VALIDO.split("description: ", 1)[1].split("---")[0].rstrip()
    texto = VALIDO.replace(f"description: {largo}", "description: hace cosas")
    with pytest.raises(SkillLoadError, match="description"):
        _parse(texto)


def test_yaml_invalido_falla_con_el_path():
    texto = "---\nname: [sin cerrar\n---\n\ncuerpo\n"
    with pytest.raises(SkillLoadError, match="YAML"):
        _parse(texto)


def test_carga_las_skills_reales_del_repo(skills_dir):
    docs = load_skill_docs(skills_dir)
    assert len(docs) == 5
    for name, doc in docs.items():
        assert doc.directory == name
        assert doc.body, f"{name}: el SKILL.md no tiene cuerpo"
        assert "## Error handling" in doc.body, f"{name}: falta la sección de errores"


def test_un_directorio_sin_skills_falla(tmp_path):
    with pytest.raises(SkillLoadError, match="No se encontró"):
        load_skill_docs(tmp_path)


def test_un_directorio_inexistente_falla(tmp_path):
    with pytest.raises(SkillLoadError, match="No existe"):
        load_skill_docs(tmp_path / "nope")

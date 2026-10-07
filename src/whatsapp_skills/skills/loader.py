"""Lectura de los SKILL.md.

Formato Agent Skills real: frontmatter YAML delimitado por '---', con `name` y
`description` obligatorios. Es el mismo formato que lee Claude Code desde
.claude/skills/, así que las mismas carpetas sirven para las dos cosas.

El `description` es lo único que entra siempre al system prompt. El cuerpo se
carga a demanda con la tool `load_skill_guide`. Eso es progressive disclosure:
el costo fijo por request son 5 descripciones, no 5 guías completas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

# Mismo criterio que Claude Code: kebab-case, sin espacios.
_NAME_RE = re.compile(r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")


class SkillLoadError(ValueError):
    """El SKILL.md está mal formado. Falla al arrancar, no en producción."""


@dataclass(frozen=True)
class SkillDoc:
    name: str
    description: str
    body: str
    path: Path

    @property
    def directory(self) -> str:
        return self.path.parent.name


def parse_skill_md(text: str, path: Path) -> SkillDoc:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillLoadError(
            f"{path}: falta el frontmatter YAML. Un SKILL.md tiene que empezar con "
            "'---' en la primera línea, incluir name y description, y cerrar con '---'."
        )

    raw_meta, body = match.group(1), match.group(2)
    try:
        meta = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{path}: el frontmatter no es YAML válido: {exc}") from exc

    if not isinstance(meta, dict):
        raise SkillLoadError(f"{path}: el frontmatter tiene que ser un mapping YAML.")

    for key in ("name", "description"):
        if not meta.get(key) or not isinstance(meta[key], str):
            raise SkillLoadError(
                f"{path}: falta el campo obligatorio '{key}' en el frontmatter "
                "(o no es un string)."
            )

    name = meta["name"].strip()
    if not _NAME_RE.match(name):
        raise SkillLoadError(
            f"{path}: name='{name}' inválido. Usá kebab-case en minúsculas, "
            "por ejemplo 'client-management'."
        )
    if name != path.parent.name:
        raise SkillLoadError(
            f"{path}: name='{name}' no coincide con la carpeta '{path.parent.name}'. "
            "Tienen que ser iguales para que Claude Code las descubra bien."
        )

    description = " ".join(meta["description"].split())
    if len(description) < 40:
        raise SkillLoadError(
            f"{path}: la description tiene {len(description)} caracteres. Es lo único "
            "que Claude ve para decidir si activa la skill — escribí qué hace Y "
            "cuándo usarla (mínimo 40 caracteres)."
        )

    return SkillDoc(name=name, description=description, body=body.strip(), path=path)


def load_skill_docs(skills_dir: Path) -> dict[str, SkillDoc]:
    """Lee todos los skills/*/SKILL.md. Ordenado alfabéticamente.

    El orden importa: el system prompt tiene que ser byte-idéntico entre
    requests o se invalida el prompt cache.
    """
    if not skills_dir.is_dir():
        raise SkillLoadError(f"No existe el directorio de skills: {skills_dir}")

    docs: dict[str, SkillDoc] = {}
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        doc = parse_skill_md(skill_md.read_text(encoding="utf-8"), skill_md)
        docs[doc.name] = doc

    if not docs:
        raise SkillLoadError(f"No se encontró ningún SKILL.md dentro de {skills_dir}")
    return docs

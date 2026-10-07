from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def registry():
    """El registry real, cargado desde skills/.

    A propósito no se mockea: si alguien rompe un SKILL.md o un input_schema,
    los tests tienen que enterarse.
    """
    from whatsapp_skills.skills.registry import SkillRegistry

    return SkillRegistry()


@pytest.fixture
def skills_dir() -> Path:
    return ROOT / "skills"

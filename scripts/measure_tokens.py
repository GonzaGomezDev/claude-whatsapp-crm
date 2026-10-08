"""Mide el costo real, en tokens, de cada estrategia de exposición de tools.

Esto existe porque "empaquetar tools en skills baja el overhead" es una
afirmación, y las afirmaciones sobre tokens se miden. `count_tokens` no consume
tokens de generación: correr esto sale prácticamente cero.

    python scripts/measure_tokens.py

Requiere ANTHROPIC_API_KEY (count_tokens es un endpoint de la Messages API; el
backend cli no lo expone).

Las cuatro configuraciones que compara:

  A  inline      Las 9 tools + las 4 guías SKILL.md completas metidas en el
                 system prompt. Es lo que hace la mayoría cuando quiere que el
                 modelo "sepa cómo usar" sus tools.
  B  full        Las 9 tools + sólo las descripciones de las skills. El cuerpo
                 de cada guía se carga a demanda con load_skill_guide.
  C  deferred    tool_search + las tools con defer_loading. Claude descubre.
  D  sin skills  Sólo las 11 tools de negocio, sin capa de skills. El baseline
                 de "tools sueltos" del que habla el video.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anthropic import Anthropic  # noqa: E402

from whatsapp_skills.agent.backend import Conversation  # noqa: E402
from whatsapp_skills.agent.prompt import PERSONA, static_system_prompt  # noqa: E402
from whatsapp_skills.observability.logging import force_utf8_output  # noqa: E402
from whatsapp_skills.skills.registry import SkillRegistry  # noqa: E402

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")

SAMPLE = "Hola, soy Juan Pérez, necesito una cotización para 500 unidades de X"


def _messages() -> list[dict[str, Any]]:
    return Conversation(phone="+5491123456789", message=SAMPLE).as_messages()


def build_configs(registry: SkillRegistry) -> dict[str, dict[str, Any]]:
    skills_block = registry.system_prompt_block()

    # A: todo adentro del system prompt.
    inline_guides = "\n\n".join(
        f"### {doc.name}\n{doc.description}\n\n{doc.body}"
        for _, doc in sorted(registry.docs.items())
    )

    return {
        "A  inline (guías completas en el system)": {
            "system": f"{PERSONA}\n## Skills disponibles\n\n{inline_guides}\n",
            "tools": registry.anthropic_tools("full"),
        },
        "B  full (descripciones + load_skill_guide)": {
            "system": static_system_prompt(skills_block),
            "tools": registry.anthropic_tools("full"),
        },
        "C  deferred (tool_search + defer_loading)": {
            "system": static_system_prompt(skills_block),
            "tools": registry.anthropic_tools("deferred"),
        },
        "D  sin capa de skills (tools sueltas)": {
            "system": PERSONA,
            "tools": [
                t.to_anthropic()
                for t in sorted(registry.tools.values(), key=lambda t: t.name)
                if t.name != "load_skill_guide"
            ],
        },
    }


def main() -> int:
    force_utf8_output()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Falta ANTHROPIC_API_KEY.\n\n"
            "count_tokens es un endpoint de la Messages API; `claude -p` no lo expone.\n"
            "Sacá una key en console.anthropic.com. Correr este script cuesta\n"
            "prácticamente cero: count_tokens no genera tokens.",
            file=sys.stderr,
        )
        return 1

    registry = SkillRegistry()
    client = Anthropic()
    configs = build_configs(registry)
    messages = _messages()

    print(f"\nmodelo: {MODEL}")
    print(f"mensaje: {SAMPLE!r}")
    print(f"skills: {len(registry.docs)}  ·  tools: {len(registry.tools)}\n")

    results: dict[str, int] = {}
    for label, config in configs.items():
        count = client.messages.count_tokens(
            model=MODEL,
            system=config["system"],
            tools=config["tools"],
            messages=messages,
        )
        results[label] = count.input_tokens

    baseline = max(results.values())
    width = max(len(label) for label in results)

    print(f"{'configuración'.ljust(width)}   tokens    vs. peor caso")
    print("─" * (width + 30))
    for label, tokens in results.items():
        delta = tokens - baseline
        pct = (delta / baseline * 100) if baseline else 0.0
        marker = "—" if delta == 0 else f"{delta:+,} ({pct:+.1f}%)"
        print(f"{label.ljust(width)}   {tokens:>6,}    {marker}")

    print(
        "\nEstos números son por request. Multiplicalos por la cantidad de mensajes\n"
        "que procesás por día para ver de qué estamos hablando.\n"
    )
    print(
        "Nota honesta: lo que baja el costo no es agrupar tools en carpetas — es\n"
        "sacar la prosa de los schemas (B) y diferir las definiciones (C). Si C no\n"
        "te da un ahorro grande acá, es porque con 9 tools el overhead de schema\n"
        "todavía es chico; la diferencia crece con el tamaño del tool set."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

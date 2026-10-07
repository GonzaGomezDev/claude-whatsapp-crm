"""Copia skills/ -> .claude/skills/ para que Claude Code las descubra.

Se copia en vez de linkear porque en Windows los symlinks piden modo
desarrollador o privilegios de admin, y este repo tiene que clonarse y andar.

Corrélo cada vez que toques un SKILL.md, antes de usar AGENT_BACKEND=cli:

    python scripts/sync_skills.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills"
TARGET = ROOT / ".claude" / "skills"


def main() -> int:
    if not SOURCE.is_dir():
        print(f"No existe {SOURCE}", file=sys.stderr)
        return 1

    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    copied = 0
    for skill_md in sorted(SOURCE.glob("*/SKILL.md")):
        destination = TARGET / skill_md.parent.name
        # Sólo el SKILL.md: tools.py lo ejecuta el server MCP desde skills/,
        # no Claude Code. Copiarlo sería confuso y encima quedaría desincronizado.
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, destination / "SKILL.md")
        copied += 1
        print(f"  {skill_md.parent.name}")

    print(f"\n{copied} skills copiadas a {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

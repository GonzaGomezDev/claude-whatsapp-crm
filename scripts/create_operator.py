"""Crea un operador del panel: usuario de Supabase Auth + fila en `operators`.

    python scripts/create_operator.py vos@tuempresa.com                 # admin
    python scripts/create_operator.py ana@tuempresa.com --role agent --name Ana

Es el bootstrap: el primer operador tiene que ser admin, y desde ahí el resto
se da de alta en el panel (Usuarios). Genera la contraseña y la imprime una sola
vez. Si el email ya existe en Auth, no lo toca: sólo lo da de alta como operador.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatsapp_skills.config import get_settings  # noqa: E402
from whatsapp_skills.integrations.supabase_client import Database  # noqa: E402
from whatsapp_skills.observability.logging import force_utf8_output  # noqa: E402


def main() -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description="Alta de un operador del panel.")
    parser.add_argument("email")
    parser.add_argument("--role", choices=["admin", "agent"], default="admin")
    parser.add_argument("--name")
    args = parser.parse_args()

    settings = get_settings()
    db = Database(settings.supabase_url, settings.supabase_secret_key)
    _, password = asyncio.run(
        db.create_operator(args.email.strip().lower(), name=args.name, role=args.role)
    )

    print(f"Operador listo: {args.email} ({args.role})")
    if password:
        print(f"Contraseña generada (guardala, no se vuelve a mostrar): {password}")
    else:
        print("El usuario ya existía en Auth: se mantiene su contraseña.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

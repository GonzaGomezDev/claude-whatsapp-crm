"""Crea un operador del panel: usuario de Supabase Auth + fila en `operators`.

    python scripts/create_operator.py vos@tuempresa.com
    python scripts/create_operator.py vos@tuempresa.com --password "una-clave-larga"

Sin --password genera una y la imprime una sola vez. Si el email ya existe en
Auth, no lo toca: sólo lo da de alta como operador.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supabase import create_client  # noqa: E402

from whatsapp_skills.config import get_settings  # noqa: E402
from whatsapp_skills.observability.logging import force_utf8_output  # noqa: E402


def find_user_id(admin, email: str) -> str | None:
    page = 1
    while True:
        users = admin.list_users(page=page, per_page=200)
        for user in users:
            if (user.email or "").lower() == email.lower():
                return user.id
        if len(users) < 200:
            return None
        page += 1


def main() -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description="Alta de un operador del panel.")
    parser.add_argument("email")
    parser.add_argument("--password", help="Si falta, se genera una")
    args = parser.parse_args()

    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    admin = client.auth.admin

    user_id = find_user_id(admin, args.email)
    password = None
    if user_id is None:
        password = args.password or secrets.token_urlsafe(12)
        created = admin.create_user(
            {"email": args.email, "password": password, "email_confirm": True}
        )
        user_id = created.user.id

    client.table("operators").upsert({"user_id": user_id}, on_conflict="user_id").execute()

    print(f"Operador listo: {args.email}")
    if password and not args.password:
        print(f"Contraseña generada (guardala, no se vuelve a mostrar): {password}")
    elif password is None:
        print("El usuario ya existía en Auth: se mantiene su contraseña.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Ver y apuntar el webhook entrante del número de WhatsApp (TWILIO_WHATSAPP_FROM).

    python scripts/twilio_webhook.py                 # estado y webhook actual
    python scripts/twilio_webhook.py --set           # apuntarlo a PUBLIC_BASE_URL/webhook/whatsapp
    python scripts/twilio_webhook.py --set https://otra-url/webhook/whatsapp

Para un sender propio usa la Senders API v2 de Twilio. El sandbox
(+14155238886) no tiene API: su webhook se cambia sólo en la consola.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatsapp_skills.config import get_settings  # noqa: E402
from whatsapp_skills.observability.logging import force_utf8_output  # noqa: E402

SENDERS = "https://messaging.twilio.com/v2/Channels/Senders"
SANDBOX = "+14155238886"
SANDBOX_CONSOLE = "https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn"


def main() -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description="Webhook entrante del número de WhatsApp.")
    parser.add_argument(
        "--set", nargs="?", const="", metavar="URL",
        help="Apuntar el webhook (sin URL: PUBLIC_BASE_URL/webhook/whatsapp)",
    )
    args = parser.parse_args()

    settings = get_settings()
    number = settings.twilio_whatsapp_from.removeprefix("whatsapp:")
    target = args.set or settings.webhook_url

    if number == SANDBOX:
        print(f"{number} es el sandbox: el webhook se configura sólo en la consola.")
        print(f"  {SANDBOX_CONSOLE} → Sandbox settings → 'When a message comes in'")
        print(f"  URL: {target}  ·  método: POST")
        return 0

    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    response = httpx.get(SENDERS, auth=auth, params={"Channel": "whatsapp", "PageSize": 50})
    response.raise_for_status()
    senders = response.json().get("senders", [])
    sender = next((s for s in senders if s.get("sender_id") == f"whatsapp:{number}"), None)
    if sender is None:
        print(f"No encontré un sender de WhatsApp para {number} en esta cuenta.", file=sys.stderr)
        return 1

    current = (sender.get("webhook") or {}).get("callback_url")
    print(f"Sender   : {number} ({sender.get('status')})")
    print(f"Webhook  : {current or '(sin configurar)'}")

    if args.set is None:
        return 0
    if not target.startswith("https://"):
        print(f"La URL tiene que ser https: {target!r}. ¿Falta PUBLIC_BASE_URL?", file=sys.stderr)
        return 1
    if current == target:
        print("Ya apunta ahí. Nada que cambiar.")
        return 0

    response = httpx.post(
        f"{SENDERS}/{sender['sid']}",
        auth=auth,
        json={"webhook": {"callback_url": target, "callback_method": "POST"}},
    )
    response.raise_for_status()
    print(f"Nuevo    : {(response.json().get('webhook') or {}).get('callback_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

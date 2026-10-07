"""Configuración del proceso, leída de .env y validada al arrancar.

La regla acá es fallar temprano y con un mensaje claro. Un agente de WhatsApp
que arranca bien y explota recién cuando entra el primer mensaje real es mucho
peor que uno que se niega a levantar.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env se resuelve contra la raíz del repo, no contra el cwd. El server MCP
# corre en un workspace vacío (aislamiento) y con una ruta relativa no lo
# encontraba: arrancaba sin credenciales, moría, y el agente se quedaba sin
# ninguna tool sin que nadie se enterara.
REPO_ROOT = Path(__file__).resolve().parents[2]

AgentBackendName = Literal["messages_api", "cli"]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Backend ─────────────────────────────────────────────────────────────
    agent_backend: AgentBackendName = "cli"
    agent_max_iterations: int = 8

    # ── Claude / Messages API ───────────────────────────────────────────────
    anthropic_api_key: str = ""
    # ID exacto. Nunca le agregues un sufijo de fecha: los IDs de la tabla de
    # modelos están completos tal cual.
    anthropic_model: str = "claude-opus-5"
    anthropic_effort: EffortLevel = "medium"
    anthropic_max_tokens: int = 8000

    # ── Claude Code / backend cli ───────────────────────────────────────────
    claude_cli_path: str = "claude"
    claude_cli_timeout_s: float = 120.0
    claude_cli_max_budget_usd: float = 0.50
    claude_cli_max_concurrency: int = 4

    # ── Twilio ──────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    public_base_url: str = ""
    twilio_validate_signature: bool = True

    # ── Supabase ────────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # ── Pagos ───────────────────────────────────────────────────────────────
    payment_provider: Literal["stripe"] = "stripe"
    stripe_secret_key: str = ""
    stripe_currency: str = "usd"

    # ── Handoff ─────────────────────────────────────────────────────────────
    handoff_notify_url: str = ""

    # ── CRM ─────────────────────────────────────────────────────────────────
    # Origen del panel, para CORS. En Vercel: https://tu-panel.vercel.app
    crm_panel_origin: str = "http://localhost:5173"

    # ── Resiliencia ─────────────────────────────────────────────────────────
    circuit_breaker_threshold: int = Field(default=3, ge=1)
    circuit_breaker_cooldown_s: float = Field(default=30.0, gt=0)

    # ── Observabilidad ──────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["demo", "json"] = "demo"

    @model_validator(mode="after")
    def _validate_backend_requirements(self) -> Settings:
        missing: list[str] = []

        if self.agent_backend == "messages_api":
            if not self.anthropic_api_key:
                missing.append(
                    "ANTHROPIC_API_KEY es obligatorio con AGENT_BACKEND=messages_api. "
                    "Sacá una key en console.anthropic.com, o pasate a "
                    "AGENT_BACKEND=cli para usar tu suscripción de Claude Code."
                )
        elif self.agent_backend == "cli":
            if shutil.which(self.claude_cli_path) is None:
                missing.append(
                    f"AGENT_BACKEND=cli necesita el ejecutable '{self.claude_cli_path}' "
                    "en el PATH. Instalá Claude Code o ajustá CLAUDE_CLI_PATH."
                )

        if not self.supabase_url or not self.supabase_service_role_key:
            missing.append(
                "SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY son obligatorios: las 5 "
                "skills leen y escriben en Supabase."
            )

        if not self.twilio_account_sid or not self.twilio_auth_token:
            missing.append(
                "TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN son obligatorios para "
                "recibir y responder mensajes."
            )

        if self.twilio_validate_signature and not self.public_base_url:
            missing.append(
                "PUBLIC_BASE_URL es obligatorio mientras TWILIO_VALIDATE_SIGNATURE=true: "
                "la firma de Twilio se calcula sobre la URL pública exacta."
            )

        if missing:
            raise ValueError(
                "Configuración incompleta:\n  - " + "\n  - ".join(missing)
            )
        return self

    @property
    def webhook_url(self) -> str:
        """URL exacta contra la que Twilio firmó el request."""
        return f"{self.public_base_url.rstrip('/')}/webhook/whatsapp"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

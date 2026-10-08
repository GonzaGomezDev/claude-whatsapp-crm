"""La app de FastAPI: arma todo una vez y lo deja en app.state.

Levantar:
    uvicorn whatsapp_skills.main:app --reload --port 8000

Todo lo caro —registry, cliente de Supabase, backend— se
construye en el lifespan, no por request. Si algo está mal configurado, el
proceso no arranca: preferimos un fallo ruidoso al arranque antes que uno
silencioso con el primer cliente real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.backend import AgentBackend
from .agent.claude_cli import ClaudeCLIBackend
from .agent.messages_api import MessagesAPIBackend
from .config import Settings, get_settings
from .crm import router as crm_router
from .integrations.notifications import build_notifier
from .integrations.supabase_client import Database
from .integrations.twilio_client import WhatsAppClient
from .observability.logging import configure_logging, get_logger
from .skills.registry import SkillRegistry
from .webhook import router as webhook_router

log = get_logger(__name__)


def build_backend(settings: Settings, registry: SkillRegistry) -> AgentBackend:
    if settings.agent_backend == "messages_api":
        return MessagesAPIBackend(
            registry,
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            effort=settings.anthropic_effort,
            max_tokens=settings.anthropic_max_tokens,
            max_iterations=settings.agent_max_iterations,
        )

    return ClaudeCLIBackend(
        registry,
        cli_path=settings.claude_cli_path,
        model=settings.anthropic_model,
        effort=settings.anthropic_effort,
        timeout_s=settings.claude_cli_timeout_s,
        max_budget_usd=settings.claude_cli_max_budget_usd,
        max_concurrency=settings.claude_cli_max_concurrency,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    registry = SkillRegistry(
        breaker_threshold=settings.circuit_breaker_threshold,
        breaker_cooldown_s=settings.circuit_breaker_cooldown_s,
    )

    app.state.settings = settings
    app.state.registry = registry
    app.state.db = Database(settings.supabase_url, settings.supabase_service_role_key)
    app.state.whatsapp = WhatsAppClient(
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_whatsapp_from,
    )
    app.state.notifier = build_notifier(settings, app.state.whatsapp)
    app.state.backend = build_backend(settings, registry)

    log.info(
        "startup",
        backend=app.state.backend.name,
        model=settings.anthropic_model,
        notificaciones=app.state.notifier.name,
        skills=len(registry.docs),
        tools=len(registry.tools),
        webhook=settings.webhook_url or "(sin PUBLIC_BASE_URL)",
    )
    yield
    log.info("shutdown")


app = FastAPI(
    title="claude-whatsapp-skills",
    description="Agente de WhatsApp sobre Claude Agent Skills.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(webhook_router)
app.include_router(crm_router)


class PanelCORS(CORSMiddleware):
    """CORS para el panel. Lee el origen al construir el stack (al arrancar), no
    al importar: la configuración se valida en el arranque, como el resto."""

    def __init__(self, app: Any) -> None:
        super().__init__(
            app,
            allow_origins=[get_settings().crm_panel_origin],
            allow_methods=["POST"],
            allow_headers=["*"],
        )


app.add_middleware(PanelCORS)

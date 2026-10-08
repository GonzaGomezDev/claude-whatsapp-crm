"""El contrato que los dos backends tienen que cumplir por igual.

Si divergen, todo el argumento del repo —la Skill no cambia, cambia el backend—
deja de ser cierto. Estos tests son la barandilla.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from whatsapp_skills.agent.backend import AgentBackend, AgentResult, Conversation, Usage
from whatsapp_skills.agent.claude_cli import (
    BLOCKED_BUILTINS,
    MCP_SERVER_NAME,
    ClaudeCLIBackend,
    _usage_from,
)
from whatsapp_skills.agent.mcp_server import _build_signature, build_server
from whatsapp_skills.agent.messages_api import MessagesAPIBackend
from whatsapp_skills.agent.prompt import cli_system_prompt, system_blocks
from whatsapp_skills.skills.base import SkillContext
from whatsapp_skills.skills.registry import repo_root


@pytest.fixture
def convo() -> Conversation:
    return Conversation(phone="+5491123456789", message="Hola, necesito una cotización")


# ── El Protocol ─────────────────────────────────────────────────────────────


def test_los_dos_backends_cumplen_el_protocol(registry):
    cli = ClaudeCLIBackend(registry)
    api = MessagesAPIBackend(registry, api_key="sk-test-noop")
    assert isinstance(cli, AgentBackend)
    assert isinstance(api, AgentBackend)
    assert {cli.name, api.name} == {"cli", "messages_api"}


# ── Conversation -> messages ────────────────────────────────────────────────


def test_una_conversacion_vacia_produce_un_solo_turno_user(convo):
    messages = convo.as_messages()
    assert messages == [{"role": "user", "content": "Hola, necesito una cotización"}]


def test_los_roles_alternan_siempre():
    """La API rechaza dos turnos seguidos del mismo rol."""
    convo = Conversation(
        phone="+549",
        message="y otra cosa",
        history=[
            {"direction": "inbound", "body": "hola"},
            {"direction": "inbound", "body": "estás?"},
            {"direction": "outbound", "body": "hola!"},
            {"direction": "outbound", "body": "decime"},
            {"direction": "inbound", "body": "quiero precios"},
        ],
    )
    roles = [m["role"] for m in convo.as_messages()]
    assert roles == ["user", "assistant", "user"]
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False))


def test_el_mensaje_nuevo_se_funde_con_el_ultimo_turno_user():
    convo = Conversation(
        phone="+549",
        message="segundo",
        history=[{"direction": "inbound", "body": "primero"}],
    )
    messages = convo.as_messages()
    assert len(messages) == 1
    assert messages[0]["content"] == "primero\nsegundo"


def test_el_primer_mensaje_siempre_es_del_usuario():
    """La API devuelve 400 si el historial arranca con un turno del asistente.

    Pasa de verdad: los entrantes se grababan con client_id NULL, así que
    `recent_messages` sólo devolvía las respuestas del agente. También puede
    pasar legítimamente si el equipo escribe primero desde scripts/inbox.py.
    """
    convo = Conversation(
        phone="+549",
        message="¿me confirmás el precio?",
        history=[
            {"direction": "outbound", "body": "Hola, te paso la cotización."},
            {"direction": "outbound", "body": "USD 9.60 la unidad."},
        ],
    )
    messages = convo.as_messages()
    assert messages[0]["role"] == "user"
    assert messages == [{"role": "user", "content": "¿me confirmás el precio?"}]


def test_un_historial_que_arranca_con_el_agente_se_recorta():
    convo = Conversation(
        phone="+549",
        message="dale",
        history=[
            {"direction": "outbound", "body": "Hola, ¿seguís interesado?"},
            {"direction": "inbound", "body": "sí"},
            {"direction": "outbound", "body": "Genial."},
        ],
    )
    roles = [m["role"] for m in convo.as_messages()]
    assert roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False))


def test_los_mensajes_vacios_del_historial_se_descartan():
    convo = Conversation(
        phone="+549",
        message="hola",
        history=[{"direction": "outbound", "body": "   "}],
    )
    assert convo.as_messages() == [{"role": "user", "content": "hola"}]


# ── System prompt ───────────────────────────────────────────────────────────


def test_el_breakpoint_de_cache_va_al_final_del_bloque_estatico(registry, convo):
    blocks = system_blocks(registry.system_prompt_block(), convo)
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_el_bloque_estatico_no_depende_de_la_conversacion(registry):
    """Si el teléfono se cuela en el prefijo, el cache hit rate se va a cero."""
    a = system_blocks(registry.system_prompt_block(), Conversation(phone="+111", message="x"))
    b = system_blocks(registry.system_prompt_block(), Conversation(phone="+222", message="y"))
    assert a[0]["text"] == b[0]["text"]
    assert a[1]["text"] != b[1]["text"]


def test_los_tickets_abiertos_van_en_el_bloque_dinamico(registry):
    """Los datos varían por conversación: en el prefijo cacheado lo tirarían abajo."""
    convo = Conversation(
        phone="+549",
        message="cuál es la lista de precios?",
        open_tickets=[{"ref": 4001, "type": "quotation", "status": "open"}],
    )
    estatico, dinamico = system_blocks(registry.system_prompt_block(), convo)
    assert "4001" in dinamico["text"]
    assert "4001" not in estatico["text"]


def test_la_regla_de_no_derivar_al_ticket_va_en_el_bloque_cacheado(registry, convo):
    """Regresión de un bug de comportamiento real.

    Con un ticket abierto en contexto, el agente contestaba "eso ya está cargado
    en el ticket 4001" y ni buscaba en la knowledge base. La regla que lo corrige
    es fija, así que va en el prefijo estático y se paga una sola vez.
    """
    estatico, _ = system_blocks(registry.system_prompt_block(), convo)
    texto = estatico["text"].lower()
    assert "un ticket abierto no es una respuesta" in texto
    assert "buscá igual" in texto


def test_los_dos_backends_usan_el_mismo_texto_de_skills(registry, convo):
    """Divergir acá haría que el agente se comporte distinto según el backend."""
    bloque = registry.system_prompt_block()
    plano = cli_system_prompt(bloque, convo)
    partido = system_blocks(bloque, convo)
    assert partido[0]["text"] in plano
    assert partido[1]["text"] in plano


# ── Paridad de tools ────────────────────────────────────────────────────────


async def test_los_dos_backends_exponen_exactamente_las_mismas_tools(registry):
    api_names = {t["name"] for t in registry.anthropic_tools("full")}
    mcp_tools = await build_server(
        registry, SkillContext(phone="+549", settings=None)
    ).list_tools()
    assert api_names == {t.name for t in mcp_tools}


async def test_los_schemas_mcp_conservan_required_y_enum(registry):
    mcp_tools = await build_server(
        registry, SkillContext(phone="+549", settings=None)
    ).list_tools()
    por_nombre = {t.name: t.input_schema for t in mcp_tools}

    for tool in registry.tools.values():
        origen = tool.input_schema
        destino = por_nombre[tool.name]
        assert set(destino.get("properties", {})) == set(origen.get("properties", {})), tool.name
        assert set(destino.get("required", [])) == set(origen.get("required", [])), tool.name

        for prop, spec in origen.get("properties", {}).items():
            if "enum" in spec:
                assert destino["properties"][prop].get("enum") == spec["enum"], (
                    f"{tool.name}.{prop}: se perdió el enum al pasar a MCP"
                )


def test_los_obligatorios_van_antes_que_los_opcionales_en_la_firma():
    """Python no acepta un parámetro sin default después de uno con default."""
    signature, _ = _build_signature(
        {
            "type": "object",
            "properties": {
                "opcional": {"type": "string"},
                "obligatorio": {"type": "string"},
            },
            "required": ["obligatorio"],
            "additionalProperties": False,
        }
    )
    nombres = list(signature.parameters)
    assert nombres.index("obligatorio") < nombres.index("opcional")


def test_un_tipo_json_schema_no_soportado_falla_al_arrancar():
    with pytest.raises(ValueError, match="no soportado"):
        _build_signature(
            {
                "type": "object",
                "properties": {"x": {"type": "cualquier-cosa"}},
                "required": ["x"],
                "additionalProperties": False,
            }
        )


# ── El backend cli ──────────────────────────────────────────────────────────


def test_el_argv_del_cli_aisla_al_agente(registry, convo):
    argv = ClaudeCLIBackend(registry)._build_argv(convo, resume=None)

    assert "--print" in argv
    # stream-json es lo que deja ver los tool_use mientras pasan. Volver a
    # "json" deja el modo cli sin observabilidad.
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    # Sin --strict-mcp-config el agente vería servers MCP del usuario que en
    # producción no existen.
    assert "--strict-mcp-config" in argv

    permitidas = argv[argv.index("--allowedTools") + 1].split(",")
    assert set(permitidas) == {f"mcp__{MCP_SERVER_NAME}__{n}" for n in registry.tools}

    bloqueadas = argv[argv.index("--disallowedTools") + 1].split(",")
    assert set(bloqueadas) == set(BLOCKED_BUILTINS)

    assert argv[-1] == convo.message


# ── Aislamiento: un mensaje de WhatsApp es input no confiable ───────────────

# Las 23 tools built-in que Claude Code exponía de verdad en una corrida real,
# a pesar de que --allowedTools sólo listaba las del MCP. Con --permission-mode
# dontAsk, allowedTools pre-aprueba pero NO restringe.
BUILTINS_OBSERVADAS = [
    "CronCreate", "CronDelete", "CronList", "DesignSync", "EnterWorktree",
    "ExitWorktree", "Glob", "Grep", "ListMcpResourcesTool", "Monitor",
    "PushNotification", "Read", "ReadMcpResourceDirTool", "ReadMcpResourceTool",
    "RemoteTrigger", "ReportFindings", "ScheduleWakeup", "SendMessage", "Skill",
    "TaskOutput", "TaskStop", "ToolSearch", "Workflow",
]


@pytest.mark.parametrize("tool", BUILTINS_OBSERVADAS)
def test_toda_builtin_observada_esta_bloqueada(tool):
    """Regresión de una vulnerabilidad real.

    Con Read/Glob/Grep disponibles y cwd en la raíz del repo, un mensaje de
    WhatsApp con prompt injection podía hacer que el agente leyera .env y
    devolviera las credenciales de Twilio, Supabase y Stripe por chat.
    """
    assert tool in BLOCKED_BUILTINS


@pytest.mark.parametrize(
    "tool", ["Read", "Glob", "Grep", "Bash", "WebFetch", "SendMessage", "CronCreate"]
)
def test_las_tools_mas_peligrosas_estan_bloqueadas(tool):
    assert tool in BLOCKED_BUILTINS


def test_el_subproceso_no_corre_dentro_del_repo(registry):
    """Segunda capa: aunque una tool de lectura se filtre, no hay nada que leer."""
    backend = ClaudeCLIBackend(registry)
    try:
        workspace = backend._workspace
        assert workspace.is_dir()
        assert list(workspace.iterdir()) == [], "el workspace tiene que estar vacío"
        assert repo_root() not in workspace.parents
        assert workspace != repo_root()
    finally:
        backend.close()


def test_detecta_una_tool_que_no_declaramos(registry):
    """Una deny list a mano se pudre cuando Claude Code agrega tools.

    Esto convierte esa degradación silenciosa en algo observable.
    """
    backend = ClaudeCLIBackend(registry)
    try:
        extra = backend._assert_tool_surface(
            [f"mcp__{MCP_SERVER_NAME}__find_client", "UnaToolNueva", "Read"]
        )
        assert extra == ["Read", "UnaToolNueva"]
    finally:
        backend.close()


def test_no_alerta_cuando_la_superficie_es_la_esperada(registry):
    backend = ClaudeCLIBackend(registry)
    try:
        assert backend._assert_tool_surface(sorted(backend._expected_tools)) == []
    finally:
        backend.close()


# ── Parseo del stream ───────────────────────────────────────────────────────


def _stream(*events: dict[str, Any]) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for event in events:
        reader.feed_data((json.dumps(event) + "\n").encode())
    reader.feed_eof()
    return reader


async def test_el_stream_recupera_las_tool_calls_reales(registry):
    """Con --output-format json el transcript no venía y tool_calls quedaba vacío.

    Eso significaba que no había forma de saber si el agente creó el ticket que
    le dijo al cliente, o si se lo inventó.
    """
    backend = ClaudeCLIBackend(registry)
    try:
        payload, calls = await backend._consume_stream(
            _stream(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_1",
                                "name": f"mcp__{MCP_SERVER_NAME}__create_ticket",
                                "input": {"client_id": "abc", "type": "quotation"},
                            }
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu_1",
                                "content": '{"ticket_ref": 4001}',
                            }
                        ]
                    },
                },
                {"type": "result", "result": "Listo", "session_id": "s1", "num_turns": 2},
            )
        )
    finally:
        backend.close()

    assert payload["result"] == "Listo"
    assert [c.name for c in calls] == ["create_ticket"]  # sin el prefijo mcp__
    assert calls[0].is_error is False
    assert calls[0].input["type"] == "quotation"


async def test_un_tool_result_con_error_queda_marcado(registry):
    backend = ClaudeCLIBackend(registry)
    try:
        _, calls = await backend._consume_stream(
            _stream(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_1",
                                "name": f"mcp__{MCP_SERVER_NAME}__find_client",
                                "input": {},
                            }
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu_1",
                                "is_error": True,
                                "content": "timeout",
                            }
                        ]
                    },
                },
                {"type": "result", "result": "hubo un problema"},
            )
        )
    finally:
        backend.close()

    assert calls[0].is_error is True


async def test_las_lineas_que_no_son_json_no_rompen_el_parseo(registry):
    """Claude Code puede escribir ruido en stdout; no es motivo para perder el turno."""
    backend = ClaudeCLIBackend(registry)
    try:
        reader = asyncio.StreamReader()
        reader.feed_data(b"esto no es json\n")
        reader.feed_data(json.dumps({"type": "result", "result": "ok"}).encode() + b"\n")
        reader.feed_eof()
        payload, calls = await backend._consume_stream(reader)
    finally:
        backend.close()

    assert payload["result"] == "ok"
    assert calls == []


def test_el_resume_solo_aparece_si_hay_session_id(registry, convo):
    backend = ClaudeCLIBackend(registry)
    assert "--resume" not in backend._build_argv(convo, resume=None)

    argv = backend._build_argv(convo, resume="abc-123")
    assert argv[argv.index("--resume") + 1] == "abc-123"


def test_la_config_mcp_apunta_al_server_del_repo(registry):
    config = ClaudeCLIBackend(registry)._mcp_config()
    server = config["mcpServers"][MCP_SERVER_NAME]
    assert server["args"] == ["-m", "whatsapp_skills.agent.mcp_server"]
    assert "src" in server["env"]["PYTHONPATH"]
    json.dumps(config)  # tiene que serializar: va como argumento de línea de comandos


def test_el_usage_del_cli_reporta_costo():
    usage = _usage_from({"usage": {"input_tokens": 100}, "total_cost_usd": 0.0123})
    assert usage.input_tokens == 100
    assert usage.cost_usd == 0.0123
    # Lo que el CLI no expone queda en None. Rellenarlo con ceros haría que las
    # métricas mientan.
    assert usage.output_tokens is None


def test_agent_result_expone_las_tools_usadas():
    result = AgentResult(reply_text="ok", usage=Usage())
    assert result.used_tools == []


# ── complete(): texto sin tools para el CRM ─────────────────────────────────


def test_complete_del_cli_no_tiene_tools_ni_mcp(registry):
    """complete() recibe historial de clientes: input no confiable. Tiene que
    quedar tan cerrado como run(), o más."""
    argv = ClaudeCLIBackend(registry)._complete_argv("sistema")

    assert argv[argv.index("--tools") + 1] == ""
    assert set(argv[argv.index("--disallowedTools") + 1].split(",")) == set(BLOCKED_BUILTINS)
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert "--strict-mcp-config" in argv
    assert "--allowedTools" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"


async def test_complete_de_la_api_no_manda_tools(registry):
    api = MessagesAPIBackend(registry, api_key="sk-test-noop")
    sent: dict[str, Any] = {}

    class Response:
        stop_reason = "end_turn"
        content = [type("Block", (), {"type": "text", "text": "Resumen."})()]

    async def fake_create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        return Response()

    api._create = fake_create  # type: ignore[method-assign]
    assert await api.complete("sistema", "historial") == "Resumen."
    assert "tools" not in sent
    assert sent["messages"] == [{"role": "user", "content": "historial"}]

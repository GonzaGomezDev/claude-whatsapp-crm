# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Este repo

Un CRM para WhatsApp construido arriba de un agente de atención con Claude Agent Skills. El agente
viene de `GonzaGomezDev/claude-whatsapp-chatbot-skills@86997cf` (copiado, no es dependencia) y el CRM
se construye encima. Todo lo que sigue a la línea divisoria describe el agente.

### Cómo funciona el CRM

- `conversations` (una fila por teléfono) guarda `status`: `bot`, `needs_human` (lo marca
  `escalate_to_human`; el bot sigue contestando) o `human` (el bot no contesta). El estado vive en la
  base porque el que lo lee es el webhook.
- `webhook._process` lee el estado antes del router y del agente, y otra vez justo antes de enviar
  (`_still_bot`): el agente tarda segundos y el operador puede tomar el chat en ese medio.
- `messages.phone` existe para que la bandeja muestre números que todavía no son clientes.
- El panel (`web/`) sólo lee, con la anon key y RLS restringida a la tabla `operators`. Tomar, devolver
  y responder pasan por `crm.py` (JWT de Supabase Auth → operador). Twilio y la service key nunca
  llegan al navegador.
- Al devolver el chat, la nota del operador (`handoff_note`) entra en `prompt.dynamic_context`, después
  del breakpoint de cache.
- `window.py` es la ventana de 24 h, compartida por `crm.py` y `scripts/inbox.py`.

### Restricciones

- API oficial de WhatsApp vía Twilio. Nada de APIs no oficiales ni Chatwoot.
- El panel se despliega en Vercel leyendo Supabase; sin VPS para el panel. El agente sigue donde ya corre.
- La service key de Supabase nunca llega al navegador. El panel tiene login (son chats de clientes).
- Los mensajes salientes se mandan por Twilio desde el servidor, nunca desde el navegador.
- Fuera de la ventana de 24 h solo se pueden mandar templates.

---

A WhatsApp customer-service agent built on Claude Agent Skills. Python 3.11+,
FastAPI, Anthropic SDK, Supabase, Twilio.

## Repo map

```
skills/<name>/SKILL.md    Agent Skill frontmatter + the guide body (loaded on demand)
skills/<name>/tools.py    @skill_tool functions — the actual implementations
src/whatsapp_skills/
  config.py               pydantic-settings; validates per-backend requirements at boot
  main.py                 FastAPI app; builds everything once in the lifespan
  webhook.py              Layer 1 (Twilio inbound) + Layer 5 (reply)
  router.py               Layer 2 — decides what never reaches the model
  context.py              Layer 3 — client + last 10 messages + open tickets
  agent/backend.py        AgentBackend Protocol, Conversation, AgentResult
  agent/messages_api.py   Production backend: manual agentic loop
  agent/claude_cli.py     Dev backend: `claude -p` subprocess
  agent/mcp_server.py     Exposes the registry over MCP stdio for the CLI backend
  agent/prompt.py         System prompt, split at the cache breakpoint
  skills/registry.py      Discovery + the single dispatch path
  skills/base.py          @skill_tool decorator, SkillTool, SkillContext
  skills/loader.py        SKILL.md frontmatter parser
  resilience/             Circuit breaker + per-tool token bucket
  integrations/           Supabase, Twilio, handoff notifications
  observability/          structlog; the "demo" renderer is the on-camera format
supabase/schema.sql       Idempotent; paste into the Supabase SQL editor
scripts/measure_tokens.py Compares tool-exposure strategies with count_tokens
scripts/sync_skills.py    Copies skills/ -> .claude/skills/ for Claude Code
```

## Commands

```bash
pytest                              # no credentials needed
ruff check .
python scripts/sync_skills.py       # after editing any SKILL.md
uvicorn whatsapp_skills.main:app --reload --port 8000
cd web && npm run dev                # panel; needs web/.env (see web/.env.example)
cd web && npm run build              # type-check + build (Vercel root dir: web/)
```

`tests/test_resilience.py::test_half_open_deja_pasar_una_sola_sonda` is timing-dependent and
occasionally flakes; rerun before debugging it.

## Non-negotiable rules

### Model configuration

- The model ID is `claude-opus-5`. It is complete as written — **never append a
  date suffix**.
- Use `thinking: {"type": "adaptive"}`. `budget_tokens` is removed on Opus 5 and
  returns a 400.
- Effort goes inside `output_config`, not at the top level:
  `output_config={"effort": "medium"}`. Not a top-level `effort=` kwarg.
- Assistant prefills return a 400 on Opus 5. Use `output_config.format` or
  system-prompt instructions to shape output.
- Check `stop_reason` **before** reading `content`. `stop_details` is populated
  only when `stop_reason == "refusal"` — guard before reading it.

### The tool_result rule

One assistant message can carry several `tool_use` blocks. Execute them
concurrently and return **all** `tool_result` blocks in a **single** user
message. Splitting them across messages teaches the model to stop parallelising.

A tool that failed still gets a `tool_result`, with `is_error: True`. Dropping
one leaves a `tool_use` unanswered and the API rejects the next request.

### Prompt caching

Render order is `tools` → `system` → `messages`. The `cache_control` breakpoint
sits at the end of the static system block in `agent/prompt.py`. Anything that
varies per conversation goes **after** it.

`registry.system_prompt_block()` and `anthropic_tools()` are sorted
alphabetically on purpose. Reordering them changes the prefix and silently
invalidates the cache — the API does not warn, it just bills full input.

### Everything executes through registry.dispatch

Both backends route tool execution through `SkillRegistry.dispatch`. That is
where timeout, circuit breaker, rate limiting and latency logging live. Do not
add a second execution path — if the two backends diverge, the repo's central
claim stops being true, and `tests/test_backend_contract.py` will fail.

### Why a manual loop instead of the SDK Tool Runner

`@beta_tool` derives schemas from function signatures and gives no place to set
`defer_loading`, per-tool timeouts, circuit breaking, rate limiting, or latency
logging. The whole error-handling story depends on that hook. If you ever
migrate to the Tool Runner, you lose `defer_loading` on custom tools.

## Adding a skill

1. `skills/<kebab-name>/SKILL.md` — frontmatter `name` (must equal the directory
   name, kebab-case) and `description` (≥40 chars; it is the only thing Claude
   always sees). Use a `>-` block scalar: descriptions contain colons, and plain
   YAML scalars break on `: `.
2. `skills/<kebab-name>/tools.py` — `@skill_tool`-decorated `async` functions
   taking `ctx: SkillContext` first.
3. Run `pytest`. The registry auto-discovers; nothing else to register.

Schema requirements when `strict=True` (the default): `additionalProperties:
False` plus a `required` list, or the API rejects the tool. Every property needs
a `description` — `tests/` does not enforce it but the MCP bridge surfaces it and
the model uses it.

Keep tool descriptions to one line. Long prose belongs in `SKILL.md`, which is
loaded on demand via `load_skill_guide` — that is the whole point of the
progressive-disclosure design.

### CLI-backend isolation (security invariant)

A WhatsApp message is untrusted input from anyone who knows the number.
`--allowedTools` is **not** an exclusive allowlist — under `--permission-mode
dontAsk` it pre-approves but does not restrict. A real run exposed 23 Claude Code
built-ins (`Read`, `Glob`, `Grep`, `Bash`, `WebFetch`, `CronCreate`,
`SendMessage`, …) alongside the MCP tools, with `cwd` at the repo root — where
`.env` holds live Twilio/Supabase credentials.

Three layers keep it closed; do not remove any of them:

1. `BLOCKED_BUILTINS` in `agent/claude_cli.py` — explicit deny. Deny wins.
2. The subprocess runs in an empty temp dir, never the repo.
3. `_assert_tool_surface` compares the stream's `system` init event against the
   expected set and logs an error on anything unexpected, because a hand-written
   deny list rots as Claude Code adds tools.

`tests/test_backend_contract.py` pins every observed built-in. When Claude Code
ships a new tool, add it to `BLOCKED_BUILTINS` and to `BUILTINS_OBSERVADAS`.

Also: `--output-format` must stay `stream-json` (with `--verbose`). Plain `json`
omits the transcript, which means no tool-call logs and no way to tell whether
the agent actually created the ticket it told the customer about.

## Things that will bite you

- `skills/` is deliberately **not** a Python package. It gets copied verbatim to
  `.claude/skills/`, where an `__init__.py` would be noise. The registry imports
  each `tools.py` with `importlib.util.spec_from_file_location`.
- The MCP server must log to **stderr**. stdout is the JSON-RPC transport; one
  stray line kills the session.
- Tool names are global across skills. The decorator raises on collision.
- `mcp_server._build_signature` synthesises Python signatures from JSON Schema.
  Required params must come first — Python forbids a non-default parameter after
  a defaulted one. `enum`/`minimum`/`maximum` ride along via
  `json_schema_extra`; dropping that would silently break parity between the two
  backends.
- The Twilio signature is computed over `PUBLIC_BASE_URL`, not the URL FastAPI
  sees behind the tunnel.
- `messages.twilio_sid` has a unique index. That is the idempotency key, not a
  nicety — Twilio retries on any non-2xx.

## What not to do

- Do not mock the integrations. This repo talks to real Twilio and Supabase
  by design; the owner chose that explicitly.
- Do not change the `demo` log renderer's output format. It is what appears
  on camera in the accompanying video.
- Do not add `budget_tokens`, date-suffixed model IDs, or assistant prefills.
- Do not let the two backends drift apart.

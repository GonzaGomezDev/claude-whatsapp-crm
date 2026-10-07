# claude-whatsapp-skills

Un agente de WhatsApp construido sobre **Claude Agent Skills**: cinco skills
coordinadas —clientes, tickets, knowledge base, pagos y escalado a humano— con
circuit breaker, rate limiting por tool y logging estructurado.

No es un prototipo. Es la estructura que necesitás cuando el agente tiene que
seguir respondiendo aunque Supabase se ponga lento, aunque entren cincuenta
mensajes juntos y aunque una skill se caiga.

```
[12:49:34 PM] Message from +5491123456789: "Hola, soy Juan Pérez, necesito una cotización para 500 unidades de X"
[12:49:34 PM] Running Claude (messages_api) with 5 Skills
[12:49:35 PM] Claude calling: find_client("+5491123456789")
[12:49:35 PM] Result: { found: false }  (287ms · breaker=closed)
[12:49:36 PM] Claude calling: create_client("+5491123456789", "Juan Pérez", null)
[12:49:36 PM] Claude calling: knowledge_search("cotización producto X unidades", 5)
[12:49:36 PM] Result: { count: 2, top_confidence: 0.412, ... }  (194ms · breaker=closed)
[12:49:37 PM] Claude calling: create_ticket(..., "quotation", "normal", ...)
[12:49:39 PM] Claude response: "Hola Juan, ..."  (in=4821 · out=180 · cache_read=3902)
```

---

## Antes que nada: Tools vs Skills, sin marketing

Vas a leer en muchos lados que "empaquetar cinco tools en una skill baja el
token overhead". Dicho así, es falso. Agrupar archivos en carpetas no cambia
nada de lo que se manda por la red.

Lo que **sí** baja el costo son dos cosas concretas, y este repo hace las dos:

1. **Sacar la prosa de los schemas.** Las descripciones de las tools se pagan en
   cada request. Las guías largas —cuándo usar cada tool, en qué orden, qué
   hacer si falla— van en el `SKILL.md`, que se carga a demanda con la tool
   `load_skill_guide`. Eso es *progressive disclosure*, y es de lo que hablan de
   verdad los Agent Skills.

2. **Diferir las definiciones.** Con `defer_loading: true` más el server tool
   `tool_search`, Claude descubre las tools que necesita en vez de recibirlas
   todas de entrada.

Y como son afirmaciones sobre tokens, se miden:

```bash
python scripts/measure_tokens.py
```

Compara cuatro configuraciones con `count_tokens` sobre el mismo mensaje y te
imprime la diferencia. Corrélo antes de creerle a nadie —incluido este README.

> Con 12 tools el ahorro por diferir todavía es moderado. La brecha crece con el
> tamaño del tool set: a las 40 o 50 tools es la diferencia entre que entre o no
> entre en presupuesto.

Lo que las Skills sí te dan desde el minuto cero, sin discusión: **separación de
responsabilidades**. Cada skill tiene su dominio, su manejo de errores y su
presupuesto de rate limit. Cuando una se cae, las otras cuatro siguen.

---

## Arquitectura

```
  WhatsApp
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Capa 1  webhook.py     Twilio entrante + validación de firma │
│                        Responde 200, trabaja aparte         │
├─────────────────────────────────────────────────────────────┤
│ Capa 2  router.py      ¿esto necesita el modelo? (µs)        │
├─────────────────────────────────────────────────────────────┤
│ Capa 3  context.py     Cliente + últimos 10 msgs + tickets   │
├─────────────────────────────────────────────────────────────┤
│ Capa 4  agent/         AgentBackend                          │
│                          ├─ messages_api.py  (producción)    │
│                          └─ claude_cli.py    (dev local)     │
│                        ambos → skills/registry.dispatch      │
├─────────────────────────────────────────────────────────────┤
│ Capa 5  twilio_client  Respuesta de vuelta por la REST API   │
├─────────────────────────────────────────────────────────────┤
│ Capa 6  observability  Latencia, breaker, tokens, errores    │
└─────────────────────────────────────────────────────────────┘
```

Detalles de cada capa y por qué está donde está: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

### Las 5 skills

| Skill | Tools | Qué resuelve |
|---|---|---|
| `client-management` | `find_client`, `create_client`, `update_client` | Quién está escribiendo |
| `ticketing` | `create_ticket`, `find_open_tickets`, `update_ticket_status` | Lo que el equipo tiene que hacer |
| `knowledge` | `knowledge_search` | Precios, plazos, políticas |
| `payments` | `create_payment_link`, `check_payment_status`, `confirm_payment` | Cobrar |
| `human-handoff` | `escalate_to_human` | La salida de emergencia |

Más la tool built-in `load_skill_guide`. Total: **12 tools**.

Cada skill es una carpeta con el formato real de Agent Skills:

```
skills/knowledge/
├── SKILL.md    ← frontmatter (name, description) + la guía
└── tools.py    ← las funciones, con @skill_tool
```

El `SKILL.md` es el formato que lee Claude Code. Corré `python scripts/sync_skills.py`
y las mismas cinco carpetas funcionan como skills nativas en tu editor.

---

## Los dos backends

El agente habla con Claude a través de un `Protocol`. Hay dos implementaciones, y
las dos ejecutan las tools por el **mismo** `registry.dispatch` —mismo timeout,
mismo circuit breaker, mismo rate limiter, mismos logs.

```python
class AgentBackend(Protocol):
    async def run(self, convo: Conversation, ctx: SkillContext) -> AgentResult: ...
```

| | `messages_api` | `cli` |
|---|---|---|
| Cómo llama a Claude | Messages API, loop agéntico manual | subproceso `claude -p` |
| Credenciales | `ANTHROPIC_API_KEY` | tu suscripción de Claude Code |
| `defer_loading` / `tool_search` | sí | no (el loop lo maneja Claude Code) |
| `count_tokens` | sí | no |
| Prompt caching controlado | sí | no |
| Arranque por mensaje | ~0 | 1–3 s (subproceso) |
| Para qué sirve | **producción y grabar** | **iterar sobre los SKILL.md gratis** |

Se cambia con una variable de entorno:

```bash
AGENT_BACKEND=cli           # desarrollo, sin API key
AGENT_BACKEND=messages_api  # producción
```

El modo `cli` expone las tools a Claude Code por un server MCP
(`src/whatsapp_skills/agent/mcp_server.py`) que recorre el mismo registry. Las
firmas de Python se sintetizan desde los JSON Schema, así que **no hay
definiciones duplicadas**: el registry es la única fuente de verdad, y los tests
verifican que los dos backends expongan exactamente las mismas tools con los
mismos `required` y `enum`.

### Aislamiento del backend `cli`

Un mensaje de WhatsApp es input **no confiable**: lo manda cualquiera que tenga
el número. Claude Code trae ~23 tools propias (`Read`, `Glob`, `Grep`, `Bash`,
`WebFetch`, `CronCreate`, `SendMessage`…) y **`--allowedTools` no es una lista
exclusiva**: con `--permission-mode dontAsk` sólo pre-aprueba, no restringe.

Sin cerrar eso, un agente corriendo con `cwd` en la raíz del repo puede leer tu
`.env`. Tres capas lo evitan:

1. `BLOCKED_BUILTINS` — deny explícito de todas las built-in. El deny gana.
2. El subproceso corre en un **directorio temporal vacío**, no en el repo.
3. El evento `system` del stream declara qué tools quedaron activas; si aparece
   una que no declaramos, se loguea como error. Una deny list a mano se pudre
   cuando Claude Code agrega tools — esto hace que te enteres el mismo día.

Verificado: la superficie pasó de 35 tools a 12, todas del MCP.

Si en tus logs ves `unexpected_tools_available` o `mcp_server_failed`, paralo y
mirá eso antes que nada: el primero es un agujero de seguridad, el segundo
significa que el agente está respondiendo **sin ninguna tool**.

---

## Setup

Necesitás cuentas en Supabase, Twilio y Stripe. Con `AGENT_BACKEND=cli` no
necesitás API key de Anthropic.

### 1. Instalar

```bash
git clone <este-repo> && cd claude-whatsapp-skills
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Supabase

Creá un proyecto, abrí el **SQL Editor** y pegá `supabase/schema.sql` entero.
Crea las seis tablas, la función de búsqueda `search_knowledge` y tres documentos
de ejemplo en la knowledge base.

En *Settings → API* copiá la URL y la **`service_role`** key (no la `anon`: el
agente escribe en tablas con RLS activo).

```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
```

### 3. Twilio

Activá el [WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn)
y mandá el código de unión desde tu teléfono.

```bash
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

### 4. Stripe

`sk_test_...` de [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys).

### 5. Exponer el webhook

```bash
python scripts/sync_skills.py            # sólo si vas a usar AGENT_BACKEND=cli
uvicorn whatsapp_skills.main:app --port 8000
ngrok http 8000                          # en otra terminal
```

Poné la URL de ngrok en `PUBLIC_BASE_URL` y configurá el webhook del sandbox de
Twilio apuntando a `https://<tu-ngrok>.ngrok-free.app/webhook/whatsapp`.

> La firma de Twilio se calcula sobre la **URL pública exacta**. Si te da 403 en
> todos los mensajes, es casi seguro que `PUBLIC_BASE_URL` no coincide con lo que
> configuraste en Twilio: `http` vs `https`, barra final de más, o un subdominio
> de ngrok viejo.

### 6. Probar

Escribile al número del sandbox desde tu WhatsApp. Mirá los logs.

[`docs/MENSAJES-DE-PRUEBA.md`](docs/MENSAJES-DE-PRUEBA.md) tiene un guion con
mensajes concretos para cada flujo —router, alta de cliente, los tres casos de
la knowledge base, dedupe de tickets, escalado, rate limit y circuit breaker—
con lo que tenés que ver en los logs y el SQL para verificarlo.

### Recibir los escalados

Cuando el agente escala, el registro queda en `escalations` y el aviso sale a
donde apunte `HANDOFF_NOTIFY_URL`. El destino se deduce de la URL:

| Poné esto | Va a | Setup |
|---|---|---|
| `https://ntfy.sh/un-topico-largo-y-random` | push al teléfono | **~2 min, sin cuenta** |
| `whatsapp:+5491112345678` | tu propio WhatsApp | ya lo tenés |
| `https://hooks.slack.com/services/...` | Slack | Incoming Webhook |
| `https://discord.com/api/webhooks/...` | Discord | Ajustes → Integraciones |
| `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>` | Telegram | @BotFather |
| cualquier otra URL | tu webhook (n8n, Make) | recibe `{"text": ...}` |
| vacío | sólo los logs y la tabla | — |

**Si no tenés nada armado, usá ntfy.** No pide registro: elegís un nombre de
tópico, lo ponés en el `.env`, instalás la app y te suscribís. Los tópicos son
públicos, así que usá un nombre largo y difícil de adivinar.

**Para el video, WhatsApp es más lindo:** el escalado te llega al mismo teléfono
desde el que estás probando, y se ve en cámara sin cambiar de ventana. La contra
es la ventana de 24 h — tenés que haberle escrito al bot ese día.

Notificar es best-effort: el escalado se guarda en la base **antes** de avisar.
Si Slack está caído, el escalado no se pierde.

### Contestar y cerrar tickets

El agente crea tickets y escala a un humano. `scripts/inbox.py` es la vuelta de
ese circuito: sin esto, el equipo no tiene forma de responderle al cliente ni de
cerrar nada, y la cola crece para siempre.

```bash
python scripts/inbox.py list                      # tickets abiertos + escalados
python scripts/inbox.py show 4001                 # detalle, historial y ventana
python scripts/inbox.py reply 4001 "USD 9.60 la unidad para 500."
python scripts/inbox.py close 4001 --note "Cotización enviada"
```

Dos cosas que hace y que importan:

**Lo que mandás queda en `messages` como `outbound`.** La Capa 3 le pasa los
últimos 10 mensajes al modelo, así que en el próximo mensaje del cliente el
agente ya sabe qué contestó el equipo y no lo contradice.

**Chequea la ventana de 24 horas antes de intentar.** WhatsApp sólo acepta
mensajes libres dentro de las 24 h desde el último mensaje del cliente; después
hace falta una plantilla aprobada y Twilio devuelve el error 63016. `show` te
dice cuánto queda; `reply` se niega y explica por qué en vez de tirar un stack
trace. `--force` lo intenta igual si ya tenés plantilla configurada.

`close` también resuelve el escalado asociado. Un escalado que queda pendiente
para siempre hace que el equipo deje de mirar la cola.

### Volver a foja cero

`schema.sql` es idempotente: correrlo de nuevo actualiza la estructura pero **no
borra datos**. Para limpiar antes de una toma, usá `supabase/reset.sql`, que
tiene tres niveles.

El nivel 1 es el que más vas a usar y no pierde nada:

```sql
update public.clients set claude_session_id = null;
```

Guardamos el `session_id` de Claude Code y lo reusamos con `--resume`, así que
el agente arrastra toda la conversación anterior. Si cambiás un `SKILL.md` o el
system prompt y el agente sigue comportándose igual, es por esto: el prompt
nuevo no borra lo que el modelo ya se dijo a sí mismo.

`GET /health` te devuelve el backend activo, las skills cargadas y el estado de
todos los circuit breakers.

---

## Escribir tu propia skill

Tres pasos, sin tocar nada del núcleo. La guía completa está en
[`docs/ESCRIBIR-UNA-SKILL.md`](docs/ESCRIBIR-UNA-SKILL.md).

```bash
mkdir skills/mi-skill
```

`skills/mi-skill/SKILL.md`:

```markdown
---
name: mi-skill
description: >-
  Qué hace Y cuándo usarla. Esto es lo único que Claude ve siempre, así que
  tiene que alcanzarle para decidir solo si activarla.
---

# Mi Skill

## Precondiciones
## Orden de operaciones
## Error handling
```

`skills/mi-skill/tools.py`:

```python
from whatsapp_skills.skills.base import SkillContext, skill_tool

@skill_tool(
    name="hacer_algo",
    description="Una línea. La prosa larga va en el SKILL.md.",
    input_schema={
        "type": "object",
        "properties": {"x": {"type": "string", "description": "..."}},
        "required": ["x"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="10/minute",   # presupuesto propio de esta tool
)
async def hacer_algo(ctx: SkillContext, x: str) -> dict:
    return {"ok": True}
```

Listo. El registry la descubre sola, aparece en los dos backends y hereda
timeout, circuit breaker, rate limiting y logging.

Corré `pytest`: si el `SKILL.md` está mal formado o el schema no cumple lo que
exige `strict`, los tests te lo dicen antes que la API.

---

## Resiliencia

**Circuit breaker por tool.** Tres fallos seguidos y esa tool deja de intentarse
por 30 segundos. Claude recibe un error explícito con la sugerencia de escalar en
vez de seguir reintentando contra un servicio caído. Que se caiga
`client-management` no toca a las otras cuatro.

**Rate limiting por tool, no por usuario.** `find_client` pega a la base y tiene
5/min; `knowledge_search` corre sobre un índice GIN y tiene 50/min. Un solo
presupuesto global para todo trata igual a una query cara y a una barata.

**Idempotencia.** `messages.twilio_sid` tiene índice único. Twilio reintenta ante
cualquier respuesta no-2xx; sin eso, un reintento crea el ticket dos veces.

**200 primero, trabajo después.** Twilio corta el request a los 15 s y el agente
tarda ~8 s. El webhook responde TwiML vacío al instante y procesa en background;
la respuesta sale por la REST API.

---

## Límites conocidos

Cosas que este repo **no** hace, dichas de frente:

- **Sin versionado de skills.** Si cambiás un `SKILL.md` mientras hay
  conversaciones activas, la próxima llamada usa la versión nueva. Para
  producción de verdad querés `skill.v1` / `skill.v2` y una migración.
- **Circuit breaker y rate limiter son in-process.** Con varias réplicas, cada
  una tiene su propio criterio. Estado compartido necesita Redis.
- **La knowledge base es búsqueda léxica**, no semántica. "presupuesto" no
  encuentra "cotización". La RPC hace dos pasadas —primero exige todos los
  términos, y si eso vuelve vacío reintenta con cualquiera ordenando por cuántos
  matchearon— y le dice al modelo cuál usó, así que un término de más ya no
  produce cero resultados. Aun así, si tu dominio tiene mucho sinónimo vas a
  querer pgvector con embeddings.
- **Los documentos se truncan a 1500 caracteres** por búsqueda. Cuando pasa, la
  tool devuelve `truncated: true` y el modelo lo aclara en vez de afirmar que
  tiene la información completa. Si tus documentos son largos, subí `max_chars`
  o partilos en chunks más chicos al cargarlos.
- **El backend `cli` no comparte estado con FastAPI.** El `dispatch` corre dentro
  del subproceso MCP, así que el breaker y el rate limiter viven ahí. Para
  desarrollo da igual; para producción usá `messages_api`.
- **El prefijo mínimo cacheable ronda los 1024 tokens.** Con cinco descripciones
  cortas el system prompt puede quedar por debajo y no cachear nada, en silencio.
  Verificalo con `usage.cache_read_input_tokens` antes de dar por hecho el ahorro.

---

## Comandos

```bash
pytest                              # 141 tests, sin credenciales
ruff check .
python scripts/measure_tokens.py    # requiere ANTHROPIC_API_KEY
python scripts/sync_skills.py       # skills/ -> .claude/skills/
uvicorn whatsapp_skills.main:app --reload --port 8000
```

---

## Una última cosa

**No copies estas cinco skills tal cual.** Las tuyas van a ser otras: tu negocio
no es cotizaciones y tickets. Lo que vale la pena copiar es el patrón —el
registry como único camino de ejecución, la guía separada del schema, el error
handling declarado por skill, el backend detrás de un `Protocol`.

MIT. Hacé lo que quieras con esto.

# claude-whatsapp-crm

Un CRM para WhatsApp donde la IA atiende sola y una persona puede meterse cuando
hace falta. Cuando tomás un chat, **el bot se calla de verdad**: no sigue
contestando por atrás mientras hablás vos.

- **Bandeja en vivo** con todas las conversaciones, sin refrescar, y filtros:
  míos, sin asignar, pidió humano.
- **Estado por conversación**: IA, pidió humano (el agente escaló) o humano.
- **Tomar chat**: el chat queda asignado a vos y el bot deja de contestar. Otro
  agente no puede responder encima; un admin puede reasignarlo.
- **Responder desde el panel**, respetando la ventana de 24 h de WhatsApp.
- **Devolver a la IA** con una nota de lo que acordaste, para que el bot no te
  contradiga.
- **Clientes**: lista con búsqueda y ficha con cuántas veces escribió, primer y
  último contacto, por qué escribió (tickets y escalados), notas internas,
  historial completo y un **resumen con IA** a pedido.
- **Tickets**: los que crea el bot, con filtros, estado, prioridad, asignado y
  notas. Cerrar un ticket resuelve su escalado.
- **Base de conocimiento** editable desde el panel, con una prueba de la misma
  búsqueda que usa el bot.
- **Usuarios y roles**: admins y agentes; alta, cambio de rol y desactivación.

Usa la **API oficial de WhatsApp** a través de Twilio, no una API no oficial que
te puede costar el número. La bandeja la sirve el mismo agente: no hay que
instalar Chatwoot ni mantener otro servidor. En local, `/setup` en Claude Code lo
deja andando; para producción hay un `Dockerfile` (ver [Deploy en Hostinger](#deploy-en-hostinger)).

Está construido arriba de
[claude-whatsapp-chatbot-skills](https://github.com/GonzaGomezDev/claude-whatsapp-chatbot-skills),
un agente de atención con Claude Agent Skills. Cómo funciona el agente por dentro
está más abajo, en [El agente por dentro](#el-agente-por-dentro).

---

## Cómo funciona

```
 Cliente (WhatsApp)
        │
        ▼
     Twilio ──► webhook ──► ¿status = human? ── sí ──► se guarda, el bot no contesta
                                   │
                                   no
                                   ▼
                            Claude + skills
                                   │
                                   ▼
                   ¿sigue en bot? (2da lectura) ── sí ──► Twilio ──► Cliente

 Supabase (conversations, messages) ── Realtime ──► Panel en web/ (operador)
        ▲                                                │
        └── /crm/take · /crm/return · /crm/reply ───────┘
            el agente escribe con la key secreta
```

**El estado vive en la base, no en el panel.** La tabla `conversations` tiene una
fila por teléfono con `status` (`bot`, `needs_human` o `human`). El que tiene que
leerlo es el webhook, antes de llamar a Claude: si una persona tomó el chat, el
mensaje se guarda y no se llama al agente. Tampoco salen las respuestas
automáticas (el "de nada" a un "gracias").

**Se lee dos veces.** El webhook contesta 200 a Twilio y procesa en segundo plano,
y Claude tarda unos segundos. Si tomás el chat justo mientras Claude está
generando, la primera lectura ya pasó. Por eso el estado se vuelve a leer justo
antes de enviar: si cambió a `human`, la respuesta del bot no sale (queda en los
logs como `reply_dropped`).

**Dos caminos de escritura.** El panel lo sirve el agente en su misma URL y usa
la publishable key de Supabase con login.

- **Datos** (editar clientes, notas, tickets, base de conocimiento): el panel
  escribe directo. RLS dice quién puede, y los grants de columna dicen qué: un
  agente no puede cambiarse el rol ni pisar el resumen IA desde la consola del
  navegador.
- **Efectos afuera o secretos** (responder por Twilio, tomar, devolver y asignar,
  dar de alta usuarios, resumen IA): pasan por el agente, el único que tiene la
  key secreta de Supabase y las credenciales de Twilio.

**Roles en la base.** `operators` guarda el rol (`admin` o `agent`) y si está
activo. Las mismas funciones (`is_operator()`, `is_admin()`) protegen RLS y la API
del agente. Un trigger impide quedarse sin admins activos.

**Veces que nos escribió** = días distintos con mensajes entrantes. Se cuenta por
teléfono, así incluye lo que llegó antes de que existiera el cliente.

**Devolver a la IA con contexto.** El bot retoma con los últimos 10 mensajes,
incluidos los del humano. Además, la nota que dejás al devolver entra a su
contexto: si prometiste algo, el bot lo sabe.

### Cuándo no te conviene

- **Equipos grandes.** Hay roles y asignación de chats, pero no reportes,
  métricas de tiempos de respuesta, reparto automático ni app móvil. Con un
  equipo grande, Chatwoot (incluso la versión Cloud) te ahorra construir eso.
- **Mensajes fuera de la ventana de 24 h.** El panel no manda plantillas: te
  avisa que la ventana está cerrada y no deja enviar.
- **Audios, imágenes, Instagram o Messenger.** Sólo texto por WhatsApp.

---

## Setup

El agente (FastAPI, en `src/`) recibe el webhook de Twilio, llama a Claude,
expone los endpoints del CRM y **sirve el panel** (`web/`, Vite + React) en la
misma URL. Es un solo proceso y un solo `.env`.

Necesitás Python 3.11+, Node 20+, [ngrok](https://ngrok.com/download) y cuentas
en Supabase (alcanza el plan gratis), Twilio y ngrok. Con `AGENT_BACKEND=cli` no
necesitás API key de Anthropic: usa tu sesión de Claude Code. Es para desarrollo
local; en un servidor usá `messages_api` (ver [Los dos backends](#los-dos-backends)).

### Con Claude Code: `/setup`

```bash
git clone <este-repo> && cd claude-whatsapp-crm
claude
```

1. Aprobá el server `supabase` del `.mcp.json` cuando Claude Code lo pregunte.
2. Corré `/mcp` → `supabase` → **Authenticate** y logueate en el navegador.
3. Corré `/setup`.

Claude instala las dependencias, crea el proyecto de Supabase (gratis), aplica
el schema, crea tu usuario operador, valida Twilio, levanta ngrok, apunta el
webhook y arranca el agente. Te va a pedir:

- **La key secreta de Supabase** (`sb_secret_...`). El MCP no la expone: la
  pegás vos en `.env`.
- **Tus credenciales de Twilio**, si no están en `.env`.
- **El authtoken de ngrok**, la primera vez.
- **Confirmación** antes de crear el proyecto y antes de cambiar el webhook de
  tu número.

Las instrucciones que sigue Claude están en
[`.claude/commands/setup.md`](.claude/commands/setup.md). Abajo está el mismo
setup a mano.

### A mano

**1. Instalar**

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
cd web && npm install && npm run build && cd ..
```

**2. Supabase**

1. Creá un proyecto.
2. Abrí el **SQL Editor** y pegá `supabase/schema.sql` entero. Crea:
   - las tablas, incluidas `conversations` y `operators` del CRM;
   - la búsqueda `search_knowledge`;
   - las políticas de RLS;
   - la publicación de Realtime;
   - tres documentos de ejemplo en la knowledge base.

   Es idempotente: si actualizás el repo, volvé a correrlo.

3. En *Project Settings → API Keys* copiá la URL y las dos keys al `.env`:

```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...            # sólo la usa el agente, nunca llega al navegador
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...  # pública: el agente se la pasa al panel
```

Si tu proyecto todavía tiene las keys legacy (`anon` / `service_role`), también
funcionan: `SUPABASE_SERVICE_ROLE_KEY` se acepta como alias. Supabase las retira
a fines de 2026.

4. Creá el primer admin. Son chats de clientes: el panel solo deja entrar a los
   usuarios cargados en `operators`. El resto del equipo se da de alta desde el
   panel, en **Usuarios**.

```bash
python scripts/create_operator.py vos@tuempresa.com    # genera la contraseña y la muestra
```

Recomendado: en *Authentication → Sign In / Providers* apagá **Allow new users to
sign up**. No es imprescindible (un usuario que no está en `operators` no ve ni
toca nada), pero evita cuentas sueltas.

**3. Twilio**

Necesitás un número de WhatsApp en Twilio. Para probar alcanza el
[WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn):
mandá `join <código>` desde tu teléfono. La unión vence a los 3 días.

```bash
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # el sandbox, o tu número propio
```

**4. ngrok y el webhook**

```bash
ngrok config add-authtoken <tu-token>     # sólo la primera vez
ngrok http 8000
```

El plan gratis de ngrok te da un dominio fijo (`<algo>.ngrok-free.app`): es el
mismo en cada arranque, así que esto se configura una sola vez.

1. Poné la URL en `PUBLIC_BASE_URL` del `.env`.
2. Apuntá el webhook de Twilio a `PUBLIC_BASE_URL/webhook/whatsapp`, método POST:
   - **Número propio:** `python scripts/twilio_webhook.py --set`. Usa la Senders
     API. Sin `--set`, solo muestra adónde apunta hoy.
   - **Sandbox:** solo desde la consola, en *Sandbox settings* → "When a message
     comes in". No hay API para esto.

> La firma de Twilio se calcula sobre la **URL pública exacta**. Si te da 403 en
> todos los mensajes, es casi seguro que `PUBLIC_BASE_URL` no coincide con el
> webhook configurado en Twilio: `http` vs `https`, barra final de más, o un
> dominio de ngrok viejo.

**5. Levantar**

```bash
python scripts/sync_skills.py            # sólo si usás AGENT_BACKEND=cli
uvicorn whatsapp_skills.main:app --port 8000
```

El panel queda en `http://localhost:8000`, y en el celular, en la URL de ngrok.
`curl http://localhost:8000/health` devuelve el backend, el modelo y las skills
cargadas (4 skills, 9 tools).

Para trabajar en el panel con recarga en caliente: `cd web && npm run dev`
(http://localhost:5173). Vite le pasa `/crm` y `/config.js` al agente en :8000.

### Probar

1. Entrá al panel con el usuario operador.
2. Escribile al número de Twilio desde tu WhatsApp. La conversación aparece en
   la bandeja sin refrescar, con la etiqueta **IA**, y el bot contesta.
3. Pedí hablar con una persona. Cuando el agente escala, la etiqueta pasa a
   **Pidió humano**.
4. **Tomar chat.** Escribí otra vez desde el teléfono: el mensaje entra a la
   bandeja y el bot no contesta.
5. Respondé desde el panel. El mensaje llega al teléfono. Si el cliente no
   escribió en las últimas 24 h, el campo se deshabilita y explica por qué.
6. **Devolver a la IA**, con una nota de lo que acordaste. El bot retoma con esa
   nota en su contexto.

Los logs del agente muestran cada decisión: el evento `routed` con `route=human`
cuando el bot se calla y `reply_dropped` si tomaste el chat mientras Claude estaba
generando.

### Deploy en Hostinger

El repo trae un `Dockerfile`: una sola imagen que compila el panel y lo sirve
junto con el agente. Supabase sigue en la nube; solo se despliega esta app.

1. **VPS.** Contratá un VPS en Hostinger con la plantilla **EasyPanel**
   (*VPS → OS & Panel → EasyPanel*). Hostinger también tiene Coolify y Docker
   Manager; el Dockerfile sirve igual en los tres.
2. **Dominio.** Creá un registro **A** (por ejemplo `crm.tudominio.com`) que
   apunte a la IP del VPS.
3. **App.** En EasyPanel: *Create project → App*.
   - **Source:** tu repo de GitHub (rama `main`).
   - **Build:** Dockerfile.
4. **Variables.** En *Environment*, pegá tu `.env` con estos cambios:

```bash
AGENT_BACKEND=messages_api          # obligatorio en un servidor
ANTHROPIC_API_KEY=sk-ant-...
PUBLIC_BASE_URL=https://crm.tudominio.com
```

5. **Dominio en la app.** En *Domains*, agregá `crm.tudominio.com` con puerto
   **8000**. EasyPanel saca el certificado HTTPS solo. Después, **Deploy**.
6. **Webhook.** Apuntalo al dominio nuevo: `python scripts/twilio_webhook.py --set`
   desde tu máquina, con el `PUBLIC_BASE_URL` nuevo en tu `.env`. Si usás el
   sandbox, cambialo en la consola.

Con eso el panel queda en `https://crm.tudominio.com` y ngrok ya no hace falta.
Para probar la imagen antes de subirla: `docker compose up --build`
(http://localhost:8000).

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

**Para probar, WhatsApp es lo más cómodo:** el escalado te llega al mismo teléfono
desde el que estás probando. La contra
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

## El agente por dentro

El agente que atiende es una copia de
[claude-whatsapp-chatbot-skills](https://github.com/GonzaGomezDev/claude-whatsapp-chatbot-skills):
cuatro skills coordinadas (clientes, tickets, knowledge base y escalado a humano)
con circuit breaker, rate limiting por tool y logging estructurado. Lo que
sigue explica cómo está armado.

```
[12:49:34 PM] Message from +5491123456789: "Hola, soy Juan Pérez, necesito una cotización para 500 unidades de X"
[12:49:34 PM] Running Claude (messages_api) with 4 Skills
[12:49:35 PM] Claude calling: find_client("+5491123456789")
[12:49:35 PM] Result: { found: false }  (287ms · breaker=closed)
[12:49:36 PM] Claude calling: create_client("+5491123456789", "Juan Pérez", null)
[12:49:36 PM] Claude calling: knowledge_search("cotización producto X unidades", 5)
[12:49:36 PM] Result: { count: 2, top_confidence: 0.412, ... }  (194ms · breaker=closed)
[12:49:37 PM] Claude calling: create_ticket(..., "quotation", "normal", ...)
[12:49:39 PM] Claude response: "Hola Juan, ..."  (in=4821 · out=180 · cache_read=3902)
```

### Tools vs Skills, sin marketing

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

> Con 9 tools el ahorro por diferir todavía es moderado. La brecha crece con el
> tamaño del tool set: a las 40 o 50 tools es la diferencia entre que entre o no
> entre en presupuesto.

Lo que las Skills sí te dan desde el minuto cero, sin discusión: **separación de
responsabilidades**. Cada skill tiene su dominio, su manejo de errores y su
presupuesto de rate limit. Cuando una se cae, las otras tres siguen.

---

### Arquitectura

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

#### Las 4 skills

| Skill | Tools | Qué resuelve |
|---|---|---|
| `client-management` | `find_client`, `create_client`, `update_client` | Quién está escribiendo |
| `ticketing` | `create_ticket`, `find_open_tickets`, `update_ticket_status` | Lo que el equipo tiene que hacer |
| `knowledge` | `knowledge_search` | Precios, plazos, políticas |
| `human-handoff` | `escalate_to_human` | La salida de emergencia |

Más la tool built-in `load_skill_guide`. Total: **9 tools**.

Cada skill es una carpeta con el formato real de Agent Skills:

```
skills/knowledge/
├── SKILL.md    ← frontmatter (name, description) + la guía
└── tools.py    ← las funciones, con @skill_tool
```

El `SKILL.md` es el formato que lee Claude Code. Corré `python scripts/sync_skills.py`
y las mismas cuatro carpetas funcionan como skills nativas en tu editor.

---

### Los dos backends

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
| Para qué sirve | **producción** | **iterar sobre los SKILL.md gratis** |

Se cambia con una variable de entorno:

```bash
AGENT_BACKEND=cli           # desarrollo, sin API key
AGENT_BACKEND=messages_api  # producción
```

`cli` usa tu suscripción de Claude Code, que según los
[términos de Anthropic](https://code.claude.com/docs/en/legal-and-compliance) es
para uso individual: un bot que atiende clientes es un servicio. En un servidor,
`messages_api` con `ANTHROPIC_API_KEY`. Ojo: si `ANTHROPIC_API_KEY` está cargada,
el subproceso de `claude -p` la usa en vez de la suscripción.

El modo `cli` expone las tools a Claude Code por un server MCP
(`src/whatsapp_skills/agent/mcp_server.py`) que recorre el mismo registry. Las
firmas de Python se sintetizan desde los JSON Schema, así que **no hay
definiciones duplicadas**: el registry es la única fuente de verdad, y los tests
verifican que los dos backends expongan exactamente las mismas tools con los
mismos `required` y `enum`.

#### Aislamiento del backend `cli`

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

Verificado: la superficie pasó de 35 tools a sólo las del MCP.

Si en tus logs ves `unexpected_tools_available` o `mcp_server_failed`, paralo y
mirá eso antes que nada: el primero es un agujero de seguridad, el segundo
significa que el agente está respondiendo **sin ninguna tool**.

---

### Escribir tu propia skill

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

### Resiliencia

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

### Límites conocidos

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
- **El prefijo mínimo cacheable ronda los 1024 tokens.** Con cuatro descripciones
  cortas el system prompt puede quedar por debajo y no cachear nada, en silencio.
  Verificalo con `usage.cache_read_input_tokens` antes de dar por hecho el ahorro.

---

## Comandos

```bash
# Agente (desde la raíz, con el virtualenv activado)
pytest                              # sin credenciales
ruff check .
python scripts/measure_tokens.py    # requiere ANTHROPIC_API_KEY
python scripts/sync_skills.py       # skills/ -> .claude/skills/
python scripts/inbox.py list        # bandeja de consola
python scripts/create_operator.py vos@tuempresa.com   # alta de un operador del panel
python scripts/twilio_webhook.py [--set]               # ver o apuntar el webhook del número
uvicorn whatsapp_skills.main:app --reload --port 8000
ngrok http 8000

# Panel (desde web/)
npm run build                       # chequeo de tipos + build a dist/ (lo sirve el agente)
npm run dev                         # http://localhost:5173, con proxy al agente en :8000

# Imagen de producción
docker compose up --build           # http://localhost:8000
```

---

## Una última cosa

**No copies estas cuatro skills tal cual.** Las tuyas van a ser otras: tu negocio
no es cotizaciones y tickets. Lo que vale la pena copiar es el patrón —el
registry como único camino de ejecución, la guía separada del schema, el error
handling declarado por skill, el backend detrás de un `Protocol`.

MIT. Hacé lo que quieras con esto.

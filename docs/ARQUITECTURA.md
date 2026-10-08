# Arquitectura

Seis capas. Cada una hace una cosa y le pasa el resultado a la siguiente. La
razón de partirlo así no es estética: es que cuando algo falla querés saber *en
qué capa* falló sin leer un stack trace de cuarenta líneas.

```
                          WhatsApp
                              │
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 1 — Webhook                              webhook.py          │
│  · Valida la firma de Twilio contra PUBLIC_BASE_URL               │
│  · Deduplica por MessageSid (índice único)                        │
│  · Devuelve TwiML vacío 200 y sigue en BackgroundTasks            │
└─────────────────────────────┬─────────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 2 — Router                               router.py           │
│  · ¿Cortesía? ¿opt-out? ¿media sin texto? ¿vacío?                 │
│  · Resuelve en microsegundos, sin tocar el modelo                 │
└─────────────────────────────┬─────────────────────────────────────┘
                              │ Route.AGENT
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 3 — Context                              context.py          │
│  · Cliente por teléfono                                           │
│  · Últimos 10 mensajes + tickets abiertos (en paralelo)           │
│  · Si la base falla, degrada: menos contexto, no menos respuesta  │
└─────────────────────────────┬─────────────────────────────────────┘
                              │ Conversation
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 4 — Agent                                agent/              │
│                                                                    │
│    AgentBackend (Protocol)                                        │
│      ├── MessagesAPIBackend   loop manual, defer_loading, caching  │
│      └── ClaudeCLIBackend     subproceso `claude -p` + MCP         │
│                    │                                              │
│                    └──────► SkillRegistry.dispatch ◄──────────────┤
│                             timeout · breaker · rate limit · log  │
│                                    │                              │
│             ┌──────────────┬───────┴───────┬─────────────┐        │
│        client-mgmt     ticketing       knowledge      handoff     │
└─────────────────────────────┬─────────────────────────────────────┘
                              │ AgentResult
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 5 — Response                             twilio_client.py    │
│  · Parte mensajes largos por párrafo, después por oración         │
│  · Manda por la REST API (no TwiML)                               │
│  · Registra el saliente en messages                               │
└─────────────────────────────┬─────────────────────────────────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────────┐
│ Capa 6 — Observability                        observability/      │
│  Latencia por tool · estado del breaker · tokens · tipo de error  │
└───────────────────────────────────────────────────────────────────┘
```

---

## Capa 1 — Webhook

**Dos decisiones que parecen detalles y no lo son.**

*Responder antes de trabajar.* Twilio corta el request a los 15 segundos. El
agente tarda unos 8. Si respondieras con TwiML al final, cualquier pico de
latencia produce dos cosas malas a la vez: el cliente no recibe nada, y Twilio
reintenta el mismo mensaje. Por eso devolvemos un TwiML vacío al instante, el
trabajo va a `BackgroundTasks`, y la respuesta sale después por la REST API.

*Validar la firma.* El webhook es una URL pública. Sin `RequestValidator`
cualquiera puede hacerte crear clientes, abrir tickets y disparar escalados. La
firma se calcula sobre la URL pública **exacta** — la que ve FastAPI detrás de
ngrok no sirve.

*Idempotencia.* `messages.twilio_sid` tiene índice único. Si el insert choca, es
un reintento y cortamos ahí. Sin esto, un reintento crea el ticket dos veces y el
cliente recibe la respuesta duplicada.

## Capa 2 — Router

La optimización más aburrida y más efectiva del sistema.

Un "gracias" no necesita cinco skills, ocho segundos y una llamada al modelo. Un
audio no lo podemos procesar de ninguna manera. Cada mensaje que se resuelve acá
es un request entero que no se paga.

El criterio es **conservador**: ante la duda, pasa al agente. Un falso positivo
acá es un cliente real recibiendo una respuesta enlatada, que es bastante peor
que gastar unos centavos de más. Por eso `"gracias pero necesito hablar con
alguien"` va al agente, y sólo `"gracias"` a secas se corta.

## Capa 3 — Context

Traemos de una sola vez lo que el agente casi seguro va a necesitar: quién es el
cliente, de qué venían hablando, qué tiene abierto.

Cada uno de esos datos es una tool call que Claude no tiene que hacer. Una tool
call que no se hace son dos round trips menos y unos cuantos tokens. Es preferible
precargar el contexto a que el agente lo descubra a fuerza de preguntas.

El historial y los tickets no dependen entre sí, así que van con `asyncio.gather`.

**Degrada.** Si la base falla, `_safe` loguea y devuelve `None`. Un historial que
no cargó empeora la respuesta; una excepción acá deja al cliente sin ninguna.

## Capa 4 — Agent

### El Protocol

```python
class AgentBackend(Protocol):
    async def run(self, convo: Conversation, ctx: SkillContext) -> AgentResult: ...
```

Las capas de arriba y de abajo no saben qué backend corrió. Se elige con
`AGENT_BACKEND` en el `.env`.

La lógica de negocio declara qué necesita, el adapter resuelve cómo. La Skill
no cambia, cambia el backend.

### El loop manual (messages_api)

```
   ┌──────────────────────────────────────────┐
   │ create(system, tools, messages)          │
   └────────────────┬─────────────────────────┘
                    │
        ┌───────────▼────────────┐
        │ stop_reason?           │
        ├────────────────────────┤
        │ refusal    → fallback  │
        │ pause_turn → reenviar  │
        │ end_turn   → salir     │
        │ tool_use   ↓           │
        └───────────┬────────────┘
                    │
        ┌───────────▼──────────────────────────┐
        │ asyncio.gather sobre TODOS los       │
        │ bloques tool_use del mismo turno     │
        └───────────┬──────────────────────────┘
                    │
        ┌───────────▼──────────────────────────┐
        │ UN mensaje user con TODOS los        │
        │ tool_result (los de error también)   │
        └───────────┬──────────────────────────┘
                    │
                    └──► volver al principio
```

Es manual y no usa el Tool Runner del SDK a propósito. `@beta_tool` deriva los
schemas de la firma de la función y no deja setear `defer_loading`, ni da un
punto donde meter timeout por tool, circuit breaker, rate limiting y logging de
latencia. Todo el manejo de errores que hace interesante a esta arquitectura vive
justamente en ese punto.

**Dos reglas de la API que se pagan caro si se rompen:**

- Todos los `tool_result` van en **un solo** mensaje `user`. Partirlos en varios
  le enseña al modelo a dejar de paralelizar.
- Una tool que falló igual devuelve su `tool_result`, con `is_error: True`.
  Descartarlo deja un `tool_use` sin respuesta y la API rechaza el request
  siguiente.

### El puente MCP (cli)

```
FastAPI ──► ClaudeCLIBackend ──► subprocess: claude -p
                                        │
                                        │ stdio JSON-RPC
                                        ▼
                                  mcp_server.py
                                        │
                                        ▼
                              registry.dispatch  ← el mismo de siempre
```

Los schemas viven en el registry como JSON Schema; el SDK de MCP los construye
desde firmas de Python. En vez de duplicar las definiciones —que se
desincronizarían al primer cambio— sintetizamos la firma desde el schema.
`enum`, `minimum` y compañía viajan por `json_schema_extra`, así el schema que ve
Claude Code es equivalente al que ve la Messages API.
`tests/test_backend_contract.py` verifica esa equivalencia.

**Asimetría conocida:** en modo `cli` el `dispatch` corre dentro del subproceso
MCP, así que el estado del breaker y el cliente de Supabase viven ahí, no en el
proceso de FastAPI. Para desarrollo es irrelevante; para producción se usa
`messages_api`.

### El system prompt y el cache

```
┌─ tools ─────────────────────┐
├─ system[0]  PERSONA         │  ← estable, byte a byte
│             + descripciones │
│             de las 4 skills │
│             cache_control ──┼──► breakpoint
├─ system[1]  contexto de     │  ← varía por conversación
│             esta charla     │
└─ messages ──────────────────┘
```

El orden de render es `tools → system → messages`, y el cache es *prefix match*:
cualquier byte que cambie invalida todo lo que sigue. Por eso las tools y las
descripciones de skills están ordenadas alfabéticamente, y por eso el teléfono
del cliente va después del breakpoint.

Con cinco descripciones cortas el prefijo puede quedar por debajo del mínimo
cacheable (~1024 tokens) y no cachear nada, **en silencio**. Verificalo con
`usage.cache_read_input_tokens`.

## Capa 5 — Response

Los mensajes largos se parten por párrafo, después por oración, y sólo al final a
lo bruto. Partir en el lugar equivocado se nota en WhatsApp.

Se manda por la REST API, no por TwiML, porque para cuando el agente terminó el
request de Twilio ya se cerró.

## Capa 6 — Observability

El punto 3 de "lo que cambiaría" del video, resuelto de entrada: si no medís por
skill, no sabés cuál es tu cuello de botella.

Cada llamada loguea latencia, estado del breaker, tipo de error y tokens.

```bash
LOG_FORMAT=demo   # legible en cámara
LOG_FORMAT=json   # una línea JSON por evento, para un agregador
```

`GET /health` devuelve el backend activo, las skills cargadas, el estado de todos
los circuit breakers y los tokens que quedan en cada bucket.

---

## Resiliencia, en concreto

### Circuit breaker

```
   CLOSED ──[N fallos]──► OPEN ──[cooldown]──► HALF_OPEN
      ▲                                            │
      └──────────[sonda OK]────────────────────────┤
                                                   │
              OPEN ◄──────[sonda falla]────────────┘
```

Un fallo durante la sonda reabre de inmediato: el servicio ya demostró que sigue
mal, no tiene sentido volver a contar hasta N.

Los circuitos son **independientes por tool**. Que se caiga `find_client` no
impide que `knowledge_search` siga funcionando — que es exactamente el argumento
de separación de responsabilidades, hecho código.

### Rate limiting

Token bucket por tool, con recarga continua (no en saltos por ventana, para no
generar efecto manada al cambiar de minuto).

Nunca bloquea. Devuelve el error y deja que Claude decida: esperar, usar otra
skill, o escalar. Dormirse adentro del handler se comería el presupuesto de
latencia sin que nadie se entere.

| tool | presupuesto | por qué |
|---|---|---|
| `find_client` | 5/min | pega a la base, es cara |
| `knowledge_search` | 50/min | índice GIN, es barata |
| `create_ticket` | 20/min | escritura, pero acotada |

Ambos son **in-process**. Con varias réplicas, cada una tiene su propio criterio.
Estado compartido necesita Redis.

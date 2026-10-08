# Escribir una skill

Una skill es una carpeta con dos archivos. El registry la descubre sola: no hay
que registrarla en ningún lado, ni importar nada, ni tocar el núcleo.

```
skills/mi-skill/
├── SKILL.md    ← el frontmatter y la guía
└── tools.py    ← las funciones
```

---

## La división que importa

Esto es lo único que hay que entender bien:

| | dónde vive | cuándo se paga |
|---|---|---|
| **`description` de la skill** | frontmatter del `SKILL.md` | **en cada request** |
| **`description` de la tool** | el decorador | **en cada request** |
| **la guía completa** | cuerpo del `SKILL.md` | sólo si Claude la pide |

Todo lo que sea prosa larga —cuándo usar cada tool, en qué orden, qué hacer si
falla, qué no hacer nunca— va en el **cuerpo** del `SKILL.md`. Claude lo lee con
`load_skill_guide` cuando lo necesita.

Meter esa prosa en las descripciones de las tools es el error caro: se paga en
cada mensaje que procesás, para siempre, aunque la skill no se use.

---

## 1. El SKILL.md

```markdown
---
name: mi-skill
description: >-
  Qué hace la skill Y cuándo conviene usarla. Con suficiente detalle para que
  el modelo decida solo si activarla, sin leer nada más.
---

# Mi Skill

Una o dos líneas sobre para qué existe.

## Precondiciones

Qué tiene que haber pasado antes. ¿Necesita un client_id? Decilo.

## Orden de operaciones

1. Primero esto
2. Después esto otro
3. Si pasa X, en cambio esto

## Error handling

- `error_type: timeout` — qué hacer
- `error_type: circuit_open` — qué hacer
- Qué NO hacer nunca

## Qué no hacer

Los antipatrones concretos que viste en producción.
```

### Reglas del frontmatter

- **`name`** en kebab-case, y tiene que ser **idéntico al nombre de la carpeta**.
  Si no coinciden, Claude Code no descubre bien la skill.
- **`description`** de 40 caracteres para arriba. Es lo único que Claude ve
  siempre: si dice sólo "maneja pagos", el modelo no tiene con qué decidir.
  Escribí **qué hace Y cuándo usarla**.
- Usá un **block scalar `>-`**. Las descripciones buenas tienen dos puntos, y en
  YAML plano `: ` rompe el parseo. Con `>-` no hay problema y encima se lee mejor
  en el archivo.

```yaml
description: >-
  Buscar respuestas en la base de conocimiento interna: listas de precios,
  políticas de pago, plazos de entrega. Usala antes de responder cualquier
  pregunta sobre condiciones comerciales.
```

El loader valida todo esto al arrancar y falla con un mensaje que dice qué
arreglar. Un `SKILL.md` mal formado que carga a medias es peor que uno que no
carga.

---

## 2. El tools.py

```python
from __future__ import annotations

from typing import Any

from whatsapp_skills.skills.base import SkillContext, skill_tool


@skill_tool(
    name="hacer_algo",
    description="Una línea. La prosa larga va en el SKILL.md.",
    input_schema={
        "type": "object",
        "properties": {
            "cosa": {
                "type": "string",
                "description": "Qué es este parámetro y de dónde sale.",
            },
        },
        "required": ["cosa"],
        "additionalProperties": False,
    },
    timeout_s=3.0,
    rate_limit="10/minute",
)
async def hacer_algo(ctx: SkillContext, cosa: str) -> dict[str, Any]:
    resultado = await ctx.db.algo(cosa)
    return {"ok": True, "resultado": resultado}
```

### El decorador

| parámetro | qué hace |
|---|---|
| `name` | Global en todo el repo. Chocar dos nombres falla al importar. |
| `description` | Una línea. Se paga en cada request. |
| `input_schema` | JSON Schema. Con `strict=True` (default) exige `additionalProperties: False` y `required`. |
| `timeout_s` | Sé realista: es el presupuesto de latencia de esta tool. |
| `rate_limit` | `"5/minute"`. El presupuesto propio de **esta** tool, no del usuario. |
| `defer_loading` | `True` para que sólo se cargue si Claude la busca. |
| `strict` | Dejalo en `True` salvo que tengas un schema que no lo permita. |

### Reglas de los handlers

**Tienen que ser `async`.** El decorador lo verifica. Todo el pipeline es
asyncio y una función sync bloquea el event loop entero. Si tenés una librería
sync, envolvela en `asyncio.to_thread` como hace `integrations/supabase_client.py`.

**`ctx` va primero**, siempre. Trae `phone`, `settings`, `db`, `notifier`,
`client_id`, `conversation` y un `scratch` para compartir cosas entre tools del
mismo turno.

**Devolvé dicts serializables a JSON**, no objetos. El resultado se serializa y
se le manda al modelo tal cual.

**Dejá que las excepciones suban.** `registry.dispatch` las atrapa, las cuenta
para el circuit breaker y las convierte en un `tool_result` con `is_error: True`.
Si vos las atrapás y devolvés `{"ok": False}`, el breaker nunca se entera de que
el servicio está caído.

**Devolvé errores esperables como datos.** "No encontré el cliente" no es una
excepción, es un resultado: `{"found": False}`. Reservá las excepciones para lo
que realmente salió mal.

### Ayudá al modelo con el resultado

Un resultado que se explica solo ahorra una vuelta entera del loop:

```python
return {
    "count": len(docs),
    "top_confidence": top,
    "docs": docs,
    "guidance": (
        "Match fuerte. Respondé con esto y citá el documento."
        if top > 0.30
        else "Confianza baja: tratalo como ruido, no lo cites."
    ),
}
```

---

## 3. Verificar

```bash
pytest
```

Los tests chequean que la skill nueva aparezca, que el `SKILL.md` parsee, que el
schema cumpla lo que exige `strict` y que los `required` existan en `properties`.

Si vas a usar `AGENT_BACKEND=cli`:

```bash
python scripts/sync_skills.py
```

Y listo. La skill aparece en los dos backends, con timeout, circuit breaker,
rate limiting y logging heredados.

---

## Cómo dividir las skills

La pregunta no es "¿qué tools tengo?" sino **"¿qué dominios de falla tengo?"**.

Una skill debería agrupar tools que:

- comparten precondiciones (todas necesitan `client_id`),
- fallan juntas (todas pegan a la misma base),
- comparten reglas de negocio,
- y tienen sentido como una unidad para alguien que no leyó el código.

`knowledge` y `ticketing` están separadas aunque las dos peguen a Supabase,
porque **fallan distinto**: una búsqueda vacía se resuelve diciendo que no se
sabe; un ticket que no se crea es una promesa al cliente que nadie va a cumplir.
Manejo de errores distinto, skill distinta.

Si dos skills tuyas tienen la misma sección de error handling, probablemente sean
una sola.

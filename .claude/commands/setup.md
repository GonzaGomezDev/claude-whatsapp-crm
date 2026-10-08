---
description: Levanta el CRM en local de punta a punta (dependencias, Supabase, operador, Twilio, ngrok, agente y panel)
---

Vas a dejar el CRM funcionando en la máquina del usuario. Hablale en español, con
voseo, y en cada paso decí en una línea qué hacés. Sé breve: el usuario quiere
verlo andando, no leer.

## Reglas

- **Idempotente.** Antes de cada paso, mirá si ya está hecho (valores en `.env`,
  procesos corriendo) y saltealo diciendo que ya estaba.
- **Secretos.** Nunca muestres en pantalla la key secreta de Supabase, el Auth
  Token de Twilio ni el authtoken de ngrok. Para confirmar que un valor está
  cargado, decí "cargado", no lo imprimas. `.env` está en `.gitignore`: no lo
  commitees ni lo copies a otro lado.
- **Solo el `.env` de la raíz.** No hay `web/.env`: el agente le pasa al panel la
  URL y la publishable key en `/config.js`.
- **No toques código.** Si algo falla, diagnosticá, explicá la causa en una línea
  y pará en ese paso.
- **Pedí confirmación** antes de crear el proyecto de Supabase y antes de cambiar
  el webhook de Twilio. Las dos cosas tienen efectos fuera de esta máquina.
- **Python del proyecto:** `.venv/Scripts/python` en Windows, `.venv/bin/python`
  en macOS y Linux. Abajo dice `PY`.
- **Procesos largos** (`ngrok`, `uvicorn`): en segundo plano, nunca en primer plano.

## 0. Prerrequisitos

Chequeá `python --version` (3.11 o más), `node --version` (20 o más) y
`ngrok version`. Si falta algo, decí qué y dónde se instala, y pará:

- Python: https://www.python.org/downloads/
- Node: https://nodejs.org/
- ngrok: https://ngrok.com/download. En Windows también se puede con
  `winget install ngrok.ngrok`.

## 1. Dependencias

1. Si no existe `.venv`, crealo con `python -m venv .venv`. Después corré
   `PY -m pip install -e ".[dev]"`.
2. En `web/`, corré `npm install` y `npm run build`. El agente sirve `web/dist`.
3. Si no existe `.env`, copialo de `.env.example`.

## 2. Supabase

1. **MCP.** Fijate si tenés las tools `mcp__supabase__*`.
   - Si no están, decile al usuario que corra `/mcp`, elija `supabase` →
     **Authenticate** y se loguee en el navegador.
   - Si `supabase` ni aparece en `/mcp`, tiene que aprobar el server del
     `.mcp.json`: que salga y vuelva a entrar con `claude --continue`.
   - Pará hasta que diga que está listo.
2. **Proyecto.**
   - Si `SUPABASE_URL` ya tiene valor, preguntá si se usa ese proyecto.
   - Si no, corré `list_organizations` (si hay más de una, preguntá cuál) y
     `list_projects`. Ofrecé crear uno nuevo, `whatsapp-crm` (recomendado), o
     usar uno existente: el schema es idempotente y no borra datos.
   - **Proyecto nuevo:** preguntá la región, con opciones `sa-east-1` (São Paulo),
     `us-east-1` y `eu-central-1`. Después `get_cost` → `confirm_cost` →
     `create_project`.
   - El plan gratis permite 2 proyectos activos. Si falla por eso, explicalo y
     ofrecé usar uno existente.
   - Esperá a que `get_project` dé `ACTIVE_HEALTHY` (tarda un par de minutos) y
     consultá de nuevo cada tanto.
3. **Schema.** Leé `supabase/schema.sql` entero y aplicalo con `apply_migration`
   (nombre `crm_schema`), sin recortarlo.
   - Verificá con `list_tables` que existan `clients`, `messages`, `tickets`,
     `knowledge_docs`, `escalations`, `conversations` y `operators`.
4. **URL y publishable key.** Corré `get_project_url` → `SUPABASE_URL` y
   `get_publishable_keys` → `SUPABASE_PUBLISHABLE_KEY`, y escribilos en `.env`.
   Usá la que empieza con `sb_publishable_`. La `anon` legacy solo si no hay otra.
5. **Key secreta.** El MCP no la devuelve. Pedile al usuario que:
   1. abra `https://supabase.com/dashboard/project/<ref>/settings/api-keys`;
   2. en **Secret keys** copie una (o cree una si no hay);
   3. la pegue él mismo en `.env`, en `SUPABASE_SECRET_KEY=`, y te avise.

   Mejor que no la pegue en el chat. Si igual la pega, escribila en `.env` y seguí.
6. **Verificá la conexión** con una consulta real que no imprima secretos:

   ```bash
   PY -c "import sys; sys.path.insert(0,'src'); from supabase import create_client; from whatsapp_skills.config import Settings; s=Settings(_env_file='.env', twilio_validate_signature=False); c=create_client(s.supabase_url, s.supabase_secret_key); print('conversations:', len(c.table('conversations').select('phone').limit(1).execute().data), 'OK')"
   ```

   Si falla con `bad_jwt` o 401, la key está mal copiada o no es la secreta.

## 3. Primer admin del panel

1. Preguntá el email. Va a ser admin: el resto del equipo lo da de alta él mismo
   desde el panel, en **Usuarios**.
2. Corré `PY scripts/create_operator.py <email>` y mostrale la contraseña
   generada. Es lo único secreto que sí se muestra: es suya y la necesita para
   entrar.
3. Recomendá, sin bloquear, apagar **Allow new users to sign up** en
   `https://supabase.com/dashboard/project/<ref>/auth/providers`.

## 4. Twilio

1. Revisá que `.env` tenga `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` y
   `TWILIO_WHATSAPP_FROM`.
   - Si faltan, pedile al usuario que los cargue desde
     https://console.twilio.com (el SID y el Auth Token están en *Account Info*).
   - Para probar sin número propio: `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`
     (sandbox).
2. Validá las credenciales:

   ```bash
   PY -c "import sys; sys.path.insert(0,'src'); from twilio.rest import Client; from whatsapp_skills.config import Settings; s=Settings(_env_file='.env', twilio_validate_signature=False); print('Twilio:', Client(s.twilio_account_sid, s.twilio_auth_token).api.accounts(s.twilio_account_sid).fetch().status)"
   ```

   Tiene que imprimir `active`.

## 5. ngrok

1. Si `http://127.0.0.1:4040/api/endpoints` ya responde, ngrok está corriendo:
   reusalo.
2. Si no, levantá `ngrok http 8000` en segundo plano.
   - Si falla por falta de authtoken, pedile al usuario que lo copie de
     https://dashboard.ngrok.com/get-started/your-authtoken y corra
     `! ngrok config add-authtoken <token>`. Después reintentá.
3. Leé la URL `https://` de `http://127.0.0.1:4040/api/endpoints` (campo `url`).
   Si ese endpoint no existe, usá `/api/tunnels` (campo `public_url`).
4. Escribila en `PUBLIC_BASE_URL`, sin barra final.
   - El plan gratis da un dominio fijo, así que esto se hace una sola vez.

## 6. Webhook de Twilio

1. Corré `PY scripts/twilio_webhook.py`. Muestra el número y adónde apunta hoy.
2. **Sandbox:** no hay API. Dale al usuario, en este orden:
   1. el link a la consola que imprime el script;
   2. la URL exacta (`PUBLIC_BASE_URL/webhook/whatsapp`, método POST);
   3. el recordatorio de mandar `join <código>` desde su WhatsApp al
      +1 415 523 8886.

   Esperá a que confirme.
3. **Número propio:**
   - Si ya apunta a `PUBLIC_BASE_URL/webhook/whatsapp`, seguí.
   - Si apunta a otra URL, avisale que esa URL va a dejar de recibir mensajes
     (puede ser otro proyecto) y pedí confirmación.
   - Con el OK, corré `PY scripts/twilio_webhook.py --set`.

## 7. Levantar el agente

1. Si `AGENT_BACKEND=cli`, corré antes `PY scripts/sync_skills.py`.
2. Si algo ya escucha en el puerto 8000, frenalo solo si es un `uvicorn` de este
   repo. Si es otra cosa, preguntá.
3. Levantá `PY -m uvicorn whatsapp_skills.main:app --port 8000` en segundo plano.
4. Verificá:
   - `http://localhost:8000/health` → `status: ok`, 9 tools;
   - `http://localhost:8000/config.js` → URL y key de Supabase cargadas.

   Mirá el log de arranque: si dice `Configuración incompleta`, nombra lo que falta.

## 8. Probar

Dale al usuario estos pasos y quedate mirando el log del agente:

1. Abrí el panel en `http://localhost:8000`, o en el celular con la URL de ngrok,
   y entrá con el operador.
2. Mandá un WhatsApp al número. Tiene que aparecer en la bandeja sin refrescar,
   con la etiqueta **IA**, y el bot tiene que contestar.
3. Apretá **Tomar chat** y volvé a escribir: el mensaje entra y el bot no
   contesta (en el log, `routed` con `route=human`).
4. Respondé desde el panel. Llega al teléfono.
5. Apretá **Devolver a la IA** con una nota.

Si el mensaje no llega al log:
- **403** → `PUBLIC_BASE_URL` no coincide con el webhook.
- **Nada** → revisá el webhook en Twilio y que ngrok siga arriba.

## Cierre

Resumí en una tabla corta, sin secretos:
- el proyecto de Supabase (nombre y ref);
- el operador;
- el número de WhatsApp;
- la URL del webhook;
- el backend del agente;
- las URLs del panel (local y ngrok).

Cerrá con cómo volver a levantarlo otro día: `ngrok http 8000` y el `uvicorn`.

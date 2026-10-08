-- ============================================================================
-- claude-whatsapp-skills — esquema Supabase / Postgres
--
-- Pegá este archivo entero en el SQL Editor de Supabase y ejecutalo.
-- Es idempotente: podés correrlo varias veces sin romper nada.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ── Capa 3: clientes ────────────────────────────────────────────────────────
create table if not exists public.clients (
    id                 uuid primary key default gen_random_uuid(),
    phone              text not null unique,
    name               text,
    company            text,
    -- session_id devuelto por `claude -p`, para continuar la conversación con
    -- --resume en el backend cli. Queda null en modo messages_api.
    claude_session_id  text,
    metadata           jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create index if not exists clients_name_lower_idx on public.clients (lower(name));

-- ── Capa 3: historial de mensajes ───────────────────────────────────────────
create table if not exists public.messages (
    id          uuid primary key default gen_random_uuid(),
    client_id   uuid references public.clients (id) on delete cascade,
    direction   text not null check (direction in ('inbound', 'outbound')),
    body        text not null,
    -- Clave de idempotencia. Twilio reintenta ante cualquier respuesta no-2xx;
    -- sin este unique, un reintento crea el ticket dos veces.
    twilio_sid  text unique,
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists messages_client_created_idx
    on public.messages (client_id, created_at desc);

-- ── Skill 2: tickets ────────────────────────────────────────────────────────
create table if not exists public.tickets (
    id          uuid primary key default gen_random_uuid(),
    -- Número corto y legible para decirle al cliente por WhatsApp ("ticket 4412")
    ref         bigint generated always as identity (start with 4000),
    client_id   uuid not null references public.clients (id) on delete cascade,
    type        text not null default 'general'
                check (type in ('general', 'quotation', 'support', 'billing', 'escalation')),
    status      text not null default 'open'
                check (status in ('open', 'in_progress', 'waiting_client', 'resolved', 'closed')),
    priority    text not null default 'normal'
                check (priority in ('low', 'normal', 'high', 'urgent')),
    subject     text,
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists tickets_client_status_idx on public.tickets (client_id, status);
create unique index if not exists tickets_ref_idx on public.tickets (ref);

-- ── Skill 3: knowledge base (full-text search, sin embeddings) ──────────────
create table if not exists public.knowledge_docs (
    id          uuid primary key default gen_random_uuid(),
    title       text not null,
    source      text,
    content     text not null,
    metadata    jsonb not null default '{}'::jsonb,
    -- Columna generada: el título pesa más que el cuerpo en el ranking.
    -- 'spanish' aplica stemming ("cotizaciones" matchea "cotización").
    fts         tsvector generated always as (
                    setweight(to_tsvector('spanish', coalesce(title, '')),   'A') ||
                    setweight(to_tsvector('spanish', coalesce(content, '')), 'B')
                ) stored,
    created_at  timestamptz not null default now()
);

create index if not exists knowledge_docs_fts_idx on public.knowledge_docs using gin (fts);

-- Skill 3 llama a esta RPC.
--
-- Dos cosas acá se aprendieron a los golpes, con el agente en producción:
--
-- 1. `websearch_to_tsquery` une los términos con AND. "lista de precios
--    actuales" produce 'list' & 'preci' & 'actual', y si ningún documento dice
--    "actual" el resultado es CERO — aunque el documento correcto esté ahí y
--    matchee dos de tres términos. Por eso hay dos etapas: si la consulta
--    estricta no devuelve nada, se reintenta con OR de los lexemas y se ordena
--    por cuántos términos matchearon. El modelo se entera de cuál se usó por
--    `match_mode`.
--
-- 2. `ts_headline` devuelve FRAGMENTOS, no el documento. Con la configuración
--    anterior el modelo veía el 40% de una política de pagos, cortada a mitad
--    de oración, y respondía —correctamente— que no tenía el detalle completo.
--    Ahora se devuelve el contenido real, truncado sólo si supera max_chars, y
--    con un flag `truncated` para que el modelo sepa si le falta algo.
--
-- `confidence` sigue siendo ts_rank normalizado (32 = rank/(rank+1), rango
-- [0,1)). Está bien calibrado: un match real da entre 0.28 y 0.50.
--
-- El drop es necesario: `create or replace` no puede cambiar el tipo de retorno
-- de una función existente. Si ya corriste una versión anterior de este archivo,
-- volvé a correrlo entero — es idempotente.
drop function if exists public.search_knowledge(text, int);
drop function if exists public.search_knowledge(text, int, int);

create or replace function public.search_knowledge(
    query_text  text,
    match_limit int default 5,
    max_chars   int default 1500
)
returns table (
    id            uuid,
    title         text,
    source        text,
    content       text,
    truncated     boolean,
    matched_terms int,
    query_terms   int,
    confidence    real,
    match_mode    text
)
language plpgsql
stable
as $fn$
declare
    strict_q tsquery;
    loose_q  tsquery;
    used_q   tsquery;
    mode     text := 'all_terms';
    total    int;
begin
    strict_q := websearch_to_tsquery('spanish', query_text);

    -- OR de todos los lexemas de la consulta. Config 'simple' porque los
    -- lexemas ya vienen stemmeados por la config 'spanish' de arriba.
    select to_tsquery('simple', string_agg(quote_literal(l.lexeme), ' | ')), count(*)
      into loose_q, total
      from unnest(to_tsvector('spanish', query_text)) as l;

    used_q := strict_q;
    if strict_q is null
       or not exists (select 1 from public.knowledge_docs d where d.fts @@ strict_q)
    then
        used_q := loose_q;
        mode   := 'any_term';
    end if;

    if used_q is null then
        return;  -- la consulta era toda stopwords
    end if;

    return query
    select d.id,
           d.title,
           d.source,
           left(d.content, max_chars),
           char_length(d.content) > max_chars,
           (select count(*)::int
              from unnest(to_tsvector('spanish', query_text)) as t
             where d.fts @@ to_tsquery('simple', quote_literal(t.lexeme))),
           coalesce(total, 0),
           ts_rank(d.fts, used_q, 32),
           mode
      from public.knowledge_docs d
     where d.fts @@ used_q
     -- Primero cuántos términos matchearon, después el rank. Posicional porque
     -- los alias chocarían con las columnas de la tabla.
     order by 6 desc, 8 desc
     limit greatest(1, least(match_limit, 20));
end;
$fn$;

-- ── Skill 4: escalados a humano ─────────────────────────────────────────────
create table if not exists public.escalations (
    id          uuid primary key default gen_random_uuid(),
    client_id   uuid references public.clients (id) on delete cascade,
    ticket_id   uuid references public.tickets (id) on delete set null,
    reason      text not null,
    summary     text,
    context     jsonb not null default '{}'::jsonb,
    status      text not null default 'pending'
                check (status in ('pending', 'claimed', 'resolved')),
    created_at  timestamptz not null default now()
);

create index if not exists escalations_status_idx on public.escalations (status, created_at desc);

-- ── updated_at automático ───────────────────────────────────────────────────
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $fn$
begin
    new.updated_at = now();
    return new;
end;
$fn$;

do $do$
declare t text;
begin
    foreach t in array array['clients', 'tickets'] loop
        execute format('drop trigger if exists %I_touch on public.%I', t, t);
        execute format(
            'create trigger %I_touch before update on public.%I
             for each row execute function public.touch_updated_at()', t, t);
    end loop;
end;
$do$;

-- ── RLS ─────────────────────────────────────────────────────────────────────
-- El agente usa la key secreta, que hace bypass de RLS. El panel usa la
-- publishable con el login del operador, y sólo lee lo que permiten las
-- políticas de abajo (sección CRM).
alter table public.clients        enable row level security;
alter table public.messages       enable row level security;
alter table public.tickets        enable row level security;
alter table public.escalations    enable row level security;
alter table public.knowledge_docs enable row level security;

-- ── Datos de ejemplo para la KB (borralos y cargá los tuyos) ────────────────
--
-- Escribí tus documentos con los acentos puestos. No es cosmético: el stemmer
-- español los necesita para reconocer sufijos, y sin ellos el matching empeora.
--
--     to_tsvector('spanish', 'aprobación')  ->  'aprob'
--     to_tsvector('spanish', 'aprobacion')  ->  'aprobacion'   (no stemea)
--
-- O sea que un documento sin acentos no matchea una consulta bien escrita.
-- Medido: 'aprobación crediticia' caía de 2/2 términos a 1/2.
insert into public.knowledge_docs (title, source, content)
select * from (values
    ('Lista de precios 2026',
     'pricelist_2026.pdf',
     'Precios vigentes 2026. El producto X tiene un precio unitario de USD 12 para ' ||
     'compras menores a 100 unidades. Entre 100 y 499 unidades el precio unitario es ' ||
     'USD 10. El producto Y cuesta USD 25 por unidad. Todas las cotizaciones tienen ' ||
     'una validez de 15 días corridos desde su emisión.'),
    ('Descuentos por volumen',
     'bulk_pricing.md',
     'Para pedidos de 500 unidades o más del producto X aplicamos un descuento por ' ||
     'volumen del 20 por ciento sobre el precio de lista, lo que deja el unitario en ' ||
     'USD 9.60. Pedidos mayores a 2000 unidades requieren aprobación comercial y se ' ||
     'cotizan caso por caso. El plazo de entrega para pedidos de volumen es de 10 a ' ||
     '15 días hábiles.'),
    ('Formas de pago y facturación',
     'payments_policy.md',
     'Aceptamos tarjeta de crédito, transferencia bancaria y débito automático. Para ' ||
     'clientes nuevos el primer pedido se abona 100 por ciento por adelantado. A ' ||
     'partir del segundo pedido ofrecemos cuenta corriente a 30 días previa ' ||
     'aprobación crediticia. Emitimos factura A y factura B.')
) as seed(title, source, content)
where not exists (select 1 from public.knowledge_docs);

-- ============================================================================
-- CRM: bandeja, estado bot/humano por conversación y operadores
-- ============================================================================

-- ── Teléfono en cada mensaje ────────────────────────────────────────────────
-- Un número que todavía no es cliente deja mensajes con client_id NULL. Sin el
-- teléfono en la fila, esos mensajes no aparecen en ninguna bandeja.
alter table public.messages add column if not exists phone text;

update public.messages m
   set phone = c.phone
  from public.clients c
 where m.client_id = c.id
   and m.phone is null;

create index if not exists messages_phone_created_idx
    on public.messages (phone, created_at desc);

-- ── Conversaciones ──────────────────────────────────────────────────────────
-- El estado vive acá y no en el panel: el que tiene que leerlo es el webhook,
-- antes de llamar a Claude.
--   bot          el agente atiende
--   needs_human  el agente escaló ("pidió humano"); sigue contestando
--   human        una persona tomó el chat; el agente no contesta
create table if not exists public.conversations (
    phone            text primary key,
    status           text not null default 'bot'
                     check (status in ('bot', 'needs_human', 'human')),
    -- Lo que el humano acordó con el cliente. Entra al contexto del agente
    -- cuando le devuelven la conversación, para que no lo contradiga.
    handoff_note     text,
    last_message_at  timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index if not exists conversations_last_message_idx
    on public.conversations (last_message_at desc);

drop trigger if exists conversations_touch on public.conversations;
create trigger conversations_touch before update on public.conversations
    for each row execute function public.touch_updated_at();

insert into public.conversations (phone, last_message_at)
select phone, max(created_at)
  from public.messages
 where phone is not null
 group by phone
on conflict (phone) do nothing;

-- ── Operadores ──────────────────────────────────────────────────────────────
-- Tener cuenta en Supabase Auth no alcanza para leer chats de clientes: hay que
-- estar en esta tabla. Alta: insert into operators (user_id) values ('<uuid>');
create table if not exists public.operators (
    user_id     uuid primary key references auth.users (id) on delete cascade,
    created_at  timestamptz not null default now()
);

alter table public.conversations enable row level security;
alter table public.operators     enable row level security;

create or replace function public.is_operator()
returns boolean language sql stable security definer set search_path = public as $fn$
    select exists (select 1 from public.operators where user_id = auth.uid());
$fn$;

-- El panel sólo lee. Toda escritura pasa por el agente con la service_role key.
do $do$
declare t text;
begin
    foreach t in array array['conversations', 'messages', 'clients', 'escalations'] loop
        execute format('drop policy if exists operators_read on public.%I', t);
        execute format(
            'create policy operators_read on public.%I for select to authenticated
             using (public.is_operator())', t);
    end loop;
end;
$do$;

-- ── Realtime ────────────────────────────────────────────────────────────────
do $do$
declare t text;
begin
    foreach t in array array['conversations', 'messages'] loop
        if not exists (
            select 1 from pg_publication_tables
             where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t
        ) then
            execute format('alter publication supabase_realtime add table public.%I', t);
        end if;
    end loop;
end;
$do$;

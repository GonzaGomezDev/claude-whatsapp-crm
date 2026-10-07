-- ============================================================================
-- claude-whatsapp-skills — volver a foja cero
--
-- `schema.sql` es idempotente a propósito: usa `create table if not exists`, así
-- que correrlo de nuevo NO borra nada. Eso está bien para actualizar la
-- estructura sin perder datos, pero es lo contrario de lo que querés antes de
-- grabar una toma o de probar un cambio de prompt.
--
-- Este archivo es el escape. Elegí un nivel y corré ESE bloque.
-- ============================================================================


-- ── Nivel 1: sólo cortar la memoria del agente ──────────────────────────────
--
-- Corré esto si cambiaste un SKILL.md o el system prompt y el agente sigue
-- comportándose como antes.
--
-- El motivo: guardamos el session_id de Claude Code y lo reusamos con --resume.
-- La sesión arrastra TODA la conversación anterior, así que el modelo se lee a
-- sí mismo diciendo "eso ya está en el ticket 4001" y lo repite. Cambiar el
-- prompt no borra ese historial. Esto sí.
--
-- No pierde ningún dato: clientes, tickets y mensajes quedan intactos.

update public.clients set claude_session_id = null;


-- ── Nivel 2: vaciar el estado operativo ─────────────────────────────────────
--
-- Clientes, conversaciones, tickets, pagos y escalados. La knowledge base NO se
-- toca: es contenido, no estado.
--
-- `restart identity` devuelve el contador de tickets a 4000, así que la próxima
-- cotización vuelve a ser el ticket 4000. Útil para que dos tomas del video den
-- los mismos números.
--
-- Descomentá para usar:

-- truncate table
--     public.escalations,
--     public.payments,
--     public.tickets,
--     public.messages,
--     public.conversations,
--     public.clients
-- restart identity cascade;


-- ── Nivel 3: recargar también la knowledge base ─────────────────────────────
--
-- Borrá los documentos y volvé a correr `schema.sql`: el insert de semillas
-- tiene un `where not exists`, así que sólo repuebla si la tabla quedó vacía.
--
-- Descomentá para usar:

-- delete from public.knowledge_docs;


-- ── Verificación ────────────────────────────────────────────────────────────

select 'clients'        as tabla, count(*) as filas from public.clients
union all select 'messages',       count(*) from public.messages
union all select 'conversations',  count(*) from public.conversations
union all select 'tickets',        count(*) from public.tickets
union all select 'payments',       count(*) from public.payments
union all select 'escalations',    count(*) from public.escalations
union all select 'knowledge_docs', count(*) from public.knowledge_docs
order by tabla;

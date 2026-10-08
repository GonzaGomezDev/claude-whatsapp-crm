import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { agent, failed, supabase } from '../supabase'
import { Messages } from '../components/Messages'
import { href } from '../lib/route'
import { useTeam } from '../lib/team'
import {
  STATUS_LABEL,
  TICKET_STATUS,
  TICKET_TYPE,
  when,
  type Client,
  type ClientOverview,
  type Escalation,
  type Message,
  type Note,
  type Ticket,
} from '../lib/types'

const PAGE = 50

export default function ClientDetail({ id }: { id: string }) {
  const { me, nameOf } = useTeam()
  const [client, setClient] = useState<Client | null>(null)
  const [stats, setStats] = useState<ClientOverview | null>(null)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [escalations, setEscalations] = useState<Escalation[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [summarizing, setSummarizing] = useState(false)

  const load = useCallback(async () => {
    const [c, s, t, e, n] = await Promise.all([
      supabase.from('clients').select('*').eq('id', id).single(),
      supabase.from('client_overview').select('*').eq('id', id).single(),
      supabase.from('tickets').select('*').eq('client_id', id).order('created_at', { ascending: false }),
      supabase.from('escalations').select('*').eq('client_id', id).order('created_at', { ascending: false }),
      supabase.from('notes').select('*').eq('client_id', id).order('created_at', { ascending: false }),
    ])
    setError(failed(c) ?? '')
    setClient(c.data)
    setStats(s.data)
    setTickets(t.data ?? [])
    setEscalations(e.data ?? [])
    setNotes(n.data ?? [])
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const text = (k: string) => String(data.get(k)).trim() || null
    const tags = String(data.get('tags'))
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    const err = failed(
      await supabase
        .from('clients')
        .update({ name: text('name'), company: text('company'), email: text('email'), tags })
        .eq('id', id),
    )
    setError(err ?? '')
    setSaved(!err)
    if (!err) load()
  }

  async function addNote(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const body = String(new FormData(form).get('body')).trim()
    if (!body) return
    const err = failed(await supabase.from('notes').insert({ client_id: id, body, author_id: me.user_id }))
    setError(err ?? '')
    if (!err) {
      form.reset()
      load()
    }
  }

  async function summarize() {
    setSummarizing(true)
    setError('')
    try {
      await agent(`/clients/${id}/summary`)
      await load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSummarizing(false)
    }
  }

  if (!client) return <div className="page">{error ? <p className="error">{error}</p> : null}</div>

  return (
    <div className="page">
      <div className="toolbar">
        <a className="link" href={href('clientes')}>← Clientes</a>
        <h1>{client.name || client.phone}</h1>
        {stats?.status && <span className={`tag ${stats.status}`}>{STATUS_LABEL[stats.status]}</span>}
        {stats?.assigned_to && <span className="muted">{nameOf(stats.assigned_to)}</span>}
        <a className="button" href={href('bandeja', client.phone)}>Abrir en bandeja</a>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="stats">
        <Stat label="Contactos" value={stats?.contact_days ?? 0} hint="Días distintos en que escribió" />
        <Stat label="Mensajes" value={stats?.message_count ?? 0} />
        <Stat label="Primer contacto" value={when(stats?.first_contact)} />
        <Stat label="Último contacto" value={when(stats?.last_contact)} />
        <Stat label="Tickets abiertos" value={stats?.open_tickets ?? 0} />
        <Stat label="Escalados" value={stats?.escalations ?? 0} />
      </div>

      <div className="columns">
        <section className="card">
          <h2>Datos</h2>
          <form className="fields" onSubmit={save} onChange={() => setSaved(false)}>
            <label>
              Nombre <input name="name" defaultValue={client.name ?? ''} />
            </label>
            <label>
              Empresa <input name="company" defaultValue={client.company ?? ''} />
            </label>
            <label>
              Email <input name="email" type="email" defaultValue={client.email ?? ''} />
            </label>
            <label>
              Teléfono <input value={client.phone} disabled />
            </label>
            <label>
              Tags <input name="tags" defaultValue={client.tags.join(', ')} placeholder="mayorista, vip" />
            </label>
            <div>
              <button>Guardar</button> {saved && <span className="muted">Guardado</span>}
            </div>
          </form>
        </section>

        <section className="card">
          <div className="toolbar">
            <h2>Resumen IA</h2>
            <button disabled={summarizing} onClick={summarize}>
              {summarizing ? 'Generando…' : client.ai_summary ? 'Actualizar' : 'Generar'}
            </button>
          </div>
          {client.ai_summary ? (
            <>
              <p className="prewrap">{client.ai_summary}</p>
              <small className="muted">Generado {when(client.ai_summary_at)}</small>
            </>
          ) : (
            <p className="muted">Claude lee el historial, los tickets y los escalados y resume quién es y qué necesita.</p>
          )}
        </section>
      </div>

      <section className="card">
        <h2>Por qué nos escribió</h2>
        {tickets.length === 0 && escalations.length === 0 && <p className="muted">Sin tickets ni escalados.</p>}
        <ul className="plain">
          {tickets.map((t) => (
            <li key={t.id}>
              <a href={href('tickets', String(t.ref))}>#{t.ref}</a> · {TICKET_TYPE[t.type] ?? t.type} ·{' '}
              {t.subject || '(sin asunto)'} <span className="muted">· {TICKET_STATUS[t.status]} · {when(t.created_at)}</span>
            </li>
          ))}
          {escalations.map((e) => (
            <li key={e.id}>
              Escalado ({e.reason}) · {e.summary || '(sin resumen)'}{' '}
              <span className="muted">· {e.status} · {when(e.created_at)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>Notas</h2>
        <form className="row-form" onSubmit={addNote}>
          <textarea name="body" rows={2} placeholder="Nota interna: el cliente no la ve" required />
          <button>Agregar</button>
        </form>
        <ul className="plain">
          {notes.map((n) => (
            <li key={n.id}>
              <p className="prewrap">{n.body}</p>
              <small className="muted">
                {nameOf(n.author_id)} · {when(n.created_at)}
              </small>
            </li>
          ))}
          {(client.metadata?.notes ?? []).map((n, i) => (
            <li key={`bot-${i}`}>
              <p className="prewrap">{n}</p>
              <small className="muted">Anotado por el bot</small>
            </li>
          ))}
        </ul>
      </section>

      <History phone={client.phone} />
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  )
}

function History({ phone }: { phone: string }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const [hasMore, setHasMore] = useState(false)

  useEffect(() => {
    let q = supabase
      .from('messages')
      .select('*')
      .eq('phone', phone)
      .order('created_at', { ascending: false })
      .limit(limit + 1)
    if (search.trim()) q = q.ilike('body', `%${search.trim()}%`)
    q.then(({ data }) => {
      const rows = data ?? []
      setHasMore(rows.length > limit)
      setMessages(rows.slice(0, limit).reverse())
    })
  }, [phone, search, limit])

  return (
    <section className="card">
      <div className="toolbar">
        <h2>Historial</h2>
        <input
          type="search"
          placeholder="Buscar en los mensajes"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setLimit(PAGE)
          }}
        />
      </div>
      {hasMore && (
        <button className="link" onClick={() => setLimit(limit + PAGE)}>
          Cargar mensajes anteriores
        </button>
      )}
      <Messages messages={messages} full />
      {messages.length === 0 && <p className="muted">Sin mensajes{search && ' que coincidan'}.</p>}
    </section>
  )
}

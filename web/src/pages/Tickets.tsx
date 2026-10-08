import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { failed, supabase } from '../supabase'
import { go, href } from '../lib/route'
import { useTeam } from '../lib/team'
import {
  OPEN_TICKET,
  PRIORITY,
  TICKET_STATUS,
  TICKET_TYPE,
  when,
  type Note,
  type Ticket,
  type TicketStatus,
} from '../lib/types'

type Filters = { status: string; type: string; priority: string; mine: boolean; q: string }

export default function Tickets({ selectedRef }: { selectedRef?: string }) {
  const { me, nameOf } = useTeam()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [filters, setFilters] = useState<Filters>({ status: 'open', type: '', priority: '', mine: false, q: '' })
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    // ponytail: hasta 500 tickets por consulta; con más, paginar.
    let q = supabase
      .from('tickets')
      .select('*, clients(name, phone)')
      .order('created_at', { ascending: false })
      .limit(500)
    if (filters.status === 'open') q = q.in('status', OPEN_TICKET)
    else if (filters.status) q = q.eq('status', filters.status)
    if (filters.type) q = q.eq('type', filters.type)
    if (filters.priority) q = q.eq('priority', filters.priority)
    if (filters.mine) q = q.eq('assigned_to', me.user_id)
    const result = await q
    setError(failed(result) ?? '')
    setTickets(result.data ?? [])
  }, [filters.status, filters.type, filters.priority, filters.mine, me.user_id])

  useEffect(() => {
    load()
    const channel = supabase
      .channel('tickets')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'tickets' }, load)
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [load])

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }))
  const term = filters.q.trim().toLowerCase()
  const visible = term
    ? tickets.filter((t) => String(t.ref).includes(term) || (t.subject ?? '').toLowerCase().includes(term))
    : tickets
  const current = tickets.find((t) => String(t.ref) === selectedRef)

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Tickets</h1>
        <input type="search" placeholder="Buscar por número o asunto" value={filters.q} onChange={(e) => set({ q: e.target.value })} />
        <select value={filters.status} onChange={(e) => set({ status: e.target.value })} aria-label="Estado">
          <option value="open">Abiertos</option>
          <option value="">Todos los estados</option>
          {Object.entries(TICKET_STATUS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select value={filters.type} onChange={(e) => set({ type: e.target.value })} aria-label="Tipo">
          <option value="">Todos los tipos</option>
          {Object.entries(TICKET_TYPE).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select value={filters.priority} onChange={(e) => set({ priority: e.target.value })} aria-label="Prioridad">
          <option value="">Toda prioridad</option>
          {Object.entries(PRIORITY).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={filters.mine} onChange={(e) => set({ mine: e.target.checked })} /> Míos
        </label>
      </div>
      {error && <p className="error">{error}</p>}

      <div className={current ? 'split' : ''}>
        <table className="list clickable">
          <thead>
            <tr>
              <th>#</th>
              <th>Asunto</th>
              <th>Cliente</th>
              <th>Tipo</th>
              <th>Prioridad</th>
              <th>Estado</th>
              <th>Asignado</th>
              <th>Creado</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.id} className={t === current ? 'active' : ''} onClick={() => go('tickets', String(t.ref))}>
                <td>{t.ref}</td>
                <td>{t.subject || '(sin asunto)'}</td>
                <td>{t.clients?.name || t.clients?.phone || '—'}</td>
                <td>{TICKET_TYPE[t.type] ?? t.type}</td>
                <td className={`prio ${t.priority}`}>{PRIORITY[t.priority] ?? t.priority}</td>
                <td>{TICKET_STATUS[t.status]}</td>
                <td>{t.assigned_to ? nameOf(t.assigned_to) : '—'}</td>
                <td>{when(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {current && <TicketDetail key={current.id} ticket={current} onChange={load} />}
      </div>
      {visible.length === 0 && <p className="muted">No hay tickets con estos filtros.</p>}
    </div>
  )
}

function TicketDetail({ ticket, onChange }: { ticket: Ticket; onChange: () => void }) {
  const { me, team, nameOf } = useTeam()
  const [notes, setNotes] = useState<Note[]>([])
  const [error, setError] = useState('')

  const loadNotes = useCallback(() => {
    supabase
      .from('notes')
      .select('*')
      .eq('ticket_id', ticket.id)
      .order('created_at', { ascending: false })
      .then(({ data }) => setNotes(data ?? []))
  }, [ticket.id])
  useEffect(loadNotes, [loadNotes])

  async function update(patch: Partial<Pick<Ticket, 'status' | 'priority' | 'assigned_to'>>) {
    const err = failed(await supabase.from('tickets').update(patch).eq('id', ticket.id))
    setError(err ?? '')
    onChange()
  }

  async function addNote(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const body = String(new FormData(form).get('body')).trim()
    if (!body) return
    const err = failed(
      await supabase.from('notes').insert({ client_id: ticket.client_id, ticket_id: ticket.id, body, author_id: me.user_id }),
    )
    setError(err ?? '')
    if (!err) {
      form.reset()
      loadNotes()
    }
  }

  return (
    <aside className="card detail">
      <div className="toolbar">
        <h2>
          #{ticket.ref} · {TICKET_TYPE[ticket.type] ?? ticket.type}
        </h2>
        <a className="link" href={href('tickets')}>Cerrar</a>
      </div>
      {error && <p className="error">{error}</p>}
      <p>
        <strong>{ticket.subject || '(sin asunto)'}</strong>
      </p>
      {ticket.metadata?.details && <p className="prewrap">{ticket.metadata.details}</p>}
      {ticket.metadata?.reason && <p className="muted">Motivo del escalado: {ticket.metadata.reason}</p>}
      <p>
        Cliente: <a href={href('clientes', ticket.client_id)}>{ticket.clients?.name || ticket.clients?.phone}</a>
        <br />
        <small className="muted">
          Creado {when(ticket.created_at)} · actualizado {when(ticket.updated_at)}
        </small>
      </p>
      <div className="fields">
        <label>
          Estado
          <select value={ticket.status} onChange={(e) => update({ status: e.target.value as TicketStatus })}>
            {Object.entries(TICKET_STATUS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Prioridad
          <select value={ticket.priority} onChange={(e) => update({ priority: e.target.value })}>
            {Object.entries(PRIORITY).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Asignado
          <select value={ticket.assigned_to ?? ''} onChange={(e) => update({ assigned_to: e.target.value || null })}>
            <option value="">Sin asignar</option>
            {team.filter((o) => o.active).map((o) => (
              <option key={o.user_id} value={o.user_id}>{o.name || o.email}</option>
            ))}
          </select>
        </label>
      </div>
      {['resolved', 'closed'].includes(ticket.status) || (
        <p className="muted">Al resolverlo o cerrarlo se resuelven también sus escalados.</p>
      )}
      <h3>Notas</h3>
      <form className="row-form" onSubmit={addNote}>
        <textarea name="body" rows={2} placeholder="Nota interna" required />
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
        {ticket.metadata?.last_note && (
          <li>
            <p className="prewrap">{ticket.metadata.last_note}</p>
            <small className="muted">Anotado por el bot</small>
          </li>
        )}
      </ul>
    </aside>
  )
}

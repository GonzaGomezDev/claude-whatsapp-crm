import { useEffect, useState, type FormEvent } from 'react'
import { agent, failed, supabase } from '../supabase'
import { Messages } from '../components/Messages'
import { go, href } from '../lib/route'
import { useTeam } from '../lib/team'
import { STATUS_LABEL, type Conversation, type Message } from '../lib/types'

const WINDOW_MS = 24 * 60 * 60 * 1000

type Filter = 'all' | 'mine' | 'unassigned' | 'needs_human'
const FILTERS: Record<Filter, string> = {
  all: 'Todos',
  mine: 'Míos',
  unassigned: 'Sin asignar',
  needs_human: 'Pidió humano',
}

type ClientRef = { id: string; name: string | null }

export default function Inbox({ selectedPhone }: { selectedPhone?: string }) {
  const { me, nameOf } = useTeam()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [clients, setClients] = useState<Record<string, ClientRef>>({})
  const [filter, setFilter] = useState<Filter>('all')

  useEffect(() => {
    async function load() {
      const [convs, cl] = await Promise.all([
        supabase.from('conversations').select('*').order('last_message_at', { ascending: false }),
        supabase.from('clients').select('id, phone, name'),
      ])
      setConversations(convs.data ?? [])
      setClients(Object.fromEntries((cl.data ?? []).map((c) => [c.phone, { id: c.id, name: c.name }])))
    }
    load()
    // ponytail: recarga la lista entera en cada cambio; alcanza para cientos de conversaciones.
    const channel = supabase
      .channel('conversations')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations' }, load)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'clients' }, load)
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  const visible = conversations.filter((c) => {
    if (filter === 'mine') return c.assigned_to === me.user_id
    if (filter === 'unassigned') return !c.assigned_to
    if (filter === 'needs_human') return c.status === 'needs_human'
    return true
  })
  const current = conversations.find((c) => c.phone === selectedPhone)

  return (
    <div className={`inbox ${current ? 'has-selection' : ''}`}>
      <aside>
        <div className="tabs">
          {(Object.keys(FILTERS) as Filter[]).map((f) => (
            <button key={f} className={filter === f ? 'active' : ''} onClick={() => setFilter(f)}>
              {FILTERS[f]}
            </button>
          ))}
        </div>
        <ul>
          {visible.map((c) => (
            <li key={c.phone}>
              <a className={c.phone === selectedPhone ? 'active' : ''} href={href('bandeja', c.phone)}>
                <span className="who">{clients[c.phone]?.name ?? c.phone}</span>
                <span className={`tag ${c.status}`}>{STATUS_LABEL[c.status]}</span>
                <time>
                  {new Date(c.last_message_at).toLocaleString()}
                  {c.assigned_to && ` · ${nameOf(c.assigned_to)}`}
                </time>
              </a>
            </li>
          ))}
          {visible.length === 0 && <li className="empty">No hay conversaciones acá.</li>}
        </ul>
      </aside>
      {current ? (
        <Chat conversation={current} client={clients[current.phone]} />
      ) : (
        <main className="placeholder">Elegí una conversación.</main>
      )}
    </div>
  )
}

function Chat({ conversation, client }: { conversation: Conversation; client?: ClientRef }) {
  const { phone, status, assigned_to } = conversation
  const { me, team, nameOf, isAdmin } = useTeam()
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [returning, setReturning] = useState(false)
  const [error, setError] = useState('')

  const takenByOther = !!assigned_to && assigned_to !== me.user_id && !isAdmin

  async function act(action: string, body?: object) {
    setBusy(true)
    setError('')
    try {
      await agent(`/conversations/${encodeURIComponent(phone)}/${action}`, body)
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function giveBack(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const note = String(new FormData(e.currentTarget).get('note')).trim()
    if (await act('return', { note })) setReturning(false)
  }

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const text = String(new FormData(form).get('text')).trim()
    if (text && (await act('reply', { text }))) form.reset()
  }

  async function createClient() {
    const result = await supabase.from('clients').insert({ phone }).select('id').single()
    const err = failed(result)
    if (err || !result.data) setError(err ?? 'No se pudo crear el cliente.')
    else go('clientes', result.data.id)
  }

  // La ventana de 24 h corre desde el último mensaje del cliente. El agente la vuelve a chequear al enviar.
  const lastInbound = messages.findLast((m) => m.direction === 'inbound')
  const windowOpen = !!lastInbound && Date.now() - new Date(lastInbound.created_at).getTime() < WINDOW_MS

  useEffect(() => {
    setMessages([])
    setError('')
    setReturning(false)
    supabase
      .from('messages')
      .select('*')
      .eq('phone', phone)
      .order('created_at', { ascending: false })
      .limit(200)
      .then(({ data }) => setMessages((data ?? []).reverse()))
    // Se filtra acá y no en la suscripción: el "+" del teléfono no es seguro en un filtro de Realtime.
    const channel = supabase
      .channel(`messages:${phone}`)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages' }, (payload) => {
        const m = payload.new as Message
        if (m.phone === phone) setMessages((prev) => [...prev, m])
      })
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [phone])

  return (
    <main className="chat">
      <header>
        <a className="link back" href={href('bandeja')}>←</a>
        <div>
          <strong>{client?.name ?? phone}</strong>
          <small>
            {client?.name && `${phone} · `}
            {client ? <a href={href('clientes', client.id)}>Ver ficha</a> : (
              <button className="link inline" onClick={createClient}>Crear cliente</button>
            )}
          </small>
        </div>
        <span className={`tag ${status}`}>{STATUS_LABEL[status]}</span>
        {isAdmin ? (
          <select
            value={assigned_to ?? ''}
            disabled={busy}
            onChange={(e) => act('assign', { user_id: e.target.value || null })}
            aria-label="Asignado a"
          >
            <option value="">Sin asignar</option>
            {team.filter((o) => o.active).map((o) => (
              <option key={o.user_id} value={o.user_id}>{o.name || o.email}</option>
            ))}
          </select>
        ) : (
          assigned_to && <span className="muted">{nameOf(assigned_to)}</span>
        )}
        {takenByOther ? null : status === 'human' ? (
          <button disabled={busy || returning} onClick={() => setReturning(true)}>Devolver a la IA</button>
        ) : (
          <button disabled={busy} onClick={() => act('take')}>Tomar chat</button>
        )}
      </header>
      {error && <p className="error banner">{error}</p>}
      {returning && status === 'human' && (
        <form className="handoff" onSubmit={giveBack}>
          <label htmlFor="note">¿Qué acordaste con el cliente? La IA lo va a respetar.</label>
          <textarea id="note" name="note" rows={2} placeholder="Ej.: le prometí envío gratis en el próximo pedido" />
          <div>
            <button type="button" className="link" onClick={() => setReturning(false)}>Cancelar</button>
            <button disabled={busy}>Devolver</button>
          </div>
        </form>
      )}
      {/* column-reverse deja el scroll pegado abajo sin JS */}
      <div className="messages">
        <Messages messages={messages} />
      </div>
      {status === 'human' && !takenByOther &&
        (windowOpen ? (
          <form className="composer" onSubmit={send}>
            <textarea name="text" rows={2} placeholder="Escribile al cliente" required />
            <button disabled={busy}>Enviar</button>
          </form>
        ) : (
          <p className="composer closed">
            La ventana de 24 h está cerrada: el cliente no escribe hace más de un día y WhatsApp solo acepta
            una plantilla aprobada.
          </p>
        ))}
      {takenByOther && <p className="composer closed">Este chat lo tiene {nameOf(assigned_to)}.</p>}
    </main>
  )
}

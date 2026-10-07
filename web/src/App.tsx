import { useEffect, useState, type FormEvent } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabase'

type Status = 'bot' | 'needs_human' | 'human'

type Conversation = {
  phone: string
  status: Status
  handoff_note: string | null
  last_message_at: string
}

type Message = {
  id: string
  phone: string | null
  direction: 'inbound' | 'outbound'
  body: string
  created_at: string
  metadata: { source?: string }
}

const LABEL: Record<Status, string> = { bot: 'IA', needs_human: 'Pidió humano', human: 'Humano' }

export default function App() {
  const [session, setSession] = useState<Session | null>(null)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s))
    return () => data.subscription.unsubscribe()
  }, [])

  return session ? <Inbox /> : <Login />
}

function Login() {
  const [error, setError] = useState('')

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const { error } = await supabase.auth.signInWithPassword({
      email: String(form.get('email')),
      password: String(form.get('password')),
    })
    setError(error?.message ?? '')
  }

  return (
    <form className="login" onSubmit={submit}>
      <h1>Bandeja</h1>
      <input name="email" type="email" placeholder="Email" autoComplete="username" required />
      <input name="password" type="password" placeholder="Contraseña" autoComplete="current-password" required />
      <button>Entrar</button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

function Inbox() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [names, setNames] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      const [convs, clients] = await Promise.all([
        supabase.from('conversations').select('*').order('last_message_at', { ascending: false }),
        supabase.from('clients').select('phone, name'),
      ])
      setConversations(convs.data ?? [])
      setNames(Object.fromEntries((clients.data ?? []).filter((c) => c.name).map((c) => [c.phone, c.name])))
    }
    load()
    // ponytail: recarga la lista entera en cada cambio; alcanza para cientos de conversaciones.
    const channel = supabase
      .channel('conversations')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations' }, load)
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  const current = conversations.find((c) => c.phone === selected)

  return (
    <div className={`inbox ${current ? 'has-selection' : ''}`}>
      <aside>
        <header>
          <h1>Bandeja</h1>
          <button className="link" onClick={() => supabase.auth.signOut()}>Salir</button>
        </header>
        <ul>
          {conversations.map((c) => (
            <li key={c.phone}>
              <button className={c.phone === selected ? 'active' : ''} onClick={() => setSelected(c.phone)}>
                <span className="who">{names[c.phone] ?? c.phone}</span>
                <span className={`tag ${c.status}`}>{LABEL[c.status]}</span>
                <time>{new Date(c.last_message_at).toLocaleString()}</time>
              </button>
            </li>
          ))}
          {conversations.length === 0 && <li className="empty">Todavía no hay conversaciones.</li>}
        </ul>
      </aside>
      {current ? (
        <Chat conversation={current} name={names[current.phone]} onBack={() => setSelected(null)} />
      ) : (
        <main className="placeholder">Elegí una conversación.</main>
      )}
    </div>
  )
}

function Chat({ conversation, name, onBack }: { conversation: Conversation; name?: string; onBack: () => void }) {
  const { phone, status } = conversation
  const [messages, setMessages] = useState<Message[]>([])

  useEffect(() => {
    setMessages([])
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
        <button className="link back" onClick={onBack}>←</button>
        <div>
          <strong>{name ?? phone}</strong>
          {name && <small>{phone}</small>}
        </div>
        <span className={`tag ${status}`}>{LABEL[status]}</span>
      </header>
      {/* column-reverse deja el scroll pegado abajo sin JS */}
      <div className="messages">
        <ol>
        {messages.map((m) => (
          <li key={m.id} className={m.direction}>
            {m.direction === 'outbound' && <small>{m.metadata?.source === 'operator' ? 'Humano' : 'IA'}</small>}
            <p>{m.body}</p>
            <time>{new Date(m.created_at).toLocaleTimeString()}</time>
          </li>
        ))}
        </ol>
      </div>
    </main>
  )
}

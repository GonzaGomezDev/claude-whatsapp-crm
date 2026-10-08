import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabase'
import { href, useRoute } from './lib/route'
import { TeamContext } from './lib/team'
import type { Operator } from './lib/types'
import Inbox from './pages/Inbox'
import Clients from './pages/Clients'
import ClientDetail from './pages/ClientDetail'
import Tickets from './pages/Tickets'
import Knowledge from './pages/Knowledge'
import Users from './pages/Users'

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s))
    return () => data.subscription.unsubscribe()
  }, [])

  if (session === undefined) return null
  return session ? <Shell userId={session.user.id} /> : <Login />
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
      <h1>CRM de WhatsApp</h1>
      <input name="email" type="email" placeholder="Email" autoComplete="username" required />
      <input name="password" type="password" placeholder="Contraseña" autoComplete="current-password" required />
      <button>Entrar</button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

const NAV = [
  { path: 'bandeja', label: 'Bandeja', admin: false },
  { path: 'clientes', label: 'Clientes', admin: false },
  { path: 'tickets', label: 'Tickets', admin: false },
  { path: 'conocimiento', label: 'Conocimiento', admin: true },
  { path: 'usuarios', label: 'Usuarios', admin: true },
]

function Shell({ userId }: { userId: string }) {
  const [team, setTeam] = useState<Operator[] | null>(null)
  const [section = 'bandeja', param] = useRoute()

  const reloadTeam = useCallback(() => {
    supabase
      .from('operators')
      .select('user_id, name, email, role, active')
      .order('name')
      .then(({ data }) => setTeam(data ?? []))
  }, [])
  useEffect(reloadTeam, [reloadTeam])

  if (team === null) return null
  const me = team.find((o) => o.user_id === userId && o.active)
  if (!me) {
    // RLS sólo deja leer operators a un operador activo: si no está, no hay acceso.
    return (
      <div className="login">
        <h1>Sin acceso</h1>
        <p>Este usuario no es operador o está desactivado. Pedile acceso a un admin.</p>
        <button onClick={() => supabase.auth.signOut()}>Salir</button>
      </div>
    )
  }

  const isAdmin = me.role === 'admin'
  const page = (() => {
    switch (section) {
      case 'clientes':
        return param ? <ClientDetail key={param} id={param} /> : <Clients />
      case 'tickets':
        return <Tickets selectedRef={param} />
      case 'conocimiento':
        return isAdmin ? <Knowledge /> : null
      case 'usuarios':
        return isAdmin ? <Users /> : null
      default:
        return <Inbox selectedPhone={param} />
    }
  })()

  return (
    <TeamContext.Provider value={{ me, team, reloadTeam }}>
      <div className="shell">
        <nav className="sidebar">
          <strong className="brand">CRM</strong>
          {NAV.filter((n) => isAdmin || !n.admin).map((n) => (
            <a key={n.path} href={href(n.path)} className={section === n.path ? 'active' : ''}>
              {n.label}
            </a>
          ))}
          <span className="me">
            {me.name || me.email}
            <small>{isAdmin ? 'Admin' : 'Agente'}</small>
          </span>
          <button className="link" onClick={() => supabase.auth.signOut()}>Salir</button>
        </nav>
        <div className="content">{page ?? <p className="placeholder">No tenés acceso a esta sección.</p>}</div>
      </div>
    </TeamContext.Provider>
  )
}

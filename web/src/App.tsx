import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { Session } from '@supabase/supabase-js'
import { Lock, MessagesSquare } from 'lucide-react'
import { supabase } from '@/supabase'
import { useRoute } from '@/lib/route'
import { TeamContext } from '@/lib/team'
import type { Operator } from '@/lib/types'
import { AppSidebar } from '@/components/AppSidebar'
import { EmptyState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Inbox from '@/pages/Inbox'
import Clients from '@/pages/Clients'
import ClientDetail from '@/pages/ClientDetail'
import Tickets from '@/pages/Tickets'
import Knowledge from '@/pages/Knowledge'
import Users from '@/pages/Users'

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
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setBusy(true)
    const { error } = await supabase.auth.signInWithPassword({
      email: String(form.get('email')),
      password: String(form.get('password')),
    })
    setBusy(false)
    setError(error ? 'El email o la contraseña no coinciden.' : '')
  }

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <span className="mb-2 inline-flex size-10 items-center justify-center rounded-lg bg-brand text-white dark:text-background">
            <MessagesSquare className="size-5" aria-hidden />
          </span>
          <CardTitle className="text-xl">Entrar al CRM</CardTitle>
          <CardDescription>Con el usuario que te dio un admin.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={submit}>
            <div className="grid gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" autoComplete="username" required />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="password">Contraseña</Label>
              <Input id="password" name="password" type="password" autoComplete="current-password" required />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button disabled={busy}>Entrar</Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}

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
      <main className="flex min-h-dvh items-center justify-center p-4">
        <Card className="w-full max-w-sm">
          <EmptyState icon={Lock} title="Sin acceso">
            Este usuario no es operador o está desactivado. Pedile acceso a un admin.
            <Button variant="outline" className="mt-4 w-full" onClick={() => supabase.auth.signOut()}>
              Salir
            </Button>
          </EmptyState>
        </Card>
      </main>
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
      <div className="flex min-h-dvh flex-col md:flex-row">
        <AppSidebar section={section} />
        <div className="min-w-0 flex-1">
          {page ?? (
            <EmptyState icon={Lock} title="Esta sección es para admins">
              Si necesitás entrar, pedíselo a un admin del equipo.
            </EmptyState>
          )}
        </div>
      </div>
    </TeamContext.Provider>
  )
}

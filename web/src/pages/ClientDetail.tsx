import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { AlertTriangle, ArrowLeft, MessagesSquare, Search, Sparkles, StickyNote, TicketIcon } from 'lucide-react'
import { toast } from 'sonner'
import { agent, failed, supabase } from '@/supabase'
import { href } from '@/lib/route'
import { useTeam } from '@/lib/team'
import {
  TICKET_TYPE,
  when,
  type Client,
  type ClientOverview,
  type Escalation,
  type Message,
  type Note,
  type Ticket,
} from '@/lib/types'
import { EmptyState } from '@/components/EmptyState'
import { InitialsAvatar } from '@/components/InitialsAvatar'
import { Messages } from '@/components/Messages'
import { Page, PageHeader } from '@/components/PageHeader'
import { StatusBadge, TicketStatusBadge } from '@/components/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const PAGE = 50

export default function ClientDetail({ id }: { id: string }) {
  const { nameOf } = useTeam()
  const [client, setClient] = useState<Client | null>(null)
  const [stats, setStats] = useState<ClientOverview | null>(null)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [escalations, setEscalations] = useState<Escalation[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [missing, setMissing] = useState(false)

  const load = useCallback(async () => {
    const [c, s, t, e, n] = await Promise.all([
      supabase.from('clients').select('*').eq('id', id).single(),
      supabase.from('client_overview').select('*').eq('id', id).single(),
      supabase.from('tickets').select('*').eq('client_id', id).order('created_at', { ascending: false }),
      supabase.from('escalations').select('*').eq('client_id', id).order('created_at', { ascending: false }),
      supabase.from('notes').select('*').eq('client_id', id).order('created_at', { ascending: false }),
    ])
    setMissing(!c.data)
    setClient(c.data)
    setStats(s.data)
    setTickets(t.data ?? [])
    setEscalations(e.data ?? [])
    setNotes(n.data ?? [])
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  if (missing)
    return (
      <Page>
        <EmptyState icon={AlertTriangle} title="No encontramos este cliente">
          <a className="text-brand hover:underline" href={href('clientes')}>
            Volver a clientes
          </a>
        </EmptyState>
      </Page>
    )
  if (!client)
    return (
      <Page>
        <Skeleton className="h-12 w-72" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-96 w-full" />
      </Page>
    )

  return (
    <Page>
      <PageHeader
        leading={
          <>
            <Button variant="ghost" size="icon" asChild>
              <a href={href('clientes')} aria-label="Volver a clientes">
                <ArrowLeft />
              </a>
            </Button>
            <InitialsAvatar name={client.name} phone={client.phone} className="size-12 text-sm" />
          </>
        }
        title={client.name || client.phone}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {client.company && <span>{client.company}</span>}
            {client.name && <span className="tabular-nums">{client.phone}</span>}
            {stats?.status && <StatusBadge status={stats.status} />}
            {stats?.assigned_to && <span>Atiende {nameOf(stats.assigned_to)}</span>}
            {client.tags.map((t) => (
              <Badge key={t} variant="secondary">
                {t}
              </Badge>
            ))}
          </span>
        }
        actions={
          <Button asChild>
            <a href={href('bandeja', client.phone)}>
              <MessagesSquare /> Abrir en bandeja
            </a>
          </Button>
        }
      />

      {/* Una sola franja de métricas: se leen juntas, no son seis tarjetas independientes. */}
      <Card className="grid grid-cols-2 gap-px overflow-hidden bg-border p-0 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Contactos" value={stats?.contact_days ?? 0} hint="Días distintos en que escribió" />
        <Stat label="Mensajes" value={stats?.message_count ?? 0} />
        <Stat label="Primer contacto" value={when(stats?.first_contact)} small />
        <Stat label="Último contacto" value={when(stats?.last_contact)} small />
        <Stat label="Tickets abiertos" value={stats?.open_tickets ?? 0} />
        <Stat label="Escalados" value={stats?.escalations ?? 0} />
      </Card>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
        <Tabs defaultValue="resumen" className="min-w-0">
          <TabsList>
            <TabsTrigger value="resumen">Resumen</TabsTrigger>
            <TabsTrigger value="historial">Historial</TabsTrigger>
            <TabsTrigger value="notas">Notas ({notes.length + (client.metadata?.notes?.length ?? 0)})</TabsTrigger>
          </TabsList>
          <TabsContent value="resumen" className="mt-4 flex flex-col gap-6">
            <Summary client={client} onDone={load} />
            <Reasons tickets={tickets} escalations={escalations} />
          </TabsContent>
          <TabsContent value="historial" className="mt-4">
            <History phone={client.phone} />
          </TabsContent>
          <TabsContent value="notas" className="mt-4">
            <Notes client={client} notes={notes} onAdded={load} />
          </TabsContent>
        </Tabs>
        <Details client={client} onSaved={load} />
      </div>
    </Page>
  )
}

function Stat({ label, value, hint, small }: { label: string; value: string | number; hint?: string; small?: boolean }) {
  return (
    <div className="bg-card px-4 py-3" title={hint}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={small ? 'mt-1 text-sm font-medium tabular-nums' : 'mt-0.5 text-2xl font-semibold tabular-nums'}>
        {value}
      </p>
    </div>
  )
}

function Summary({ client, onDone }: { client: Client; onDone: () => void }) {
  const [busy, setBusy] = useState(false)

  async function summarize() {
    setBusy(true)
    try {
      await agent(`/clients/${client.id}/summary`)
      onDone()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="size-4 text-brand" aria-hidden /> Resumen con IA
        </CardTitle>
        <Button variant="outline" size="sm" disabled={busy} onClick={summarize}>
          {busy ? 'Leyendo el historial…' : client.ai_summary ? 'Actualizar' : 'Generar resumen'}
        </Button>
      </CardHeader>
      <CardContent>
        {client.ai_summary ? (
          <>
            <p className="max-w-prose leading-relaxed whitespace-pre-wrap">{client.ai_summary}</p>
            <p className="mt-3 text-xs text-muted-foreground">Generado el {when(client.ai_summary_at)}</p>
          </>
        ) : (
          <p className="max-w-prose text-sm text-muted-foreground">
            Claude lee el historial, los tickets y los escalados, y te dice en pocas líneas quién es este cliente,
            por qué escribe y qué quedó pendiente.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function Reasons({ tickets, escalations }: { tickets: Ticket[]; escalations: Escalation[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Por qué nos escribió</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {tickets.length === 0 && escalations.length === 0 ? (
          <EmptyState icon={TicketIcon} title="Sin tickets ni escalados">
            Todo lo que pidió lo resolvió la IA en el momento.
          </EmptyState>
        ) : (
          <ul className="divide-y">
            {tickets.map((t) => (
              <li key={t.id}>
                <a href={href('tickets', String(t.ref))} className="flex items-center gap-3 px-6 py-3 hover:bg-accent/50">
                  <span className="w-14 shrink-0 text-sm text-muted-foreground tabular-nums">#{t.ref}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{t.subject || 'Sin asunto'}</span>
                    <span className="text-xs text-muted-foreground">
                      {TICKET_TYPE[t.type] ?? t.type}, {when(t.created_at)}
                    </span>
                  </span>
                  <TicketStatusBadge status={t.status} />
                </a>
              </li>
            ))}
            {escalations.map((e) => (
              <li key={e.id} className="flex items-start gap-3 px-6 py-3">
                <span className="w-14 shrink-0 text-sm text-st-needs">Escaló</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm">{e.summary || e.reason}</span>
                  <span className="text-xs text-muted-foreground">
                    Motivo: {e.reason}, {when(e.created_at)}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">{e.status}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function Notes({ client, notes, onAdded }: { client: Client; notes: Note[]; onAdded: () => void }) {
  const { me, nameOf } = useTeam()
  const botNotes = client.metadata?.notes ?? []

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const body = String(new FormData(form).get('body')).trim()
    if (!body) return
    const err = failed(await supabase.from('notes').insert({ client_id: client.id, body, author_id: me.user_id }))
    if (err) return toast.error(err)
    form.reset()
    onAdded()
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <form className="flex flex-col gap-2" onSubmit={add}>
          <Textarea name="body" rows={2} placeholder="Nota interna. El cliente no la ve." required />
          <Button size="sm" className="self-end">
            Agregar nota
          </Button>
        </form>
        {notes.length === 0 && botNotes.length === 0 ? (
          <EmptyState icon={StickyNote} title="Sin notas">
            Anotá lo que el próximo que atienda tiene que saber.
          </EmptyState>
        ) : (
          <ul className="divide-y">
            {notes.map((n) => (
              <li key={n.id} className="py-3">
                <p className="whitespace-pre-wrap text-sm">{n.body}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {nameOf(n.author_id)}, {when(n.created_at)}
                </p>
              </li>
            ))}
            {botNotes.map((n, i) => (
              <li key={`bot-${i}`} className="py-3">
                <p className="whitespace-pre-wrap text-sm">{n}</p>
                <p className="mt-1 text-xs text-st-bot">Anotado por la IA</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function Details({ client, onSaved }: { client: Client; onSaved: () => void }) {
  const [busy, setBusy] = useState(false)

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const text = (k: string) => String(data.get(k)).trim() || null
    const tags = String(data.get('tags'))
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    setBusy(true)
    const err = failed(
      await supabase
        .from('clients')
        .update({ name: text('name'), company: text('company'), email: text('email'), tags })
        .eq('id', client.id),
    )
    setBusy(false)
    if (err) return toast.error(err)
    toast.success('Datos guardados.')
    onSaved()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Datos</CardTitle>
      </CardHeader>
      <CardContent>
        <form className="grid gap-4" onSubmit={save}>
          <Field label="Nombre" name="name" value={client.name} />
          <Field label="Empresa" name="company" value={client.company} />
          <Field label="Email" name="email" type="email" value={client.email} />
          <div className="grid gap-1.5">
            <Label htmlFor="phone">Teléfono</Label>
            <Input id="phone" value={client.phone} disabled />
          </div>
          <Field label="Tags" name="tags" value={client.tags.join(', ')} placeholder="mayorista, vip" hint="Separados por coma." />
          <Button disabled={busy}>Guardar datos</Button>
        </form>
      </CardContent>
    </Card>
  )
}

function Field({
  label,
  name,
  value,
  type = 'text',
  placeholder,
  hint,
}: {
  label: string
  name: string
  value: string | null
  type?: string
  placeholder?: string
  hint?: string
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} name={name} type={type} defaultValue={value ?? ''} placeholder={placeholder} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function History({ phone }: { phone: string }) {
  const [messages, setMessages] = useState<Message[] | null>(null)
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
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            placeholder="Buscar en la conversación"
            className="pl-8"
            value={search}
            aria-label="Buscar en la conversación"
            onChange={(e) => {
              setSearch(e.target.value)
              setLimit(PAGE)
            }}
          />
        </div>
        {hasMore && (
          <Button variant="ghost" size="sm" className="self-center" onClick={() => setLimit(limit + PAGE)}>
            Ver mensajes anteriores
          </Button>
        )}
        {messages && messages.length > 0 && <Messages messages={messages} />}
        {messages && messages.length === 0 && (
          <EmptyState icon={MessagesSquare} title={search ? 'Ningún mensaje coincide' : 'Sin mensajes'} />
        )}
      </CardContent>
    </Card>
  )
}

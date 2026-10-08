import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowLeft, Bot, Inbox as InboxIcon, MessageSquareDashed, SendHorizontal, UserPlus, UserRound } from 'lucide-react'
import { toast } from 'sonner'
import { agent, failed, supabase } from '@/supabase'
import { go, href } from '@/lib/route'
import { useTeam } from '@/lib/team'
import { cn } from '@/lib/utils'
import type { Conversation, Message } from '@/lib/types'
import { EmptyState } from '@/components/EmptyState'
import { InitialsAvatar } from '@/components/InitialsAvatar'
import { Messages } from '@/components/Messages'
import { STATUS_RAIL, StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const WINDOW_MS = 24 * 60 * 60 * 1000
const UNASSIGNED = 'none'

type Filter = 'all' | 'mine' | 'unassigned' | 'needs_human'
const FILTERS: Record<Filter, string> = {
  all: 'Todos',
  mine: 'Míos',
  unassigned: 'Sin asignar',
  needs_human: 'Pidió humano',
}

type ClientRef = { id: string; name: string | null }

function shortTime(iso: string) {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today
    ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

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
    <div className="grid h-[calc(100dvh-3.5rem)] md:h-dvh md:grid-cols-[22rem_1fr]">
      <aside className={cn('flex min-h-0 flex-col border-r bg-card', current && 'hidden md:flex')}>
        <div className="flex flex-col gap-3 border-b p-4">
          <h1 className="text-lg font-semibold tracking-tight">Bandeja</h1>
          <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)}>
            <TabsList className="w-full">
              {(Object.keys(FILTERS) as Filter[]).map((f) => (
                <TabsTrigger key={f} value={f} className="text-xs">
                  {FILTERS[f]}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {visible.map((c) => {
            const name = clients[c.phone]?.name
            const active = c.phone === selectedPhone
            return (
              <li key={c.phone}>
                <a
                  href={href('bandeja', c.phone)}
                  aria-current={active ? 'true' : undefined}
                  className={cn(
                    'relative flex items-center gap-3 border-b px-4 py-3 transition-colors hover:bg-accent/60',
                    active && 'bg-accent',
                  )}
                >
                  {/* Quién atiende, de un vistazo: el mismo color que el estado. */}
                  <span className={cn('absolute inset-y-2 left-0 w-0.5 rounded-full', STATUS_RAIL[c.status])} aria-hidden />
                  <InitialsAvatar name={name} phone={c.phone} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium">{name ?? c.phone}</span>
                      <time className="shrink-0 text-xs text-muted-foreground tabular-nums">
                        {shortTime(c.last_message_at)}
                      </time>
                    </span>
                    <span className="mt-1 flex items-center gap-2">
                      <StatusBadge status={c.status} />
                      {c.assigned_to && (
                        <span className="truncate text-xs text-muted-foreground">{nameOf(c.assigned_to)}</span>
                      )}
                    </span>
                  </span>
                </a>
              </li>
            )
          })}
          {visible.length === 0 && (
            <EmptyState icon={InboxIcon} title="Nada por acá">
              {filter === 'all' ? 'Cuando alguien escriba al número, la conversación aparece sola.' : 'Ninguna conversación con este filtro.'}
            </EmptyState>
          )}
        </ul>
      </aside>
      {current ? (
        <Chat conversation={current} client={clients[current.phone]} />
      ) : (
        <main className="hidden items-center justify-center md:flex">
          <EmptyState icon={MessageSquareDashed} title="Elegí una conversación">
            Vas a ver el historial, quién atiende y, si tomás el chat, vas a poder responder.
          </EmptyState>
        </main>
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
  const formRef = useRef<HTMLFormElement>(null)

  const takenByOther = !!assigned_to && assigned_to !== me.user_id && !isAdmin
  const humanName = assigned_to ? (assigned_to === me.user_id ? 'Vos' : nameOf(assigned_to)) : 'Humano'

  async function act(action: string, body?: object) {
    setBusy(true)
    try {
      await agent(`/conversations/${encodeURIComponent(phone)}/${action}`, body)
      return true
    } catch (e) {
      toast.error((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function giveBack(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const note = String(new FormData(e.currentTarget).get('note')).trim()
    if (await act('return', { note })) {
      setReturning(false)
      toast.success('La IA retomó el chat.')
    }
  }

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const text = String(new FormData(form).get('text')).trim()
    if (text && (await act('reply', { text }))) form.reset()
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      formRef.current?.requestSubmit()
    }
  }

  async function createClient() {
    const result = await supabase.from('clients').insert({ phone }).select('id').single()
    const err = failed(result)
    if (err || !result.data) toast.error(err ?? 'No se pudo crear el cliente.')
    else go('clientes', result.data.id)
  }

  // La ventana de 24 h corre desde el último mensaje del cliente. El agente la vuelve a chequear al enviar.
  const lastInbound = messages.findLast((m) => m.direction === 'inbound')
  const windowOpen = !!lastInbound && Date.now() - new Date(lastInbound.created_at).getTime() < WINDOW_MS

  useEffect(() => {
    setMessages([])
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
    <main className="flex min-h-0 min-w-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b bg-card px-4 py-3">
        <Button variant="ghost" size="icon" className="md:hidden" asChild>
          <a href={href('bandeja')} aria-label="Volver a la bandeja">
            <ArrowLeft />
          </a>
        </Button>
        <InitialsAvatar name={client?.name} phone={phone} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{client?.name ?? phone}</p>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            {client?.name && <span className="tabular-nums">{phone}</span>}
            {client ? (
              <a className="text-brand hover:underline" href={href('clientes', client.id)}>
                Ver ficha
              </a>
            ) : (
              <button className="inline-flex items-center gap-1 text-brand hover:underline" onClick={createClient}>
                <UserPlus className="size-3" aria-hidden /> Crear cliente
              </button>
            )}
          </p>
        </div>

        {status === 'needs_human' && <StatusBadge status="needs_human" />}

        {isAdmin && (
          <Select
            value={assigned_to ?? UNASSIGNED}
            disabled={busy}
            onValueChange={(v) => act('assign', { user_id: v === UNASSIGNED ? null : v })}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Asignado a">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNASSIGNED}>Sin asignar</SelectItem>
              {team
                .filter((o) => o.active)
                .map((o) => (
                  <SelectItem key={o.user_id} value={o.user_id}>
                    {o.name || o.email}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        )}

        <Speaker
          human={status === 'human'}
          humanName={humanName}
          disabled={busy || takenByOther}
          disabledReason={takenByOther ? `Este chat lo tiene ${nameOf(assigned_to)}.` : undefined}
          onTake={() => act('take')}
          onReturn={() => setReturning(true)}
        />
      </header>

      <div className="flex min-h-0 flex-1 flex-col-reverse overflow-y-auto px-4 py-4 sm:px-8">
        <Messages messages={messages} />
      </div>

      {status === 'human' && !takenByOther && windowOpen && (
        <form ref={formRef} className="flex items-end gap-2 border-t bg-card p-3" onSubmit={send}>
          <Textarea
            name="text"
            rows={1}
            placeholder="Escribile al cliente. Enter envía, Shift+Enter hace un salto de línea."
            className="max-h-40 min-h-10 resize-none"
            onKeyDown={onKeyDown}
            required
          />
          <Button size="icon-lg" disabled={busy} aria-label="Enviar">
            <SendHorizontal />
          </Button>
        </form>
      )}
      {status === 'human' && !takenByOther && !windowOpen && (
        <p className="border-t bg-card px-4 py-3 text-sm text-muted-foreground">
          La ventana de 24 h está cerrada: el cliente no escribe hace más de un día y WhatsApp solo acepta una
          plantilla aprobada.
        </p>
      )}
      {takenByOther && (
        <p className="border-t bg-card px-4 py-3 text-sm text-muted-foreground">
          Este chat lo tiene {nameOf(assigned_to)}. Un admin lo puede reasignar.
        </p>
      )}

      <Dialog open={returning} onOpenChange={setReturning}>
        <DialogContent>
          <form onSubmit={giveBack} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Devolver el chat a la IA</DialogTitle>
              <DialogDescription>
                Contale qué acordaste con el cliente. La IA lo va a tener en cuenta y no te va a contradecir.
              </DialogDescription>
            </DialogHeader>
            <Textarea name="note" rows={3} placeholder="Ej.: le prometí envío gratis en el próximo pedido." autoFocus />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setReturning(false)}>
                Cancelar
              </Button>
              <Button disabled={busy}>Devolver a la IA</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </main>
  )
}

/**
 * Quién atiende este chat, y la acción para cambiarlo. Es el control central del CRM:
 * apretar el lado que no está activo toma el chat o se lo devuelve a la IA.
 */
function Speaker({
  human,
  humanName,
  disabled,
  disabledReason,
  onTake,
  onReturn,
}: {
  human: boolean
  humanName: string
  disabled: boolean
  disabledReason?: string
  onTake: () => void
  onReturn: () => void
}) {
  const segment = 'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed'
  const control = (
    <div role="group" aria-label="Quién atiende" className="inline-flex rounded-lg border bg-muted p-0.5">
      <button
        type="button"
        aria-pressed={!human}
        disabled={disabled || !human}
        onClick={onReturn}
        className={cn(segment, !human ? 'bg-st-bot-soft text-st-bot shadow-xs' : 'text-muted-foreground hover:text-foreground')}
      >
        <Bot className="size-4" aria-hidden /> IA
      </button>
      <button
        type="button"
        aria-pressed={human}
        disabled={disabled || human}
        onClick={onTake}
        className={cn(segment, human ? 'bg-st-human-soft text-st-human shadow-xs' : 'text-muted-foreground hover:text-foreground')}
      >
        <UserRound className="size-4" aria-hidden /> {human ? humanName : 'Tomar chat'}
      </button>
    </div>
  )
  if (!disabledReason) return control
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span>{control}</span>
      </TooltipTrigger>
      <TooltipContent>{disabledReason}</TooltipContent>
    </Tooltip>
  )
}

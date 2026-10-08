import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Search, TicketIcon } from 'lucide-react'
import { toast } from 'sonner'
import { failed, supabase } from '@/supabase'
import { go, href } from '@/lib/route'
import { useTeam } from '@/lib/team'
import { OPEN_TICKET, PRIORITY, TICKET_STATUS, TICKET_TYPE, when, type Note, type Ticket, type TicketStatus } from '@/lib/types'
import { EmptyState } from '@/components/EmptyState'
import { Page, PageHeader } from '@/components/PageHeader'
import { PriorityText, TicketStatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

// Radix Select no acepta '' como valor: estos son los "todos" de cada filtro.
const ALL = 'all'
const OPEN = 'open_any'
const NOBODY = 'none'

type Filters = { status: string; type: string; priority: string; mine: boolean; q: string }

export default function Tickets({ selectedRef }: { selectedRef?: string }) {
  const { me, nameOf } = useTeam()
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [filters, setFilters] = useState<Filters>({ status: OPEN, type: ALL, priority: ALL, mine: false, q: '' })

  const load = useCallback(async () => {
    // ponytail: hasta 500 tickets por consulta; con más, paginar.
    let q = supabase.from('tickets').select('*, clients(name, phone)').order('created_at', { ascending: false }).limit(500)
    if (filters.status === OPEN) q = q.in('status', OPEN_TICKET)
    else if (filters.status !== ALL) q = q.eq('status', filters.status)
    if (filters.type !== ALL) q = q.eq('type', filters.type)
    if (filters.priority !== ALL) q = q.eq('priority', filters.priority)
    if (filters.mine) q = q.eq('assigned_to', me.user_id)
    const result = await q
    const err = failed(result)
    if (err) toast.error(err)
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
  const visible = (tickets ?? []).filter(
    (t) => !term || String(t.ref).includes(term) || (t.subject ?? '').toLowerCase().includes(term),
  )
  const current = tickets?.find((t) => String(t.ref) === selectedRef)

  return (
    <Page>
      <PageHeader title="Tickets" description="Lo que el bot no pudo resolver solo y quedó para el equipo." />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64 max-w-full">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            placeholder="Número o asunto"
            className="pl-8"
            value={filters.q}
            onChange={(e) => set({ q: e.target.value })}
            aria-label="Buscar tickets"
          />
        </div>
        <FilterSelect label="Estado" value={filters.status} onChange={(status) => set({ status })}>
          <SelectItem value={OPEN}>Abiertos</SelectItem>
          <SelectItem value={ALL}>Todos los estados</SelectItem>
          {Object.entries(TICKET_STATUS).map(([k, v]) => (
            <SelectItem key={k} value={k}>
              {v}
            </SelectItem>
          ))}
        </FilterSelect>
        <FilterSelect label="Tipo" value={filters.type} onChange={(type) => set({ type })}>
          <SelectItem value={ALL}>Todos los tipos</SelectItem>
          {Object.entries(TICKET_TYPE).map(([k, v]) => (
            <SelectItem key={k} value={k}>
              {v}
            </SelectItem>
          ))}
        </FilterSelect>
        <FilterSelect label="Prioridad" value={filters.priority} onChange={(priority) => set({ priority })}>
          <SelectItem value={ALL}>Toda prioridad</SelectItem>
          {Object.entries(PRIORITY).map(([k, v]) => (
            <SelectItem key={k} value={k}>
              {v}
            </SelectItem>
          ))}
        </FilterSelect>
        <Label className="ml-1 flex items-center gap-2 text-sm font-normal">
          <Checkbox checked={filters.mine} onCheckedChange={(v) => set({ mine: v === true })} /> Solo los míos
        </Label>
      </div>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16 pl-4">#</TableHead>
              <TableHead>Asunto</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Prioridad</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Asignado</TableHead>
              <TableHead className="pr-4">Creado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tickets === null &&
              Array.from({ length: 5 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={8} className="px-4">
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {visible.map((t) => (
              <TableRow
                key={t.id}
                data-state={t === current ? 'selected' : undefined}
                className="cursor-pointer"
                onClick={() => go('tickets', String(t.ref))}
              >
                <TableCell className="pl-4 text-muted-foreground tabular-nums">{t.ref}</TableCell>
                <TableCell className="max-w-72 truncate font-medium">{t.subject || 'Sin asunto'}</TableCell>
                <TableCell>{t.clients?.name || t.clients?.phone || '—'}</TableCell>
                <TableCell className="text-muted-foreground">{TICKET_TYPE[t.type] ?? t.type}</TableCell>
                <TableCell>
                  <PriorityText priority={t.priority} />
                </TableCell>
                <TableCell>
                  <TicketStatusBadge status={t.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">{t.assigned_to ? nameOf(t.assigned_to) : '—'}</TableCell>
                <TableCell className="pr-4 text-muted-foreground tabular-nums">{when(t.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {tickets !== null && visible.length === 0 && (
          <EmptyState icon={TicketIcon} title="No hay tickets con estos filtros">
            Probá con "Todos los estados" o sacá el filtro de prioridad.
          </EmptyState>
        )}
      </Card>

      <Sheet open={!!current} onOpenChange={(open) => !open && go('tickets')}>
        <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-lg">
          {current && <TicketDetail key={current.id} ticket={current} onChange={load} />}
        </SheetContent>
      </Sheet>
    </Page>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  children: ReactNode
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  )
}

function TicketDetail({ ticket, onChange }: { ticket: Ticket; onChange: () => void }) {
  const { me, team, nameOf } = useTeam()
  const [notes, setNotes] = useState<Note[]>([])

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
    if (err) toast.error(err)
    else if (patch.status === 'resolved' || patch.status === 'closed') toast.success('Ticket cerrado. Sus escalados quedaron resueltos.')
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
    if (err) return toast.error(err)
    form.reset()
    loadNotes()
  }

  return (
    <>
      <SheetHeader>
        <p className="text-sm text-muted-foreground tabular-nums">
          #{ticket.ref}, {TICKET_TYPE[ticket.type] ?? ticket.type}
        </p>
        <SheetTitle className="text-lg">{ticket.subject || 'Sin asunto'}</SheetTitle>
        <SheetDescription>
          De{' '}
          <a className="text-brand hover:underline" href={href('clientes', ticket.client_id)}>
            {ticket.clients?.name || ticket.clients?.phone}
          </a>
          , creado el {when(ticket.created_at)}.
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-6 px-4 pb-6">
        {ticket.metadata?.details && <p className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">{ticket.metadata.details}</p>}
        {ticket.metadata?.reason && <p className="text-sm text-st-needs">Motivo del escalado: {ticket.metadata.reason}</p>}

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="grid gap-1.5">
            <Label>Estado</Label>
            <Select value={ticket.status} onValueChange={(v) => update({ status: v as TicketStatus })}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(TICKET_STATUS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>Prioridad</Label>
            <Select value={ticket.priority} onValueChange={(v) => update({ priority: v })}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(PRIORITY).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>Asignado</Label>
            <Select
              value={ticket.assigned_to ?? NOBODY}
              onValueChange={(v) => update({ assigned_to: v === NOBODY ? null : v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NOBODY}>Sin asignar</SelectItem>
                {team
                  .filter((o) => o.active)
                  .map((o) => (
                    <SelectItem key={o.user_id} value={o.user_id}>
                      {o.name || o.email}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {!['resolved', 'closed'].includes(ticket.status) && (
          <p className="text-xs text-muted-foreground">Al resolverlo o cerrarlo se resuelven también sus escalados.</p>
        )}

        <Separator />

        <div className="flex flex-col gap-3">
          <h3 className="font-medium">Notas</h3>
          <form className="flex flex-col gap-2" onSubmit={addNote}>
            <Textarea name="body" rows={2} placeholder="Nota interna. El cliente no la ve." required />
            <Button size="sm" className="self-end">
              Agregar nota
            </Button>
          </form>
          <ul className="divide-y">
            {notes.map((n) => (
              <li key={n.id} className="py-3">
                <p className="whitespace-pre-wrap text-sm">{n.body}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {nameOf(n.author_id)}, {when(n.created_at)}
                </p>
              </li>
            ))}
            {ticket.metadata?.last_note && (
              <li className="py-3">
                <p className="whitespace-pre-wrap text-sm">{ticket.metadata.last_note}</p>
                <p className="mt-1 text-xs text-st-bot">Anotado por la IA</p>
              </li>
            )}
          </ul>
        </div>
      </div>
    </>
  )
}

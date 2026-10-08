import { useEffect, useState } from 'react'
import { Search, Users } from 'lucide-react'
import { toast } from 'sonner'
import { failed, supabase } from '@/supabase'
import { go } from '@/lib/route'
import { when, type ClientOverview } from '@/lib/types'
import { EmptyState } from '@/components/EmptyState'
import { InitialsAvatar } from '@/components/InitialsAvatar'
import { Page, PageHeader } from '@/components/PageHeader'
import { StatusBadge } from '@/components/StatusBadge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function Clients() {
  const [rows, setRows] = useState<ClientOverview[] | null>(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    // ponytail: trae hasta 1000 y filtra en el navegador; con más clientes, búsqueda en el servidor.
    supabase
      .from('client_overview')
      .select('*')
      .order('last_contact', { ascending: false, nullsFirst: false })
      .limit(1000)
      .then((result) => {
        const err = failed(result)
        if (err) toast.error(err)
        setRows(result.data ?? [])
      })
  }, [])

  const q = query.trim().toLowerCase()
  const visible = (rows ?? []).filter(
    (c) => !q || [c.name, c.phone, c.company, c.email, ...(c.tags ?? [])].some((v) => v?.toLowerCase().includes(q)),
  )

  return (
    <Page>
      <PageHeader
        title="Clientes"
        description={rows ? `${rows.length} en total, los que escribieron hace menos tiempo primero.` : 'Cargando…'}
        actions={
          <div className="relative w-72 max-w-full">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              type="search"
              placeholder="Nombre, teléfono, empresa o tag"
              className="pl-8"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Buscar clientes"
            />
          </div>
        }
      />
      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Cliente</TableHead>
              <TableHead>Empresa</TableHead>
              <TableHead className="text-right" title="Días distintos en que escribió">
                Contactos
              </TableHead>
              <TableHead className="text-right">Mensajes</TableHead>
              <TableHead>Último contacto</TableHead>
              <TableHead className="text-right">Tickets abiertos</TableHead>
              <TableHead className="pr-4">Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows === null &&
              Array.from({ length: 6 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7} className="px-4">
                    <Skeleton className="h-8 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {visible.map((c) => (
              <TableRow key={c.id} className="cursor-pointer" onClick={() => go('clientes', c.id)}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-3">
                    <InitialsAvatar name={c.name} phone={c.phone} className="size-8" />
                    <div className="min-w-0">
                      <p className="truncate font-medium">{c.name || 'Sin nombre'}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">{c.phone}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{c.company || '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{c.contact_days}</TableCell>
                <TableCell className="text-right tabular-nums">{c.message_count}</TableCell>
                <TableCell className="text-muted-foreground tabular-nums">{when(c.last_contact)}</TableCell>
                <TableCell className="text-right tabular-nums">{c.open_tickets || '—'}</TableCell>
                <TableCell className="pr-4">{c.status ? <StatusBadge status={c.status} /> : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {rows !== null && visible.length === 0 && (
          <EmptyState icon={Users} title={q ? 'Ningún cliente coincide' : 'Todavía no hay clientes'}>
            {q
              ? 'Probá con otra parte del nombre, el teléfono o un tag.'
              : 'El bot los crea cuando se presentan, o los creás vos desde la bandeja.'}
          </EmptyState>
        )}
      </Card>
    </Page>
  )
}

import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { BookOpen, Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { failed, supabase } from '@/supabase'
import { when } from '@/lib/types'
import { EmptyState } from '@/components/EmptyState'
import { Page, PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

type Doc = { id: string; title: string; source: string | null; content: string; created_at: string }
type Hit = { id: string; title: string; confidence: number; match_mode: string; matched_terms: number; query_terms: number }

export default function Knowledge() {
  const [docs, setDocs] = useState<Doc[] | null>(null)
  const [editing, setEditing] = useState<Doc | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Doc | null>(null)

  const load = useCallback(() => {
    supabase
      .from('knowledge_docs')
      .select('id, title, source, content, created_at')
      .order('title')
      .then((result) => {
        const err = failed(result)
        if (err) toast.error(err)
        setDocs(result.data ?? [])
      })
  }, [])
  useEffect(load, [load])

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const row = {
      title: String(data.get('title')).trim(),
      source: String(data.get('source')).trim() || null,
      content: String(data.get('content')).trim(),
    }
    // RLS: sólo admins escriben en knowledge_docs. El índice de búsqueda (fts) se recalcula solo.
    const result =
      editing === 'new'
        ? await supabase.from('knowledge_docs').insert(row)
        : await supabase.from('knowledge_docs').update(row).eq('id', (editing as Doc).id)
    const err = failed(result)
    if (err) return toast.error(err)
    toast.success(editing === 'new' ? 'Documento creado. El bot ya lo usa.' : 'Documento guardado.')
    setEditing(null)
    load()
  }

  async function remove() {
    if (!deleting) return
    const err = failed(await supabase.from('knowledge_docs').delete().eq('id', deleting.id))
    if (err) toast.error(err)
    else toast.success('Documento borrado.')
    setDeleting(null)
    setEditing(null)
    load()
  }

  const doc = editing === 'new' ? null : editing

  return (
    <Page>
      <PageHeader
        title="Base de conocimiento"
        description="Lo que el bot consulta antes de responder precios, plazos o políticas."
        actions={
          <Button onClick={() => setEditing('new')}>
            <Plus /> Nuevo documento
          </Button>
        }
      />

      <SearchTest />

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Título</TableHead>
              <TableHead>Fuente</TableHead>
              <TableHead className="text-right">Largo</TableHead>
              <TableHead className="pr-4">Creado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(docs ?? []).map((d) => (
              <TableRow key={d.id} className="cursor-pointer" onClick={() => setEditing(d)}>
                <TableCell className="pl-4 font-medium">{d.title}</TableCell>
                <TableCell className="text-muted-foreground">{d.source || '—'}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{d.content.length} caracteres</TableCell>
                <TableCell className="pr-4 text-muted-foreground tabular-nums">{when(d.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {docs?.length === 0 && (
          <EmptyState icon={BookOpen} title="La base está vacía">
            Sin documentos, el bot responde que no tiene ese dato y escala a una persona.
          </EmptyState>
        )}
      </Card>

      <Sheet open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <SheetContent className="w-full data-[side=right]:sm:max-w-2xl">
          <form key={doc?.id ?? 'new'} onSubmit={save} className="flex h-full flex-col">
            <SheetHeader>
              <SheetTitle>{doc ? 'Editar documento' : 'Nuevo documento'}</SheetTitle>
              <SheetDescription>
                Escribí con acentos: la búsqueda en español los necesita para reconocer las palabras.
              </SheetDescription>
            </SheetHeader>
            <div className="flex min-h-0 flex-1 flex-col gap-4 px-4">
              <div className="grid gap-1.5">
                <Label htmlFor="title">Título</Label>
                <Input id="title" name="title" defaultValue={doc?.title ?? ''} required />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="source">Fuente</Label>
                <Input id="source" name="source" defaultValue={doc?.source ?? ''} placeholder="precios_2026.pdf" />
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-1.5">
                <Label htmlFor="content">Contenido</Label>
                <Textarea id="content" name="content" defaultValue={doc?.content ?? ''} className="min-h-64 flex-1" required />
              </div>
            </div>
            <SheetFooter className="flex-row justify-between">
              {doc ? (
                <Button type="button" variant="destructive" onClick={() => setDeleting(doc)}>
                  Borrar
                </Button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
                  Cancelar
                </Button>
                <Button>{doc ? 'Guardar cambios' : 'Crear documento'}</Button>
              </div>
            </SheetFooter>
          </form>
        </SheetContent>
      </Sheet>

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Borrar "{deleting?.title}"?</DialogTitle>
            <DialogDescription>El bot deja de usarlo desde la próxima respuesta. No se puede deshacer.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancelar
            </Button>
            <Button variant="destructive" onClick={remove}>
              Borrar documento
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  )
}

/** La misma búsqueda que usa el bot (RPC search_knowledge), para ver qué encontraría. */
function SearchTest() {
  const [hits, setHits] = useState<Hit[] | null>(null)

  async function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const query = String(new FormData(e.currentTarget).get('q')).trim()
    if (!query) return
    const result = await supabase.rpc('search_knowledge', { query_text: query, match_limit: 5 })
    const err = failed(result)
    if (err) return toast.error(err)
    setHits(result.data ?? [])
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Probar como el bot</CardTitle>
        <CardDescription>Escribí una pregunta como la haría un cliente y mirá qué documentos encontraría.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form className="flex gap-2" onSubmit={search}>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input name="q" className="pl-8" placeholder="¿Cuánto sale el producto X por 500 unidades?" aria-label="Pregunta de prueba" />
          </div>
          <Button variant="outline">Buscar</Button>
        </form>
        {hits && hits.length === 0 && (
          <p className="text-sm text-muted-foreground">Nada. El bot respondería que no tiene ese dato.</p>
        )}
        {hits && hits.length > 0 && (
          <ul className="divide-y rounded-md border">
            {hits.map((h) => (
              <li key={h.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="flex-1 font-medium">{h.title}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {h.matched_terms} de {h.query_terms} palabras
                </span>
                <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">
                  confianza {h.confidence.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

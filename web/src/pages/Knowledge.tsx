import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { failed, supabase } from '../supabase'
import { when } from '../lib/types'

type Doc = { id: string; title: string; source: string | null; content: string; created_at: string }
type Hit = { id: string; title: string; confidence: number; match_mode: string; matched_terms: number; query_terms: number }

export default function Knowledge() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [editing, setEditing] = useState<Doc | 'new' | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    supabase
      .from('knowledge_docs')
      .select('id, title, source, content, created_at')
      .order('title')
      .then((result) => {
        setError(failed(result) ?? '')
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
    setError(err ?? '')
    if (!err) {
      setEditing(null)
      load()
    }
  }

  async function remove(doc: Doc) {
    if (!window.confirm(`¿Borrar "${doc.title}"? El bot deja de usarlo.`)) return
    const err = failed(await supabase.from('knowledge_docs').delete().eq('id', doc.id))
    setError(err ?? '')
    setEditing(null)
    load()
  }

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Base de conocimiento</h1>
        <button onClick={() => setEditing('new')}>Nuevo documento</button>
      </div>
      <p className="muted">
        El bot busca acá antes de responder precios, plazos o políticas. Escribí con acentos: la búsqueda en español
        los necesita para reconocer las palabras.
      </p>
      {error && <p className="error">{error}</p>}

      <SearchTest />

      {editing && (
        <form className="card fields" onSubmit={save} key={editing === 'new' ? 'new' : editing.id}>
          <label>
            Título <input name="title" defaultValue={editing === 'new' ? '' : editing.title} required />
          </label>
          <label>
            Fuente <input name="source" defaultValue={editing === 'new' ? '' : editing.source ?? ''} placeholder="precios_2026.pdf" />
          </label>
          <label>
            Contenido
            <textarea name="content" rows={10} defaultValue={editing === 'new' ? '' : editing.content} required />
          </label>
          <div>
            <button>Guardar</button>{' '}
            <button type="button" className="link" onClick={() => setEditing(null)}>Cancelar</button>
            {editing !== 'new' && (
              <button type="button" className="link danger" onClick={() => remove(editing)}>Borrar</button>
            )}
          </div>
        </form>
      )}

      <table className="list clickable">
        <thead>
          <tr>
            <th>Título</th>
            <th>Fuente</th>
            <th>Largo</th>
            <th>Creado</th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.id} onClick={() => setEditing(d)}>
              <td>{d.title}</td>
              <td>{d.source || '—'}</td>
              <td>{d.content.length} car.</td>
              <td>{when(d.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** La misma búsqueda que usa el bot (RPC search_knowledge), para ver qué encontraría. */
function SearchTest() {
  const [hits, setHits] = useState<Hit[] | null>(null)
  const [error, setError] = useState('')

  async function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const query = String(new FormData(e.currentTarget).get('q')).trim()
    if (!query) return
    const result = await supabase.rpc('search_knowledge', { query_text: query, match_limit: 5 })
    setError(failed(result) ?? '')
    setHits(result.data ?? [])
  }

  return (
    <section className="card">
      <form className="row-form" onSubmit={search}>
        <input name="q" placeholder="Probá una pregunta de un cliente: ¿cuánto sale el producto X?" />
        <button>Probar búsqueda</button>
      </form>
      {error && <p className="error">{error}</p>}
      {hits && (
        <ul className="plain">
          {hits.length === 0 && <li className="muted">Nada: el bot respondería que no tiene ese dato.</li>}
          {hits.map((h) => (
            <li key={h.id}>
              {h.title}{' '}
              <span className="muted">
                · confianza {h.confidence.toFixed(2)} · {h.matched_terms}/{h.query_terms} términos ·{' '}
                {h.match_mode === 'all_terms' ? 'todos' : 'alguno'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

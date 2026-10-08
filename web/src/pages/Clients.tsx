import { useEffect, useState } from 'react'
import { failed, supabase } from '../supabase'
import { go } from '../lib/route'
import { STATUS_LABEL, when, type ClientOverview } from '../lib/types'

export default function Clients() {
  const [rows, setRows] = useState<ClientOverview[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    // ponytail: trae hasta 1000 y filtra en el navegador; con más clientes, búsqueda en el servidor.
    supabase
      .from('client_overview')
      .select('*')
      .order('last_contact', { ascending: false, nullsFirst: false })
      .limit(1000)
      .then((result) => {
        setError(failed(result) ?? '')
        setRows(result.data ?? [])
      })
  }, [])

  const q = query.trim().toLowerCase()
  const visible = q
    ? rows.filter((c) =>
        [c.name, c.phone, c.company, c.email, ...(c.tags ?? [])].some((v) => v?.toLowerCase().includes(q)),
      )
    : rows

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Clientes</h1>
        <input
          type="search"
          placeholder="Buscar por nombre, teléfono, empresa o tag"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {error && <p className="error">{error}</p>}
      <table className="list clickable">
        <thead>
          <tr>
            <th>Cliente</th>
            <th>Empresa</th>
            <th title="Días distintos en que escribió">Contactos</th>
            <th>Mensajes</th>
            <th>Último contacto</th>
            <th>Tickets abiertos</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((c) => (
            <tr key={c.id} onClick={() => go('clientes', c.id)}>
              <td>
                <strong>{c.name || 'Sin nombre'}</strong>
                <small>{c.phone}</small>
              </td>
              <td>{c.company || '—'}</td>
              <td>{c.contact_days}</td>
              <td>{c.message_count}</td>
              <td>{when(c.last_contact)}</td>
              <td>{c.open_tickets || '—'}</td>
              <td>{c.status ? <span className={`tag ${c.status}`}>{STATUS_LABEL[c.status]}</span> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <p className="muted">No hay clientes{q && ' que coincidan'}.</p>}
    </div>
  )
}

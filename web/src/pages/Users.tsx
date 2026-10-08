import { useState, type FormEvent } from 'react'
import { agent, failed, supabase } from '../supabase'
import { useTeam } from '../lib/team'
import type { Operator, Role } from '../lib/types'

export default function Users() {
  const { me, team, reloadTeam } = useTeam()
  const [error, setError] = useState('')
  const [created, setCreated] = useState<{ email: string; password: string | null } | null>(null)
  const [busy, setBusy] = useState(false)

  async function update(op: Operator, patch: Partial<Pick<Operator, 'role' | 'active' | 'name'>>) {
    setError('')
    // RLS: sólo un admin puede actualizar operators, y sólo name/role/active (grants de columna).
    const err = failed(await supabase.from('operators').update(patch).eq('user_id', op.user_id))
    if (err) setError(err.includes('admin activo') ? 'Tiene que quedar al menos un admin activo.' : err)
    reloadTeam()
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const data = new FormData(form)
    const email = String(data.get('email')).trim()
    setBusy(true)
    setError('')
    try {
      const res = await agent<{ password: string | null }>('/admin/operators', {
        email,
        name: String(data.get('name')).trim(),
        role: String(data.get('role')) as Role,
      })
      setCreated({ email, password: res.password })
      form.reset()
      reloadTeam()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h1>Usuarios</h1>
      {error && <p className="error">{error}</p>}

      <form className="card row-form" onSubmit={create}>
        <input name="email" type="email" placeholder="Email" required />
        <input name="name" placeholder="Nombre" />
        <select name="role" defaultValue="agent">
          <option value="agent">Agente</option>
          <option value="admin">Admin</option>
        </select>
        <button disabled={busy}>Dar de alta</button>
      </form>

      {created && (
        <p className="card notice">
          {created.password ? (
            <>
              Usuario <strong>{created.email}</strong> creado. Contraseña: <code>{created.password}</code>. Pasásela
              por un canal seguro: no se vuelve a mostrar.
            </>
          ) : (
            <>
              <strong>{created.email}</strong> ya tenía cuenta: quedó como operador con su contraseña de siempre.
            </>
          )}
        </p>
      )}

      <table className="list">
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Email</th>
            <th>Rol</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {team.map((op) => (
            <tr key={op.user_id} className={op.active ? '' : 'inactive'}>
              <td>
                <input
                  defaultValue={op.name ?? ''}
                  placeholder="(sin nombre)"
                  onBlur={(e) => e.target.value !== (op.name ?? '') && update(op, { name: e.target.value })}
                />
              </td>
              <td>{op.email}</td>
              <td>
                <select value={op.role} onChange={(e) => update(op, { role: e.target.value as Role })}>
                  <option value="agent">Agente</option>
                  <option value="admin">Admin</option>
                </select>
              </td>
              <td>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={op.active}
                    disabled={op.user_id === me.user_id}
                    onChange={(e) => update(op, { active: e.target.checked })}
                  />
                  {op.active ? 'Activo' : 'Desactivado'}
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Un usuario desactivado no puede entrar al panel ni usar la API del CRM. Agentes: bandeja, clientes y
        tickets. Admins: además, usuarios y base de conocimiento.
      </p>
    </div>
  )
}

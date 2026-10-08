import { useState, type FormEvent } from 'react'
import { Copy, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { agent, failed, supabase } from '@/supabase'
import { useTeam } from '@/lib/team'
import type { Operator, Role } from '@/lib/types'
import { InitialsAvatar } from '@/components/InitialsAvatar'
import { Page, PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const ROLE_LABEL: Record<Role, string> = { admin: 'Admin', agent: 'Agente' }

export default function Users() {
  const { me, team, reloadTeam } = useTeam()
  const [creating, setCreating] = useState(false)

  async function update(op: Operator, patch: Partial<Pick<Operator, 'role' | 'active' | 'name'>>) {
    // RLS: sólo un admin puede actualizar operators, y sólo name/role/active (grants de columna).
    const err = failed(await supabase.from('operators').update(patch).eq('user_id', op.user_id))
    if (err) toast.error(err.includes('admin activo') ? 'Tiene que quedar al menos un admin activo.' : err)
    reloadTeam()
  }

  return (
    <Page>
      <PageHeader
        title="Usuarios"
        description="Los agentes atienden la bandeja, los clientes y los tickets. Los admins además gestionan el equipo y la base de conocimiento."
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus /> Nuevo usuario
          </Button>
        }
      />

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Persona</TableHead>
              <TableHead className="w-40">Rol</TableHead>
              <TableHead className="w-40 pr-4">Acceso</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {team.map((op) => (
              <TableRow key={op.user_id} className={op.active ? '' : 'opacity-60'}>
                <TableCell className="pl-4">
                  <div className="flex items-center gap-3">
                    <InitialsAvatar name={op.name || op.email} className="size-8" />
                    <div className="min-w-0">
                      <Input
                        defaultValue={op.name ?? ''}
                        placeholder="Sin nombre"
                        aria-label={`Nombre de ${op.email}`}
                        className="h-7 border-transparent px-1.5 font-medium shadow-none hover:border-input focus-visible:border-ring"
                        onBlur={(e) => e.target.value !== (op.name ?? '') && update(op, { name: e.target.value })}
                      />
                      <p className="px-1.5 text-xs text-muted-foreground">
                        {op.email}
                        {op.user_id === me.user_id && ' (vos)'}
                      </p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <Select value={op.role} onValueChange={(v) => update(op, { role: v as Role })}>
                    <SelectTrigger size="sm" className="w-32" aria-label={`Rol de ${op.email}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="agent">{ROLE_LABEL.agent}</SelectItem>
                      <SelectItem value="admin">{ROLE_LABEL.admin}</SelectItem>
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="pr-4">
                  <Label className="flex items-center gap-2 font-normal">
                    <Checkbox
                      checked={op.active}
                      disabled={op.user_id === me.user_id}
                      onCheckedChange={(v) => update(op, { active: v === true })}
                    />
                    {op.active ? 'Activo' : 'Desactivado'}
                  </Label>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <p className="text-sm text-muted-foreground">
        Un usuario desactivado no puede entrar al panel ni usar la API del CRM. No podés desactivarte a vos mismo.
      </p>

      <NewUserDialog open={creating} onOpenChange={setCreating} onCreated={reloadTeam} />
    </Page>
  )
}

function NewUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}) {
  const [role, setRole] = useState<Role>('agent')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<{ email: string; password: string | null } | null>(null)

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const email = String(data.get('email')).trim()
    setBusy(true)
    try {
      const res = await agent<{ password: string | null }>('/admin/operators', {
        email,
        name: String(data.get('name')).trim(),
        role,
      })
      setCreated({ email, password: res.password })
      onCreated()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function close(next: boolean) {
    onOpenChange(next)
    if (!next) {
      setCreated(null)
      setRole('agent')
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Usuario creado</DialogTitle>
              <DialogDescription>
                {created.password
                  ? 'Pasale esta contraseña por un canal seguro. No se vuelve a mostrar.'
                  : `${created.email} ya tenía cuenta: quedó como operador con su contraseña de siempre.`}
              </DialogDescription>
            </DialogHeader>
            {created.password && (
              <div className="grid gap-1.5">
                <Label>Contraseña de {created.email}</Label>
                <div className="flex gap-2">
                  <Input readOnly value={created.password} className="font-mono" onFocus={(e) => e.target.select()} />
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="Copiar contraseña"
                    onClick={() => navigator.clipboard.writeText(created.password!).then(() => toast.success('Contraseña copiada.'))}
                  >
                    <Copy />
                  </Button>
                </div>
              </div>
            )}
            <DialogFooter>
              <Button onClick={() => close(false)}>Listo</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={create} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Nuevo usuario</DialogTitle>
              <DialogDescription>Le generamos una contraseña que vas a ver una sola vez.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-1.5">
              <Label htmlFor="new-email">Email</Label>
              <Input id="new-email" name="email" type="email" required autoFocus />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="new-name">Nombre</Label>
              <Input id="new-name" name="name" placeholder="Como lo va a ver el equipo" />
            </div>
            <div className="grid gap-1.5">
              <Label>Rol</Label>
              <Select value={role} onValueChange={(v) => setRole(v as Role)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="agent">Agente: bandeja, clientes y tickets</SelectItem>
                  <SelectItem value="admin">Admin: además, usuarios y conocimiento</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => close(false)}>
                Cancelar
              </Button>
              <Button disabled={busy}>Crear usuario</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

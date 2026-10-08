import { createContext, useContext } from 'react'
import type { Operator } from './types'

export type Team = {
  me: Operator
  team: Operator[]
  reloadTeam: () => void
}

export const TeamContext = createContext<Team | null>(null)

export function useTeam(): Team & { nameOf: (id: string | null | undefined) => string; isAdmin: boolean } {
  const ctx = useContext(TeamContext)
  if (!ctx) throw new Error('useTeam fuera de TeamContext')
  const nameOf = (id: string | null | undefined) => {
    if (!id) return 'Sin asignar'
    const op = ctx.team.find((o) => o.user_id === id)
    return op?.name || op?.email || 'Operador'
  }
  return { ...ctx, nameOf, isAdmin: ctx.me.role === 'admin' }
}

import { Bot, Hand, UserRound } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PRIORITY, STATUS_LABEL, TICKET_STATUS, type Status, type TicketStatus } from '@/lib/types'

/** Color por estado de conversación: es la información central de la bandeja (quién atiende). */
export const STATUS_TONE: Record<Status, string> = {
  bot: 'bg-st-bot-soft text-st-bot',
  needs_human: 'bg-st-needs-soft text-st-needs',
  human: 'bg-st-human-soft text-st-human',
}

export const STATUS_RAIL: Record<Status, string> = {
  bot: 'bg-st-bot',
  needs_human: 'bg-st-needs',
  human: 'bg-st-human',
}

const STATUS_ICON = { bot: Bot, needs_human: Hand, human: UserRound }

const pill = 'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap'

export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  const Icon = STATUS_ICON[status]
  return (
    <span className={cn(pill, STATUS_TONE[status], className)}>
      <Icon className="size-3" aria-hidden />
      {STATUS_LABEL[status]}
    </span>
  )
}

const TICKET_TONE: Record<TicketStatus, string> = {
  open: 'bg-brand-soft text-brand',
  in_progress: 'bg-st-bot-soft text-st-bot',
  waiting_client: 'bg-st-needs-soft text-st-needs',
  resolved: 'bg-muted text-muted-foreground',
  closed: 'bg-muted text-muted-foreground',
}

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  return <span className={cn(pill, TICKET_TONE[status])}>{TICKET_STATUS[status]}</span>
}

export function PriorityText({ priority }: { priority: string }) {
  return (
    <span
      className={cn(
        'text-sm',
        priority === 'high' && 'font-medium text-st-needs',
        priority === 'urgent' && 'font-semibold text-destructive',
        priority === 'low' && 'text-muted-foreground',
      )}
    >
      {PRIORITY[priority] ?? priority}
    </span>
  )
}

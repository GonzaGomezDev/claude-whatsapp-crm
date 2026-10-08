export type Status = 'bot' | 'needs_human' | 'human'
export type Role = 'admin' | 'agent'

export type Conversation = {
  phone: string
  status: Status
  handoff_note: string | null
  last_message_at: string
  assigned_to: string | null
}

export type Message = {
  id: string
  phone: string | null
  direction: 'inbound' | 'outbound'
  body: string
  created_at: string
  metadata: { source?: string }
}

export type Operator = {
  user_id: string
  name: string | null
  email: string | null
  role: Role
  active: boolean
}

export type Client = {
  id: string
  phone: string
  name: string | null
  company: string | null
  email: string | null
  tags: string[]
  metadata: { notes?: string[] }
  ai_summary: string | null
  ai_summary_at: string | null
  created_at: string
}

export type ClientOverview = Pick<Client, 'id' | 'phone' | 'name' | 'company' | 'email' | 'tags' | 'created_at'> & {
  status: Status | null
  assigned_to: string | null
  inbound_count: number
  message_count: number
  contact_days: number
  first_contact: string | null
  last_contact: string | null
  open_tickets: number
  escalations: number
}

export type TicketStatus = 'open' | 'in_progress' | 'waiting_client' | 'resolved' | 'closed'

export type Ticket = {
  id: string
  ref: number
  client_id: string
  type: string
  status: TicketStatus
  priority: string
  subject: string | null
  metadata: { details?: string; reason?: string; last_note?: string }
  assigned_to: string | null
  created_at: string
  updated_at: string
  clients?: { name: string | null; phone: string } | null
}

export type Escalation = {
  id: string
  reason: string
  summary: string | null
  status: string
  created_at: string
}

export type Note = {
  id: string
  client_id: string
  ticket_id: string | null
  author_id: string | null
  body: string
  created_at: string
}

export const STATUS_LABEL: Record<Status, string> = { bot: 'IA', needs_human: 'Pidió humano', human: 'Humano' }

export const TICKET_STATUS: Record<TicketStatus, string> = {
  open: 'Abierto',
  in_progress: 'En curso',
  waiting_client: 'Esperando cliente',
  resolved: 'Resuelto',
  closed: 'Cerrado',
}

export const TICKET_TYPE: Record<string, string> = {
  general: 'General',
  quotation: 'Cotización',
  support: 'Soporte',
  billing: 'Facturación',
  escalation: 'Escalado',
}

export const PRIORITY: Record<string, string> = { low: 'Baja', normal: 'Normal', high: 'Alta', urgent: 'Urgente' }

export const OPEN_TICKET: TicketStatus[] = ['open', 'in_progress', 'waiting_client']

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

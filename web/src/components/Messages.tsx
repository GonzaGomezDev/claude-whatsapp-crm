import { Bot, UserRound } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Message } from '@/lib/types'

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
}

/**
 * Burbujas de un chat, en orden cronológico, con separador por día. La autoría de cada respuesta
 * (IA o humano) usa los mismos colores que el estado de la conversación.
 */
export function Messages({ messages }: { messages: Message[] }) {
  return (
    <ol className="flex flex-col gap-1.5">
      {messages.map((m, i) => {
        const outbound = m.direction === 'outbound'
        const human = m.metadata?.source === 'operator'
        const newDay = i === 0 || day(messages[i - 1]!.created_at) !== day(m.created_at)
        return (
          <li key={m.id} className="contents">
            {newDay && (
              <span className="my-3 self-center rounded-full bg-muted px-3 py-0.5 text-xs text-muted-foreground first-letter:uppercase">
                {day(m.created_at)}
              </span>
            )}
            <div
              className={cn(
                'max-w-[min(80%,36rem)] rounded-2xl px-3.5 py-2 text-sm shadow-xs',
                outbound ? 'self-end rounded-br-md' : 'self-start rounded-bl-md border bg-card',
                outbound && (human ? 'bg-st-human-soft' : 'bg-st-bot-soft'),
              )}
            >
              {outbound && (
                <span className={cn('mb-0.5 flex items-center gap-1 text-xs font-medium', human ? 'text-st-human' : 'text-st-bot')}>
                  {human ? <UserRound className="size-3" aria-hidden /> : <Bot className="size-3" aria-hidden />}
                  {human ? 'Humano' : 'IA'}
                </span>
              )}
              <p className="whitespace-pre-wrap break-words">{m.body}</p>
              <time className="mt-0.5 block text-right text-[11px] text-muted-foreground tabular-nums">
                {new Date(m.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
              </time>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

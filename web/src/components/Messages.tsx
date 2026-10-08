import type { Message } from '../lib/types'

/** Burbujas de un chat, en orden cronológico. La usan la bandeja y la ficha del cliente. */
export function Messages({ messages, full = false }: { messages: Message[]; full?: boolean }) {
  return (
    <ol className="bubbles">
      {messages.map((m) => (
        <li key={m.id} className={m.direction}>
          {m.direction === 'outbound' && <small>{m.metadata?.source === 'operator' ? 'Humano' : 'IA'}</small>}
          <p>{m.body}</p>
          <time>{full ? new Date(m.created_at).toLocaleString() : new Date(m.created_at).toLocaleTimeString()}</time>
        </li>
      ))}
    </ol>
  )
}

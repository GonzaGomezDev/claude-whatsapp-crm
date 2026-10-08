import { cn } from '@/lib/utils'

/** Iniciales del nombre, o los últimos dígitos del teléfono si todavía no sabemos quién es. */
export function initials(name: string | null | undefined, phone?: string): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (words.length) return words.slice(0, 2).map((w) => w[0]!.toUpperCase()).join('')
  return (phone ?? '').replace(/\D/g, '').slice(-2) || '?'
}

export function InitialsAvatar({
  name,
  phone,
  className,
}: {
  name?: string | null
  phone?: string
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground tabular-nums',
        className,
      )}
    >
      {initials(name, phone)}
    </span>
  )
}

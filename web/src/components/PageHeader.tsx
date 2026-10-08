import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  actions,
  leading,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  leading?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-3">
      {leading}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-8 sm:py-8">{children}</div>
}

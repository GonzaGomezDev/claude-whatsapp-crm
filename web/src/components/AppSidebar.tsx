import { useState } from 'react'
import { BookOpen, ChevronsUpDown, LogOut, Menu, MessagesSquare, ShieldCheck, Ticket, Users } from 'lucide-react'
import { supabase } from '@/supabase'
import { href } from '@/lib/route'
import { useTeam } from '@/lib/team'
import { cn } from '@/lib/utils'
import { InitialsAvatar } from '@/components/InitialsAvatar'
import { ThemeMenuItem } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'

export const NAV = [
  { path: 'bandeja', label: 'Bandeja', icon: MessagesSquare, admin: false },
  { path: 'clientes', label: 'Clientes', icon: Users, admin: false },
  { path: 'tickets', label: 'Tickets', icon: Ticket, admin: false },
  { path: 'conocimiento', label: 'Conocimiento', icon: BookOpen, admin: true },
  { path: 'usuarios', label: 'Usuarios', icon: ShieldCheck, admin: true },
]

function Brand() {
  return (
    <a href={href('bandeja')} className="flex items-center gap-2.5 px-2 py-1">
      <span className="inline-flex size-8 items-center justify-center rounded-lg bg-brand text-white dark:text-background">
        <MessagesSquare className="size-4" aria-hidden />
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold">CRM</span>
        <span className="block text-xs text-muted-foreground">WhatsApp</span>
      </span>
    </a>
  )
}

function NavLinks({ section, onNavigate }: { section: string; onNavigate?: () => void }) {
  const { isAdmin } = useTeam()
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Secciones">
      {NAV.filter((n) => isAdmin || !n.admin).map((n) => {
        const active = section === n.path
        return (
          <a
            key={n.path}
            href={href(n.path)}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground',
              active && 'bg-sidebar-accent font-medium text-foreground',
            )}
          >
            <n.icon className={cn('size-4', active && 'text-brand')} aria-hidden />
            {n.label}
          </a>
        )
      })}
    </nav>
  )
}

function UserMenu() {
  const { me, isAdmin } = useTeam()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-sidebar-accent">
          <InitialsAvatar name={me.name || me.email} className="size-8" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{me.name || me.email}</span>
            <span className="block text-xs text-muted-foreground">{isAdmin ? 'Admin' : 'Agente'}</span>
          </span>
          <ChevronsUpDown className="size-4 text-muted-foreground" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <ThemeMenuItem />
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => supabase.auth.signOut()}>
          <LogOut /> Salir
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Barra lateral fija en escritorio; en celular, barra superior con el menú en un Sheet. */
export function AppSidebar({ section }: { section: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r border-sidebar-border bg-sidebar p-3 md:flex">
        <Brand />
        <NavLinks section={section} />
        <div className="mt-auto">
          <UserMenu />
        </div>
      </aside>

      <div className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-sidebar px-3 md:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Abrir menú">
              <Menu />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64 gap-6 bg-sidebar p-3">
            <SheetTitle className="sr-only">Menú</SheetTitle>
            <Brand />
            <NavLinks section={section} onNavigate={() => setOpen(false)} />
            <div className="mt-auto">
              <UserMenu />
            </div>
          </SheetContent>
        </Sheet>
        <Brand />
      </div>
    </>
  )
}

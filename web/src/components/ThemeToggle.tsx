import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'

const NEXT = { system: 'light', light: 'dark', dark: 'system' } as const
const LABEL = { system: 'Tema: del sistema', light: 'Tema: claro', dark: 'Tema: oscuro' }
const ICON = { system: Monitor, light: Sun, dark: Moon }

/** Ítem del menú de usuario que rota sistema → claro → oscuro. next-themes lo recuerda. */
export function ThemeMenuItem() {
  const { theme = 'system', setTheme } = useTheme()
  const current = (theme in NEXT ? theme : 'system') as keyof typeof NEXT
  const Icon = ICON[current]
  return (
    <DropdownMenuItem
      onSelect={(e) => {
        e.preventDefault()
        setTheme(NEXT[current])
      }}
    >
      <Icon /> {LABEL[current]}
    </DropdownMenuItem>
  )
}

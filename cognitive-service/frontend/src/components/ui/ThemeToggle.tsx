// Compact light/dark toggle that fits the 68px nav rail. Visual treatment
// uses semantic --engram-* tokens so it adapts to whichever theme is active.

import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/lib/theme'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isLight = theme === 'light'

  return (
    <button
      onClick={toggle}
      title={isLight ? 'Switch to dark' : 'Switch to light'}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        padding: '10px 0',
        borderRadius: 'var(--engram-radius-md)',
        border: 'none',
        cursor: 'pointer',
        background: 'transparent',
        color: 'var(--engram-text-muted)',
        transition: 'color var(--engram-transition), background var(--engram-transition)',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'var(--engram-tint-primary)'
        e.currentTarget.style.color = 'var(--engram-accent-primary)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.color = 'var(--engram-text-muted)'
      }}
    >
      {isLight ? <Moon size={15} strokeWidth={1.7} /> : <Sun size={15} strokeWidth={1.7} />}
    </button>
  )
}

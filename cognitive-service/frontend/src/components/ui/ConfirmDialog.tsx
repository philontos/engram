// react-refresh/only-export-components: this file intentionally exports the
// `useConfirm` hook alongside `ConfirmProvider`. They are tightly coupled and
// always imported as a pair; splitting the hook into its own file just to
// satisfy fast-refresh would be churn. The cost is HMR re-mounting the
// provider on edits to this file, which is acceptable for a rarely-touched
// dialog.
/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { AlertTriangle, Trash2, X } from 'lucide-react'
import { useI18n } from '@/i18n'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ConfirmOptions {
  title: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Red confirm button + warning icon */
  danger?: boolean
  /** Show trash icon instead of warning icon (for delete-style confirms) */
  destructive?: boolean
}

type ConfirmState = ConfirmOptions & {
  resolve: (ok: boolean) => void
}

// ── Context ───────────────────────────────────────────────────────────────────

const Ctx = createContext<(opts: ConfirmOptions) => Promise<boolean>>(() => Promise.resolve(false))

export function useConfirm() {
  return useContext(Ctx)
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConfirmState | null>(null)
  const resolveRef = useRef<((ok: boolean) => void) | null>(null)

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise(resolve => {
      resolveRef.current = resolve
      setState({ ...opts, resolve })
    })
  }, [])

  function close(ok: boolean) {
    resolveRef.current?.(ok)
    resolveRef.current = null
    setState(null)
  }

  return (
    <Ctx.Provider value={confirm}>
      {children}
      {state && <ConfirmDialog opts={state} onClose={close} />}
    </Ctx.Provider>
  )
}

// ── Dialog UI ─────────────────────────────────────────────────────────────────

function ConfirmDialog({ opts, onClose }: { opts: ConfirmState; onClose: (ok: boolean) => void }) {
  const { t } = useI18n()
  const {
    title, message, danger, destructive,
    confirmLabel = t('common.confirm'),
    cancelLabel  = t('common.cancel'),
  } = opts

  // Close on backdrop click
  function handleBackdrop(e: React.MouseEvent) {
    if (e.target === e.currentTarget) onClose(false)
  }

  // Close on Escape
  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onClose(false)
    if (e.key === 'Enter') onClose(true)
  }

  return (
    <div
      onMouseDown={handleBackdrop}
      onKeyDown={handleKey}
      tabIndex={-1}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
        backdropFilter: 'blur(2px)',
      }}
    >
      <div
        className="fade-in"
        style={{
          width: '100%', maxWidth: 400,
          background: 'var(--surface)',
          border: '1px solid var(--border2)',
          borderRadius: 14,
          boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{ padding: '20px 20px 0', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          {danger && (
            <div style={{
              width: 36, height: 36, borderRadius: 10, flexShrink: 0,
              background: 'rgba(248,113,113,0.12)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {destructive
                ? <Trash2 size={17} color="#f87171" />
                : <AlertTriangle size={17} color="#f87171" />
              }
            </div>
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', lineHeight: 1.3 }}>{title}</div>
            {message && (
              <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 6, lineHeight: 1.6 }}>{message}</div>
            )}
          </div>
          <button
            onClick={() => onClose(false)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: '0 2px', display: 'flex', flexShrink: 0, marginTop: 2 }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '20px 20px 20px' }}>
          <button
            onClick={() => onClose(false)}
            style={{
              padding: '8px 18px', borderRadius: 8, border: '1px solid var(--border2)',
              background: 'transparent', color: 'var(--text2)', fontSize: 13, fontWeight: 500,
              cursor: 'pointer', transition: 'all 0.12s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface2)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {cancelLabel}
          </button>
          <button
            onClick={() => onClose(true)}
            autoFocus
            style={{
              padding: '8px 18px', borderRadius: 8, border: 'none',
              background: danger ? '#ef4444' : 'var(--accent)',
              color: '#fff', fontSize: 13, fontWeight: 600,
              cursor: 'pointer', transition: 'opacity 0.12s',
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.88')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

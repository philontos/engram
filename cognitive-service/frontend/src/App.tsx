import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchStats, exportEntries, processPending, resetData, importEntries } from '@/api'
import type { Stats } from '@/types'
import { GraphTab }   from '@/components/graph/GraphTab'
import { EntriesTab } from '@/components/entries/EntriesTab'
import { ProfileTab } from '@/components/profile/ProfileTab'
import { QueryTab }   from '@/components/query/QueryTab'
import { Network, BookOpen, UserCircle2, Search, Settings, Download, Upload, Zap, Trash2, AlertTriangle, X } from 'lucide-react'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { useI18n, type TKey } from '@/i18n'
import { LangSwitcher } from '@/components/ui/LangSwitcher'

type Tab = 'graph' | 'entries' | 'profile' | 'query'

const TABS: { id: Tab; labelKey: TKey; Icon: React.ElementType }[] = [
  { id: 'graph',   labelKey: 'nav.graph',   Icon: Network     },
  { id: 'entries', labelKey: 'nav.entries', Icon: BookOpen    },
  { id: 'profile', labelKey: 'nav.profile', Icon: UserCircle2 },
  { id: 'query',   labelKey: 'nav.query',   Icon: Search      },
]

export default function App() {
  const qc      = useQueryClient()
  const confirm = useConfirm()
  const { t }   = useI18n()
  const [tab, setTab]           = useState<Tab>('graph')
  const [adminOpen, setAdminOpen] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [adminBusy, setAdminBusy]   = useState(false)
  const [adminMsg, setAdminMsg]     = useState('')
  const adminRef = useRef<HTMLDivElement>(null)

  const { data: stats } = useQuery<Stats>({
    queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 30_000,
  })

  useEffect(() => {
    const fn = (e: MouseEvent) => {
      if (adminRef.current && !adminRef.current.contains(e.target as Node)) setAdminOpen(false)
    }
    if (adminOpen) document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [adminOpen])

  async function handleExport() {
    setAdminOpen(false)
    const res = await exportEntries()
    if (!res.ok) return alert(t('admin.export_failed'))
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    Object.assign(document.createElement('a'), { href: url, download: 'cognitive_entries.json' }).click()
    URL.revokeObjectURL(url)
  }

  async function handleProcessPending() {
    setAdminOpen(false); setAdminBusy(true); setAdminMsg('')
    try {
      const r = await processPending()
      setAdminMsg(t('admin.processed', { count: r.processed }))
      await qc.invalidateQueries()
    } catch (e) { setAdminMsg(`${t('common.failed')} ${String(e)}`) }
    finally { setAdminBusy(false) }
  }

  async function handleReset(scope: 'derived' | 'all') {
    setAdminOpen(false)
    const label = scope === 'all' ? t('admin.reset_all_label') : t('admin.reset_derived_label')
    const ok = await confirm({
      title: scope === 'all' ? t('admin.reset_all_title') : t('admin.reset_derived_title'),
      message: t('admin.reset_message', { label }),
      confirmLabel: t('admin.reset_confirm'),
      danger: true, destructive: true,
    })
    if (!ok) return
    setAdminBusy(true); setAdminMsg('')
    try {
      await resetData(scope); setAdminMsg(t('admin.reset_success'))
      await qc.invalidateQueries()
    } catch (e) { setAdminMsg(`${t('common.failed')} ${String(e)}`) }
    finally { setAdminBusy(false) }
  }

  function parseEntries(text: string): unknown[] {
    const json = JSON.parse(text) as unknown
    if (Array.isArray(json)) return json
    if (json && typeof json === 'object') {
      const obj = json as Record<string, unknown>
      if (Array.isArray(obj.entries)) return obj.entries
      // single entry object
      if ('raw' in obj || 'id' in obj) return [obj]
    }
    throw new Error(t('import.parse_error'))
  }

  async function doImport(text: string) {
    const entries = parseEntries(text)
    if (!entries.length) throw new Error(t('import.nothing_to_import'))
    const ok = await confirm({
      title: t('import.confirm_title', { count: entries.length }),
      message: t('import.confirm_message'),
      confirmLabel: t('import.confirm_button'),
    })
    if (!ok) return
    await importEntries(entries)
    await qc.invalidateQueries({ queryKey: ['entries'] })
    await qc.invalidateQueries({ queryKey: ['stats'] })
    setShowImport(false)
  }

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', overflow: 'hidden' }}>

      {/* ── Left nav ────────────────────────────────────── */}
      <nav style={{
        width: 68, flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center',
        padding: '16px 0', background: 'var(--surface)', borderRight: '1px solid var(--border)',
        position: 'relative', zIndex: 20,
      }}>
        {/* Logo */}
        <div style={{ fontSize: 20, marginBottom: 20, userSelect: 'none' }}>🧠</div>

        {/* Nav items */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%', padding: '0 8px' }}>
          {TABS.map(({ id, labelKey, Icon }) => {
            const active = tab === id
            return (
              <button key={id} onClick={() => setTab(id)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                  padding: '10px 0', borderRadius: 10, width: '100%', cursor: 'pointer',
                  border: 'none', position: 'relative', transition: 'all 0.12s',
                  background: active ? 'rgba(99,102,241,0.15)' : 'transparent',
                  color: active ? 'var(--accent2)' : 'var(--text3)',
                }}>
                {active && (
                  <span style={{
                    position: 'absolute', left: 0, top: 8, bottom: 8,
                    width: 3, borderRadius: '0 3px 3px 0', background: 'var(--accent)',
                  }} />
                )}
                <Icon size={17} strokeWidth={active ? 2.2 : 1.7} />
                <span style={{ fontSize: 10, fontWeight: active ? 600 : 400, letterSpacing: '0.02em' }}>{t(labelKey)}</span>
              </button>
            )
          })}
        </div>

        <div style={{ flex: 1 }} />

        {/* Stats */}
        {stats && (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
            marginBottom: 12, padding: '10px 8px',
            borderRadius: 10, background: 'var(--surface2)', width: 'calc(100% - 16px)',
          }}>
            <StatBit label={t('stats.entries')} value={stats.entries} />
            <div style={{ width: '100%', height: 1, background: 'var(--border)' }} />
            <StatBit label={t('stats.nodes')} value={stats.nodes} />
            <div style={{ width: '100%', height: 1, background: 'var(--border)' }} />
            <StatBit label={t('stats.edges')} value={stats.edges} />
          </div>
        )}

        {/* Language switcher */}
        <div style={{ width: '100%', padding: '0 8px', marginBottom: 4 }}>
          <LangSwitcher />
        </div>

        {/* Admin */}
        <div ref={adminRef} style={{ position: 'relative', width: '100%', padding: '0 8px' }}>
          <button onClick={() => setAdminOpen(v => !v)}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
              padding: '10px 0', borderRadius: 10, width: '100%', cursor: 'pointer',
              border: 'none', transition: 'all 0.12s',
              background: adminOpen ? 'rgba(99,102,241,0.15)' : 'transparent',
              color: adminOpen ? 'var(--accent2)' : 'var(--text3)',
            }}>
            <Settings size={17} strokeWidth={1.7} />
            <span style={{ fontSize: 10 }}>{t('nav.admin')}</span>
          </button>

          {adminOpen && (
            <div className="fade-in" style={{
              position: 'absolute', bottom: 0, left: 'calc(100% + 8px)',
              width: 228, borderRadius: 12, overflow: 'hidden',
              background: 'var(--surface)',
              border: '1px solid var(--border2)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
            }}>
              <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 2 }}>{t('admin.title')}</div>
                {adminMsg && (
                  <div style={{ fontSize: 11, marginTop: 4, color: 'var(--text2)' }}>{adminMsg}</div>
                )}
              </div>
              <div style={{ padding: '6px 6px' }}>
                <AdminMenuItem icon={<Download size={13} />} label={t('admin.export_entries')} onClick={handleExport} disabled={adminBusy} />
                <AdminMenuItem icon={<Upload size={13} />} label={t('admin.import_entries')} onClick={() => { setAdminOpen(false); setShowImport(true) }} disabled={adminBusy} />
                <AdminMenuItem icon={<Zap size={13} />} label={t('admin.process_pending')} onClick={handleProcessPending} disabled={adminBusy} />
                <div style={{ margin: '6px 10px', height: 1, background: 'var(--border)' }} />
                <AdminMenuItem icon={<Trash2 size={13} />} label={t('admin.reset_derived')} onClick={() => handleReset('derived')} disabled={adminBusy} danger />
                <AdminMenuItem icon={<AlertTriangle size={13} />} label={t('admin.reset_all')} onClick={() => handleReset('all')} disabled={adminBusy} danger />
              </div>
            </div>
          )}
        </div>
      </nav>

      {/* ── Content ─────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {showImport && <ImportModal onImport={doImport} onClose={() => setShowImport(false)} />}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div className={tab === 'graph'   ? 'h-full' : 'hidden'}><GraphTab active={tab === 'graph'} /></div>
          <div className={tab === 'entries' ? 'h-full' : 'hidden'}><EntriesTab /></div>
          <div className={tab === 'profile' ? 'h-full' : 'hidden'}><ProfileTab /></div>
          <div className={tab === 'query'   ? 'h-full' : 'hidden'}><QueryTab /></div>
        </div>
      </div>
    </div>
  )
}

function StatBit({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
      <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text2)', lineHeight: 1 }}>{value}</span>
      <span style={{ fontSize: 9, color: 'var(--text3)', letterSpacing: '0.04em' }}>{label}</span>
    </div>
  )
}

function ImportModal({ onImport, onClose }: { onImport: (text: string) => Promise<void>; onClose: () => void }) {
  const { t } = useI18n()
  const [pasteText, setPasteText] = useState('')
  const [error, setError]         = useState('')
  const [busy, setBusy]           = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFormat() {
    const text = pasteText.trim()
    if (!text) return
    try {
      setPasteText(JSON.stringify(JSON.parse(text), null, 2))
      setError('')
    } catch (e) {
      setError(`${t('common.invalid_json')}: ${e instanceof SyntaxError ? e.message : String(e)}`)
    }
  }

  async function handleSubmit() {
    const text = pasteText.trim()
    if (!text) return
    setBusy(true); setError('')
    try {
      await onImport(text)
    } catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setBusy(true); setError('')
    try {
      await onImport(await file.text())
    } catch (e) { setError(String(e)) }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, backdropFilter: 'blur(2px)' }}
      onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="fade-in" style={{ width: '100%', maxWidth: 560, background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 14, boxShadow: '0 24px 64px rgba(0,0,0,0.5)', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 20px', borderBottom: '1px solid var(--border)' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{t('import.title')}</div>
            <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>{t('import.formats_hint')}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', display: 'flex' }}><X size={16} /></button>
        </div>

        {/* Paste area */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('import.paste_json')}</span>
              {pasteText.trim() && (() => {
                try { JSON.parse(pasteText); return <span style={{ fontSize: 10, color: '#34d399', fontWeight: 600 }}>{t('import.valid')}</span> }
                catch { return <span style={{ fontSize: 10, color: '#f87171', fontWeight: 600 }}>{t('import.invalid')}</span> }
              })()}
            </div>
            <button onClick={handleFormat} disabled={!pasteText.trim()} style={{ fontSize: 11, padding: '2px 10px', borderRadius: 6, border: '1px solid var(--border2)', background: 'transparent', color: 'var(--text3)', cursor: pasteText.trim() ? 'pointer' : 'default', opacity: pasteText.trim() ? 1 : 0.4 }}>{t('import.format_button')}</button>
          </div>
          <textarea
            value={pasteText}
            onChange={e => { setPasteText(e.target.value); setError('') }}
            placeholder={'[\n  { "id": 1, "raw": "...", "created_at": "..." },\n  ...\n]'}
            style={{
              width: '100%', height: 180, resize: 'vertical',
              background: 'var(--surface2)', border: `1px solid ${error ? '#f87171' : 'var(--border2)'}`,
              borderRadius: 8, color: 'var(--text)', fontFamily: 'monospace', fontSize: 11,
              padding: '10px 12px', outline: 'none', lineHeight: 1.6,
            }}
          />
          {error && <div style={{ fontSize: 11, color: '#f87171', marginTop: 6 }}>{error}</div>}
        </div>

        {/* Divider */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 20px' }}>
          <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>{t('common.or')}</span>
          <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
        </div>

        {/* File upload */}
        <div style={{ padding: '0 20px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', flexShrink: 0 }}>{t('import.file_select')}</div>
          <input ref={fileRef} type="file" accept=".json" onChange={handleFile}
            disabled={busy}
            style={{ fontSize: 12, color: 'var(--text2)', flex: 1 }} />
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '14px 20px', borderTop: '1px solid var(--border)' }}>
          <button onClick={onClose} className="btn btn-ghost" style={{ fontSize: 13 }}>{t('common.cancel')}</button>
          <button onClick={handleSubmit} disabled={busy || !pasteText.trim()} className="btn btn-primary" style={{ fontSize: 13, opacity: (!pasteText.trim() || busy) ? 0.4 : 1 }}>
            {busy ? t('import.importing') : t('import.import')}
          </button>
        </div>
      </div>
    </div>
  )
}

function AdminMenuItem({ icon, label, onClick, disabled, danger }: {
  icon: React.ReactNode; label: string; onClick: () => void; disabled?: boolean; danger?: boolean
}) {
  const [hover, setHover] = useState(false)
  return (
    <button onClick={onClick} disabled={disabled}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10, width: '100%',
        padding: '8px 10px', borderRadius: 8, border: 'none', cursor: disabled ? 'default' : 'pointer',
        background: hover && !disabled ? (danger ? 'rgba(248,113,113,0.08)' : 'var(--surface2)') : 'transparent',
        color: danger ? '#f87171' : 'var(--text2)',
        fontSize: 12, opacity: disabled ? 0.4 : 1,
        transition: 'background 0.1s',
      }}>
      <span style={{ color: danger ? '#f87171' : 'var(--text3)', flexShrink: 0, display: 'flex' }}>{icon}</span>
      {label}
    </button>
  )
}

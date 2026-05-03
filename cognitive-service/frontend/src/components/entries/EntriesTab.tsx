import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchEntries, fetchEntry, fetchEntryTrace, deleteEntry, revertEntry, exportEntryTrace, exportAllTraces } from '@/api'
import type { EntryDetail, TraceData, SliceFeature, SituationContext } from '@/types'
import { SCHWARTZ_COLORS, getDomainColor, getDomainLabel } from '@/lib/constants'
import { useDimensionSchemas, getDimSchema } from '@/lib/useDimensionSchemas'
import { useBackbones } from '@/lib/useBackbones'
import { useI18n } from '@/i18n'
import type { DimensionSchema } from '@/types'
import { fmtTime } from '@/lib/utils'
import { RefreshCw, Search, Trash2, ChevronRight, RotateCcw } from 'lucide-react'
import { useConfirm } from '@/components/ui/ConfirmDialog'

export function EntriesTab() {
  const qc = useQueryClient()
  const { backbones } = useBackbones()
  const { lang, t } = useI18n()
  const [selectedId, setSelectedId]    = useState<number | null>(null)
  const [traceId, setTraceId]          = useState<number | null>(null)
  const [captureText, setCaptureText]  = useState('')
  const [capturing, setCapturing]      = useState(false)
  const [revertingIds, setRevertingIds] = useState<Set<number>>(new Set())
  const confirm     = useConfirm()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['entries'], queryFn: () => fetchEntries(200),
  })

  // When the user has not picked an entry yet, fall back to the first one in
  // the list. Derived at render time (not via setState-in-effect) so React 19
  // doesn't flag a cascading-render anti-pattern.
  const effectiveSelectedId = selectedId ?? entries[0]?.id ?? null
  const { data: detail } = useQuery({
    queryKey: ['entry', effectiveSelectedId], queryFn: () => fetchEntry(effectiveSelectedId!), enabled: effectiveSelectedId !== null,
  })
  const { data: traceData } = useQuery({
    queryKey: ['trace', traceId], queryFn: () => fetchEntryTrace(traceId!), enabled: traceId !== null,
  })

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'Enter' && document.activeElement === textareaRef.current) handleCapture()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  async function handleCapture() {
    const text = captureText.trim(); if (!text || capturing) return
    setCapturing(true)
    try {
      const res = await fetch('/capture', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text, source: 'web' }) })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json() as { track: 'entry' | 'reject'; reason?: string }
      if (data.track === 'reject') {
        alert(data.reason || t('entries.write_failed', { error: 'rejected' }))
        return
      }
      setCaptureText('')
      await qc.invalidateQueries({ queryKey: ['entries'] })
      await qc.invalidateQueries({ queryKey: ['stats'] })
    } catch (err) { alert(t('entries.write_failed', { error: String(err) })) }
    finally { setCapturing(false) }
  }


  async function handleDelete(id: number, e: React.MouseEvent) {
    e.stopPropagation()
    const ok = await confirm({ title: t('entries.delete_title', { id }), message: t('entries.delete_message'), confirmLabel: t('common.delete'), danger: true })
    if (!ok) return
    await deleteEntry(id)
    if (selectedId === id) setSelectedId(null)
    await qc.invalidateQueries({ queryKey: ['entries'] })
    await qc.invalidateQueries({ queryKey: ['stats'] })
  }

  async function handleRevert(id: number, newerCount: number, e: React.MouseEvent) {
    e.stopPropagation()
    if (newerCount > 0) {
      await confirm({
        title:        t('entries.revert_blocked_title'),
        message:      t('entries.revert_blocked_msg', { n: newerCount }),
        confirmLabel: t('common.ok'),
        cancelLabel:  '',
      })
      return
    }
    const ok = await confirm({
      title: t('entries.revert_title', { id }),
      message: t('entries.revert_message', { cascade: '' }),
      confirmLabel: t('entries.revert'),
      danger: true,
    })
    if (!ok) return
    setRevertingIds(prev => new Set(prev).add(id))
    try {
      await revertEntry(id)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['entries'] }),
        qc.invalidateQueries({ queryKey: ['stats'] }),
        qc.invalidateQueries({ queryKey: ['graph'] }),
      ])
    } catch (err) { alert(t('entries.revert_failed', { error: String(err) })) }
    finally { setRevertingIds(prev => { const s = new Set(prev); s.delete(id); return s }) }
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Left list ── */}
      <div style={{
        width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: 'var(--surface)', borderRight: '1px solid var(--border)',
      }}>
        {/* Capture */}
        <div style={{ padding: '14px 14px 12px', borderBottom: '1px solid var(--border)' }}>
          <textarea
            ref={textareaRef} rows={3} value={captureText}
            onChange={e => setCaptureText(e.target.value)}
            placeholder={t('entries.write_placeholder')}
            className="input"
            style={{ resize: 'none', marginBottom: 8, lineHeight: 1.6, fontSize: 12 }}
          />
          <button onClick={handleCapture} disabled={capturing || !captureText.trim()} className="btn btn-primary" style={{ width: '100%', fontSize: 12 }}>
            {capturing ? t('entries.storing') : t('entries.store')}
          </button>
        </div>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text3)' }}>{t('entries.tab_entries')}</span>
          <button onClick={() => qc.invalidateQueries({ queryKey: ['entries'] })}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', display: 'flex', padding: 4, borderRadius: 6 }}>
            <RefreshCw size={13} />
          </button>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <>
              {isLoading && <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>{t('entries.loading')}</div>}
              {entries.map(e => {
                const isSelected = effectiveSelectedId === e.id
                return (
                  <div key={e.id} onClick={() => setSelectedId(e.id)}
                    style={{
                      padding: '12px 16px', cursor: 'pointer', borderBottom: '1px solid var(--border)',
                      background: isSelected ? 'rgba(99,102,241,0.1)' : 'transparent',
                      borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                      transition: 'background 0.1s',
                    }}>
                    <div className="line-clamp-2" style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.55, marginBottom: 8 }}>
                      {e.preview}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <StatusBadge status={e.processing_status} />
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(e.created_at)}</span>
                      {e.domains.map(d => {
                        const c = getDomainColor(d, backbones)
                        return <span key={d} className="chip" style={{ background: c + '22', color: c }}>{getDomainLabel(d, backbones, lang)}</span>
                      })}
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }} onClick={ev => ev.stopPropagation()}>
                      {e.processing_status === 'processed' && (
                        <button onClick={ev => { ev.stopPropagation(); setTraceId(e.id) }}
                          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 9px', borderRadius: 6, border: '1px solid rgba(99,102,241,0.3)', cursor: 'pointer', background: 'rgba(99,102,241,0.08)', color: 'var(--accent2)', fontSize: 11 }}>
                          <Search size={11} />Trace
                        </button>
                      )}
                      {e.can_revert && (
                        <button onClick={ev => handleRevert(e.id, e.newer_processed_count, ev)}
                          disabled={revertingIds.has(e.id)}
                          title={e.newer_processed_count > 0 ? t('entries.cascade_revert_title', { n: e.newer_processed_count }) : t('entries.revert_one_title')}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 3, padding: '3px 7px',
                            borderRadius: 6, border: '1px solid rgba(248,113,113,0.4)', cursor: 'pointer',
                            background: 'rgba(248,113,113,0.08)', color: '#f87171', fontSize: 11,
                            opacity: revertingIds.has(e.id) ? 0.5 : 1,
                          }}>
                          <RotateCcw size={11} />
                          {revertingIds.has(e.id) ? t('entries.reverting') : e.newer_processed_count > 0 ? t('entries.cascade_revert', { n: e.newer_processed_count }) : t('entries.revert')}
                        </button>
                      )}
                      <button onClick={ev => handleDelete(e.id, ev)}
                        style={{ display: 'flex', alignItems: 'center', padding: '3px 7px', borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: 'transparent', color: 'var(--text3)', fontSize: 11 }}>
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </>
        </div>
      </div>

      {/* ── Right detail ── */}
      <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
        {!effectiveSelectedId && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', gap: 8 }}>
            <ChevronRight size={28} strokeWidth={1.5} />
            <span style={{ fontSize: 13 }}>{t('entries.select_one')}</span>
          </div>
        )}
        {effectiveSelectedId && detail && (
          <EntryDetailPanel detail={detail} onTrace={() => setTraceId(effectiveSelectedId)} />
        )}
      </div>

      {/* Trace Modal */}
      {traceId !== null && (
        <TraceModal traceId={traceId} traceData={traceData} onClose={() => setTraceId(null)} />
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n()
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    captured:     { bg: 'rgba(79,90,110,0.35)',  color: '#8892a4', label: t('entries.status_captured') },
    processed:    { bg: 'rgba(16,185,129,0.15)', color: '#10b981', label: t('entries.status_processed') },
    slice_failed: { bg: 'rgba(248,113,113,0.15)', color: '#f87171', label: t('entries.status_slice_failed') },
    reverted:     { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', label: t('entries.status_reverted') },
  }
  const s = cfg[status] || cfg.captured
  return <span className="badge" style={{ background: s.bg, color: s.color }}>{s.label}</span>
}

function EntryDetailPanel({ detail, onTrace }: { detail: EntryDetail; onTrace: () => void }) {
  const schemas = useDimensionSchemas()
  const { backbones } = useBackbones()
  const { t, lang } = useI18n()
  return (
    <div style={{ padding: '24px 28px', maxWidth: 720 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <span className="badge" style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent2)', marginBottom: 8, display: 'inline-flex' }}>
            Entry #{detail.entry.id}
          </span>
          <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.7 }}>{detail.entry.raw}</div>
          <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: 'var(--text3)' }}>
            <span>{fmtTime(detail.entry.created_at)}</span>
            <StatusBadge status={detail.entry.processing_status} />
            {detail.entry.processing_status === 'processed' && (
              <button onClick={onTrace} style={{ color: 'var(--accent2)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, display: 'flex', alignItems: 'center', gap: 3 }}>
                <Search size={11} /> {t('entries.view_trace')}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Situation */}
      {detail.entry.situation && <SituationBadges sit={detail.entry.situation} />}

      {/* Features */}
      {detail.features.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div className="t-caption" style={{ marginBottom: 12 }}>{t('entries.slice_analysis')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {detail.features.map((f, i) => <FeatureBlock key={i} f={f} schemas={schemas} />)}
          </div>
        </div>
      )}

      {/* Activations */}
      {detail.activations.length > 0 && (
        <div>
          <div className="t-caption" style={{ marginBottom: 12 }}>{t('entries.activation_nodes', { n: detail.activations.length })}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {detail.activations.map((a, i) => {
              const color = getDomainColor(a.domain, backbones)
              return (
                <div key={i} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--surface2)', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: a.user_relevance ? 4 : 0 }}>
                    <span className="chip" style={{ background: color + '22', color }}>{getDomainLabel(a.domain, backbones, lang)}</span>
                    <span style={{ fontWeight: 600, fontSize: 12, color: 'var(--text)' }}>{a.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--text3)' }}>{a.node_type}</span>
                  </div>
                  {a.user_relevance && <div style={{ fontSize: 11, color: 'var(--text3)', lineHeight: 1.5 }}>{a.user_relevance}</div>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {detail.activations.length === 0 && detail.entry.processing_status !== 'processed' && (
        <div style={{ color: 'var(--text3)', fontSize: 12 }}>{t('entries.not_processed')}</div>
      )}
    </div>
  )
}

function ScoreBars({ schema, content, compact = false }: {
  schema: DimensionSchema
  content: Record<string, unknown>
  compact?: boolean
}) {
  const entries: [string, string][] = schema.sub_dimensions?.length
    ? schema.sub_dimensions.map(sd => [sd.key, sd.name])
    : Object.keys(content).map(k => [k, k])
  const sorted = schema.sort_by_score
    ? [...entries].sort(([a], [b]) => ((content[b] as Record<string, number>)?.score ?? 0) - ((content[a] as Record<string, number>)?.score ?? 0))
    : entries
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 5 : 7 }}>
      {sorted.map(([k, name], i) => {
        const v = (content[k] as Record<string, number> | undefined) ?? {}
        const score = v.score ?? 50
        const color = SCHWARTZ_COLORS[i % SCHWARTZ_COLORS.length]
        return (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: compact ? 8 : 10 }}>
            <span style={{ color: 'var(--text3)', fontSize: compact ? 10 : 11, width: compact ? 80 : 88, flexShrink: 0 }}>{name}</span>
            {compact
              ? <div style={{ width: 80, height: 4, background: 'var(--surface3)', borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
                  <div style={{ height: '100%', width: `${score}%`, background: color, borderRadius: 2 }} />
                </div>
              : <div className="bar-track"><div className="bar-fill" style={{ width: `${score}%`, background: color }} /></div>
            }
            <span style={{ color: 'var(--text2)', fontSize: compact ? 10 : 12, fontWeight: 600, width: 26, textAlign: 'right' }}>{Math.round(score)}</span>
            {!compact && <span style={{ color: 'var(--text3)', fontSize: 10, width: 30, textAlign: 'right' }}>{(v.confidence ?? 0).toFixed(1)}</span>}
          </div>
        )
      })}
    </div>
  )
}

function FeatureBlock({ f, schemas }: { f: SliceFeature; schemas: DimensionSchema[] }) {
  const c = f.content_json as Record<string, unknown>
  const schema = getDimSchema(schemas, f.dimension)
  const fmt = schema?.summary_format ?? 'free'
  const label = schema?.summary_label ?? f.dimension

  if (fmt === 'scores' && schema) {
    return (
      <div style={{ padding: '14px 16px', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)', marginBottom: 10 }}>{label}</div>
        <ScoreBars schema={schema} content={c} />
      </div>
    )
  }

  if (fmt === 'key_value') {
    const rows = Object.entries(c).filter(([, v]) => v && v !== 'null')
    if (!rows.length) return null
    return (
      <div style={{ padding: '14px 16px', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)', marginBottom: 10 }}>{label}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {rows.map(([k, v]) => {
            const val = typeof v === 'object' && v !== null && 'value' in v ? String((v as Record<string, unknown>).value) : String(v)
            return (
              <div key={k} style={{ display: 'flex', gap: 12, fontSize: 12 }}>
                <span style={{ color: 'var(--text3)', width: 64, flexShrink: 0 }}>{k}</span>
                <span style={{ color: 'var(--text)' }}>{val}</span>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)' }}>
      {label} · {JSON.stringify(c).substring(0, 120)}
    </div>
  )
}

const LEVEL_COLOR: Record<string, string> = { high: '#f87171', medium: '#f59e0b', low: '#34d399' }

function SituationBadges({ sit }: { sit: SituationContext }) {
  const { t } = useI18n()
  const FRAME_LABEL: Record<string, string> = {
    present: t('entries.frame_present'),
    retrospective: t('entries.frame_retrospective'),
    hypothetical: t('entries.frame_hypothetical'),
  }
  const STANCE_LABEL: Record<string, string> = {
    present_reflection: t('entries.stance_present'),
    recounting_past: t('entries.stance_recount'),
    mixed: t('entries.stance_mixed'),
  }
  const items: { label: string; value: string; color?: string }[] = []
  if (sit.temporal_frame) items.push({ label: t('entries.sit_temporal'), value: FRAME_LABEL[sit.temporal_frame] || sit.temporal_frame })
  if (sit.narrator_stance) items.push({ label: t('entries.sit_stance'), value: STANCE_LABEL[sit.narrator_stance] || sit.narrator_stance })
  if (sit.life_phase_ref) items.push({ label: t('entries.sit_phase'), value: sit.life_phase_ref })
  if (sit.emotional_state) items.push({ label: t('entries.sit_emotion'), value: sit.emotional_state })
  if (sit.pressure_level) items.push({ label: t('entries.sit_pressure'), value: sit.pressure_level, color: LEVEL_COLOR[sit.pressure_level] })
  if (sit.energy_level) items.push({ label: t('entries.sit_energy'), value: sit.energy_level, color: LEVEL_COLOR[sit.energy_level] })
  if (!items.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
      {items.map(({ label, value, color }) => (
        <span key={label} style={{
          fontSize: 11, padding: '3px 9px', borderRadius: 99,
          background: color ? color + '1a' : 'var(--surface2)',
          color: color || 'var(--text3)',
          border: `1px solid ${color ? color + '44' : 'var(--border)'}`,
        }}>
          <span style={{ opacity: 0.7 }}>{label} · </span>{value}
        </span>
      ))}
    </div>
  )
}

// ── Trace Modal ───────────────────────────────────────────────────────────────

const EDGE_COLORS: Record<string, string> = { supports: '#818cf8', opposes: '#f87171', derives: '#34d399', similar: '#94a3b8', related: '#64748b' }

const FIELD_HINT_KEYS: Record<string, { title: string; body: string }> = {
  conf:     { title: 'fieldHint.conf_title',     body: 'fieldHint.conf_body' },
  strength: { title: 'fieldHint.strength_title', body: 'fieldHint.strength_body' },
  weight:   { title: 'fieldHint.weight_title',   body: 'fieldHint.weight_body' },
  sim:      { title: 'fieldHint.sim_title',      body: 'fieldHint.sim_body' },
}

function FieldHint({ field }: { field: keyof typeof FIELD_HINT_KEYS }) {
  const { t } = useI18n()
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const keys = FIELD_HINT_KEYS[field]
  const doc = { title: t(keys.title as Parameters<typeof t>[0]), body: t(keys.body as Parameters<typeof t>[0]) }

  useEffect(() => {
    if (!pos) return
    const close = () => setPos(null)
    const onMouse = (e: MouseEvent) => {
      if (btnRef.current && !btnRef.current.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onMouse)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('mousedown', onMouse)
      window.removeEventListener('scroll', close, true)
    }
  }, [pos])

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (pos) { setPos(null); return }
    const r = btnRef.current!.getBoundingClientRect()
    const popW = 300
    const left = Math.min(r.left, window.innerWidth - popW - 12)
    setPos({ top: r.bottom + 6, left })
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', verticalAlign: 'middle', marginLeft: 3 }}>
      <button ref={btnRef} onClick={toggle}
        style={{
          width: 13, height: 13, borderRadius: '50%', border: '1px solid var(--border2)',
          background: pos ? 'var(--accent)' : 'var(--surface3)',
          color: pos ? '#fff' : 'var(--text3)',
          fontSize: 8, fontWeight: 700, cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          lineHeight: 1, padding: 0, flexShrink: 0,
        }}>?</button>
      {pos && createPortal(
        <div style={{
          position: 'fixed', top: pos.top, left: pos.left, zIndex: 9999,
          width: 300, background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: 10, padding: '12px 14px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>{doc.title}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{doc.body}</div>
        </div>,
        document.body
      )}
    </span>
  )
}

function TraceModal({ traceId, traceData, onClose }: { traceId: number; traceData?: TraceData; onClose: () => void }) {
  const { t } = useI18n()
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: 32, overflowY: 'auto' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="fade-in" style={{ width: '100%', maxWidth: 860, flexShrink: 0, borderRadius: 14, overflow: 'hidden', background: 'var(--surface)', border: '1px solid var(--border2)' }}>
        <div style={{ position: 'sticky', top: 0, display: 'flex', alignItems: 'center', padding: '16px 20px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', zIndex: 2 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Pipeline Trace — Entry #{traceId}</div>
            {traceData?.updated_at && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{t('entries.trace_run_at', { time: fmtTime(traceData.updated_at) })}</div>}
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={() => exportEntryTrace(traceId).catch(e => alert(t('entries.export_failed', { error: e.message ?? e })))}
              title={t('entries.export_one_title')}
              style={{ fontSize: 12, padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border2)', background: 'var(--surface2)', color: 'var(--text)', cursor: 'pointer' }}>
              {t('entries.export_one')}
            </button>
            <button
              onClick={() => exportAllTraces().catch(e => alert(t('entries.export_failed', { error: e.message ?? e })))}
              title={t('entries.export_all_title')}
              style={{ fontSize: 12, padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border2)', background: 'var(--surface2)', color: 'var(--text)', cursor: 'pointer' }}>
              {t('entries.export_all')}
            </button>
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: 18, lineHeight: 1 }}>✕</button>
          </div>
        </div>
        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {!traceData && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 8 }}>{t('entries.loading')}</div>}
          {traceData && !traceData.trace && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 8 }}>{t('entries.no_trace')}</div>}
          {traceData?.trace && <TraceStages trace={traceData.trace} />}
        </div>
      </div>
    </div>
  )
}

function TraceStages({ trace }: { trace: NonNullable<TraceData['trace']> }) {
  const { t } = useI18n()
  return (
    <>
      <TraceStage num="1" title={t('entries.stage_slice')} data={trace.slice}><SliceContent slice={trace.slice} /></TraceStage>
      <TraceStage num="2" title="Profile Diff" data={trace.profile_diff}><ProfileDiffContent diff={trace.profile_diff} /></TraceStage>
      <TraceStage num="3" title={t('entries.stage_activation')} data={trace.activation}><ActivationContent act={trace.activation} /></TraceStage>
      <TraceStage num="4" title={t('entries.stage_rough_recall')} data={trace.rough_retrieval} collapsed><RoughRetrievalContent nodes={trace.rough_retrieval} /></TraceStage>
      <TraceStage num="5" title={t('entries.stage_node_extract')} data={trace.node_extract}><NodeExtractContent extract={trace.node_extract} /></TraceStage>
      <TraceStage num="6" title="Confirmed Nodes" data={trace.confirmed_nodes}><ConfirmedNodesContent nodes={trace.confirmed_nodes} /></TraceStage>
      <TraceStage num="7" title={t('entries.stage_subgraph')} data={trace.subgraph} collapsed><SubgraphContent sg={trace.subgraph} /></TraceStage>
      <TraceStage num="8" title={t('entries.stage_edge_extract')} data={trace.edge_extract}><EdgeExtractContent edges={trace.edge_extract} /></TraceStage>
      <TraceStage num="9" title={t('entries.stage_db_diff')} data={trace.db_diff}><DbDiffContent diff={trace.db_diff} /></TraceStage>
    </>
  )
}

function TraceStage({ num, title, data, collapsed = false, children }: {
  num: string; title: string; data: unknown; collapsed?: boolean; children: React.ReactNode
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(!collapsed)
  const isEmpty = !data || (Array.isArray(data) && !data.length) || (typeof data === 'object' && !Array.isArray(data) && !Object.keys(data as object).length)
  const count = Array.isArray(data) ? data.length : (data && typeof data === 'object' ? Object.keys(data as object).length : 0)
  const badge = isEmpty ? t('entries.badge_empty') : count > 0 ? t('entries.badge_n_items', { n: count }) : t('entries.badge_has_data')
  return (
    <div style={{ borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: 'var(--surface2)', cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen(v => !v)}>
        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 99, background: 'var(--accent)', color: '#fff' }}>{num}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{title}</span>
        <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 99, fontWeight: 500, background: isEmpty ? 'rgba(79,90,110,0.25)' : 'rgba(16,185,129,0.15)', color: isEmpty ? 'var(--text3)' : '#10b981' }}>{badge}</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
      </div>
      {open && <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', fontSize: 11 }}>{children}</div>}
    </div>
  )
}

function TEmpty({ text }: { text?: string }) {
  const { t } = useI18n()
  return <div style={{ color: 'var(--text3)', fontSize: 11 }}>{text ?? t('entries.empty_text')}</div>
}

function TTable({ headers, rows }: { headers: React.ReactNode[]; rows: React.ReactNode[][] }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
      <thead>
        <tr>{headers.map((h, i) => <th key={i} style={{ textAlign: 'left', padding: '5px 8px', color: 'var(--text3)', borderBottom: '1px solid var(--border)', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>{row.map((cell, j) => <td key={j} style={{ padding: '5px 8px', color: 'var(--text2)', borderBottom: i < rows.length - 1 ? '1px solid rgba(37,42,61,0.8)' : 'none', verticalAlign: 'top' }}>{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  )
}

function DPill({ domain }: { domain: string }) {
  const { backbones } = useBackbones()
  const { lang } = useI18n()
  const c = getDomainColor(domain, backbones)
  return <span className="chip" style={{ background: c + '22', color: c }}>{getDomainLabel(domain, backbones, lang)}</span>
}

function SliceContent({ slice }: { slice: NonNullable<TraceData['trace']>['slice'] }) {
  const schemas = useDimensionSchemas()
  const { t } = useI18n()
  if (!slice || !Object.keys(slice).length) return <TEmpty text={t('entries.no_slice')} />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {Object.entries(slice).map(([dim, data]) => {
        const schema = getDimSchema(schemas, dim)
        const label = schema?.summary_label ?? dim
        return (
          <div key={dim}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', marginBottom: 8, textTransform: 'uppercase' }}>
              {label} <span style={{ fontWeight: 400 }}>conf={data.confidence?.toFixed(2)}<FieldHint field="conf" /></span>
            </div>
            {schema?.summary_format === 'scores'
              ? <ScoreBars schema={schema} content={data.content as Record<string, unknown>} compact />
              : <div style={{ color: 'var(--text2)', fontFamily: 'monospace', fontSize: 10, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>{JSON.stringify(data.content, null, 2).substring(0, 300)}</div>
            }
          </div>
        )
      })}
    </div>
  )
}

function ProfileDiffContent({ diff }: { diff: NonNullable<TraceData['trace']>['profile_diff'] }) {
  const { t } = useI18n()
  if (!diff || !Object.keys(diff).length) return <TEmpty text={t('entries.no_change')} />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(diff).map(([dim, keys]) => (
        <div key={dim}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>{dim}</div>
          <TTable headers={[t('entries.th_field'), t('entries.th_score'), 'Δ', <span>conf<FieldHint field="conf" /></span>]}
            rows={Object.entries(keys as Record<string, Record<string, number>>).map(([k, v]) => [
              k,
              'delta' in v ? `${v.score_before} → ${v.score_after}` : `${JSON.stringify((v as unknown as Record<string, unknown>).before)} → ${JSON.stringify((v as unknown as Record<string, unknown>).after)}`,
              'delta' in v ? <span style={{ color: v.delta > 0 ? '#10b981' : '#f87171', fontWeight: 700 }}>{v.delta > 0 ? '+' : ''}{v.delta}</span> : '—',
              'delta' in v ? `${v.conf_before} → ${v.conf_after}` : '—',
            ])}
          />
        </div>
      ))}
    </div>
  )
}

function ActivationContent({ act }: { act: NonNullable<TraceData['trace']>['activation'] }) {
  const { backbones } = useBackbones()
  const { t } = useI18n()
  if (!act || !Object.keys(act).length) return <TEmpty text={t('entries.no_activation')} />
  return (
    <TTable headers={[t('entries.th_domain_act'), 'effort_weight', '']}
      rows={Object.entries(act).sort(([, a], [, b]) => b - a).map(([domain, w]) => {
        const c = getDomainColor(domain, backbones)
        return [
          <DPill domain={domain} />,
          w.toFixed(3),
          <div style={{ width: 100, height: 4, background: 'var(--surface3)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${w * 100}%`, background: c, borderRadius: 2 }} />
          </div>,
        ]
      })}
    />
  )
}

function RoughRetrievalContent({ nodes }: { nodes: NonNullable<TraceData['trace']>['rough_retrieval'] }) {
  const { t } = useI18n()
  if (!nodes?.length) return <TEmpty text={t('entries.empty_text')} />
  return <TTable headers={[t('entries.th_label'), t('entries.th_domain'), t('entries.th_type'), <span>strength<FieldHint field="strength" /></span>, <span>sim<FieldHint field="sim" /></span>]}
    rows={nodes.map(n => [n.label, <DPill domain={n.domain} />, n.node_type, n.strength.toFixed(3), <span style={{ color: '#10b981' }}>{n.sim.toFixed(3)}</span>])} />
}

function NodeExtractContent({ extract }: { extract: NonNullable<TraceData['trace']>['node_extract'] }) {
  const { backbones } = useBackbones()
  const { lang, t } = useI18n()
  if (!extract || !Object.keys(extract).length) return <TEmpty text={t('entries.no_extract')} />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(extract).map(([domain, nodes]) => {
        const c = getDomainColor(domain, backbones)
        return (
          <div key={domain}>
            <div style={{ fontSize: 10, fontWeight: 600, color: c, marginBottom: 6 }}>{t('entries.domain_n_nodes', { domain: getDomainLabel(domain, backbones, lang), n: nodes.length })}</div>
            {nodes.length === 0 ? <TEmpty /> : (
              <TTable headers={[t('entries.th_label'), t('entries.th_type'), <span>conf<FieldHint field="conf" /></span>, t('entries.th_description')]}
                rows={nodes.map(n => [n.label, n.node_type, n.confidence.toFixed(2), <span style={{ color: 'var(--text3)', display: 'block', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.description || ''}</span>])} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function ConfirmedNodesContent({ nodes }: { nodes: NonNullable<TraceData['trace']>['confirmed_nodes'] }) {
  const { t } = useI18n()
  if (!nodes?.length) return <TEmpty text={t('entries.no_confirmed')} />
  return <TTable headers={[t('entries.th_label'), t('entries.th_domain'), t('entries.th_type'), t('entries.th_status'), <span>strength<FieldHint field="strength" /></span>, <span>conf<FieldHint field="conf" /></span>]}
    rows={nodes.map(n => [
      n.label, <DPill domain={n.domain} />, n.node_type,
      <span className="badge" style={n.is_new ? { background: 'rgba(16,185,129,0.15)', color: '#10b981' } : { background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>{n.is_new ? t('entries.badge_new') : t('entries.badge_hit')}</span>,
      n.strength.toFixed(3), n.new_conf != null ? n.new_conf.toFixed(3) : '—',
    ])} />
}

function SubgraphContent({ sg }: { sg: NonNullable<TraceData['trace']>['subgraph'] }) {
  const { t } = useI18n()
  if (!sg) return <TEmpty text={t('entries.no_subgraph')} />
  const nodes = sg.nodes || [], edges = sg.edges || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ color: 'var(--text3)', fontSize: 11 }}>{t('entries.nodes_edges_label', { nodes: nodes.length, edges: edges.length })}</div>
      {nodes.length > 0 && <TTable headers={[t('entries.th_label'), t('entries.th_domain'), <span>strength<FieldHint field="strength" /></span>]} rows={nodes.map(n => [n.label, <DPill domain={n.domain} />, n.strength.toFixed(3)])} />}
      {edges.length > 0 && <TTable headers={['from', t('entries.th_relation'), 'to', <span>weight<FieldHint field="weight" /></span>]}
        rows={edges.map(e => [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label, (e.weight ?? 0).toFixed(3)])} />}
    </div>
  )
}

function EdgeExtractContent({ edges }: { edges: NonNullable<TraceData['trace']>['edge_extract'] }) {
  const { t } = useI18n()
  if (!edges?.length) return <TEmpty text={t('entries.no_edge_extract')} />
  return <TTable headers={['from', t('entries.th_relation'), 'to', t('entries.th_direction'), <span>conf<FieldHint field="conf" /></span>, t('entries.th_evidence')]}
    rows={edges.map(e => [
      e.from_label,
      <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>,
      e.to_label,
      <span style={{ color: 'var(--text3)' }}>{e.direction}</span>,
      e.confidence.toFixed(2),
      <span style={{ color: 'var(--text3)', display: 'block', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 10 }}>{e.evidence || ''}</span>,
    ])} />
}

function DbDiffContent({ diff }: { diff: NonNullable<TraceData['trace']>['db_diff'] }) {
  const { t } = useI18n()
  if (!diff) return <TEmpty text={t('entries.no_diff')} />
  const { nodes_new: nn = [], nodes_updated: nu = [], edges_new: en = [], edges_updated: eu = [] } = diff
  if (!nn.length && !nu.length && !en.length && !eu.length) return <TEmpty text={t('entries.no_db_change')} />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {nn.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981' }}>{t('entries.new_nodes_n', { n: nn.length })}</div>
        <TTable headers={[t('entries.th_id'), t('entries.th_label'), t('entries.th_domain'), t('entries.th_type'), <span>strength<FieldHint field="strength" /></span>]}
          rows={nn.map(n => [`#${n.id}`, n.label, <DPill domain={n.domain} />, n.node_type, n.strength.toFixed(3)])} />
      </>}
      {nu.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#818cf8' }}>{t('entries.update_nodes_n', { n: nu.length })}</div>
        <TTable headers={[t('entries.th_label'), t('entries.th_domain'), <span>before<FieldHint field="strength" /></span>, 'after', 'Δ']}
          rows={nu.map(n => {
            const d = n.strength_after - n.strength_before
            return [n.label, <DPill domain={n.domain} />, n.strength_before.toFixed(3), n.strength_after.toFixed(3), <span style={{ color: d > 0 ? '#10b981' : '#f87171', fontWeight: 700 }}>{d > 0 ? '+' : ''}{d.toFixed(3)}</span>]
          })} />
      </>}
      {en.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981' }}>{t('entries.new_edges_n', { n: en.length })}</div>
        <TTable headers={['from', t('entries.th_relation'), 'to', <span>weight<FieldHint field="weight" /></span>]}
          rows={en.map(e => [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label, (e.weight ?? 0).toFixed(3)])} />
      </>}
      {eu.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#818cf8' }}>{t('entries.update_edges_n', { n: eu.length })}</div>
        <TTable headers={['from', t('entries.th_relation'), 'to', <span>weight delta<FieldHint field="weight" /></span>]}
          rows={eu.map(e => {
            const dw = (e.weight_after ?? 0) - (e.weight_before ?? 0)
            return [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label,
              <span>{(e.weight_before ?? 0).toFixed(3)} → <b>{(e.weight_after ?? 0).toFixed(3)}</b> <span style={{ color: dw >= 0 ? '#10b981' : '#f87171', fontWeight: 700 }}>{dw >= 0 ? '+' : ''}{dw.toFixed(3)}</span></span>]
          })} />
      </>}
    </div>
  )
}

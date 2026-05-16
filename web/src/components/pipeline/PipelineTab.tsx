import { useState, useMemo } from 'react'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  fetchPipelineEntries, fetchPipelineHealth, fetchEntryTrace, fetchEntry, replayProfileMerge, replayNodeStrength,
  fetchBackbones,
} from '@/api'
import type { PipelineHealthRow, ReplayResult, NodeStrengthReplayResult } from '@/api'
import { fmtTime } from '@/lib/utils'
import { useDimensionSchemas } from '@/lib/useDimensionSchemas'
import { useI18n } from '@/i18n'
import { RefreshCw, Activity, BarChart3, Wrench, ChevronDown, ChevronRight } from 'lucide-react'
import { TraceDetail } from './TraceDetail'

export function PipelineTab() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [toolsOpen, setToolsOpen] = useState(false)

  const { data: entries = [] } = useQuery({
    queryKey: ['pipeline-entries'],
    // 200 to match the Reflections tab's fetchEntries(200) — otherwise the
    // two tabs show different sets when the user has > 50 entries.
    queryFn:  () => fetchPipelineEntries(200),
  })
  const { data: health, refetch: refetchHealth } = useQuery({
    queryKey: ['pipeline-health'],
    queryFn:  () => fetchPipelineHealth(100),
  })
  const effectiveId = selectedId ?? entries[0]?.id ?? null
  const { data: traceData, isLoading: traceLoading, isFetching: traceFetching } = useQuery({
    queryKey: ['pipeline-trace', effectiveId],
    queryFn:  () => fetchEntryTrace(effectiveId!),
    enabled:  effectiveId !== null,
    // Keep showing the previous entry's trace while the new one loads.
    // Prevents the right pane from collapsing to "No trace" mid-switch and
    // causing the Tools section to jump.
    placeholderData: keepPreviousData,
  })
  const { data: entryDetail } = useQuery({
    queryKey: ['pipeline-entry-detail', effectiveId],
    queryFn:  () => fetchEntry(effectiveId!),
    enabled:  effectiveId !== null,
    placeholderData: keepPreviousData,
  })

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Left: entry picker */}
      <div style={{
        width: 260, flexShrink: 0, borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: 'var(--surface)',
      }}>
        <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{t('pipeline.title')}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4, lineHeight: 1.5 }}>
            {t('pipeline.subtitle')}
          </div>
        </div>
        <div style={{ padding: '8px 0', overflow: 'auto', flex: 1 }}>
          <div style={{ padding: '0 16px 6px', fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {t('pipeline.select_entry')}
          </div>
          {entries.length === 0 && (
            <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--text3)' }}>{t('pipeline.no_entries')}</div>
          )}
          {entries.map(e => (
            <button key={e.id}
              onClick={() => setSelectedId(e.id)}
              style={{
                width: '100%', textAlign: 'left',
                padding: '8px 16px', border: 'none', cursor: 'pointer',
                background: e.id === effectiveId ? 'var(--engram-tint-primary)' : 'transparent',
                color: e.id === effectiveId ? 'var(--engram-accent-primary)' : 'var(--text2)',
                borderLeft: e.id === effectiveId ? '2px solid var(--engram-accent-primary)' : '2px solid transparent',
                fontSize: 12, transition: 'background 0.1s',
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                <span style={{ fontWeight: 600 }}>#{e.id}</span>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(e.created_at)}</span>
              </div>
              <div style={{
                fontSize: 11, color: 'var(--text3)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>{e.preview || t('pipeline.none_yet')}</div>
              {!e.has_trace && (
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2, fontStyle: 'italic' }}>
                  ({e.processing_status})
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Right: detail */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        {/* 1. Health metrics — daily monitoring tool, place at top */}
        <Section
          icon={<BarChart3 size={14} />}
          title={t('pipeline.health_title')}
          subtitle={t('pipeline.health_subtitle', { n: health?.entries_with_health ?? 0 })}
          right={
            <button onClick={() => refetchHealth()} className="btn btn-ghost" style={{ fontSize: 11, padding: '2px 8px' }}>
              <RefreshCw size={11} />
            </button>
          }
        >
          <HealthTable rows={health?.by_dimension ?? []} />
        </Section>

        {/* 2. Trace drill-down — main debug / recall surface.
            min-height stops the Tools section below from jumping when the
            selected entry has a smaller trace than the previous one. */}
        <Section
          icon={<Activity size={14} />}
          title={t('pipeline.trace_title')}
          subtitle={effectiveId ? `entry #${effectiveId}${traceFetching && !traceLoading ? ' · refreshing…' : ''}` : t('pipeline.trace_no_entry_selected')}
        >
          <div style={{ minHeight: 480 }}>
            {traceLoading && <div style={{ fontSize: 12, color: 'var(--text3)', padding: 8 }}>{t('common.loading')}</div>}
            {!traceLoading && traceData?.trace
              ? <TraceDetail trace={traceData.trace} raw={entryDetail?.entry?.raw || ''} />
              : !traceLoading && <div style={{ fontSize: 12, color: 'var(--text3)', padding: 8 }}>{t('pipeline.no_trace')}</div>}
          </div>
        </Section>

        {/* 3. Tools — algorithm tuning utilities (Profile/Strength replay), collapsible */}
        <Section
          icon={<Wrench size={14} />}
          title={t('pipeline.tools_title')}
          subtitle={t('pipeline.tools_subtitle')}
          right={
            <button onClick={() => setToolsOpen(v => !v)} className="btn btn-ghost" style={{ fontSize: 11, padding: '2px 8px', display: 'flex', alignItems: 'center', gap: 4 }}>
              {toolsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              {toolsOpen ? t('pipeline.tools_hide') : t('pipeline.tools_show')}
            </button>
          }
        >
          {toolsOpen && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <SubSection title={t('pipeline.replay_title')} subtitle={t('pipeline.replay_subtitle')}>
                <ReplayPanel onDone={() => { qc.invalidateQueries({ queryKey: ['pipeline-health'] }); qc.invalidateQueries({ queryKey: ['profile'] }); qc.invalidateQueries({ queryKey: ['profile-evolution'] }) }} />
              </SubSection>
              <SubSection title={t('pipeline.strength_replay_title')} subtitle={t('pipeline.strength_replay_subtitle')}>
                <NodeStrengthReplayPanel onDone={() => { qc.invalidateQueries({ queryKey: ['graph'] }) }} />
              </SubSection>
            </div>
          )}
        </Section>
      </div>
    </div>
  )
}


// ── Sub-section wrapper inside Tools ─────────────────────────────────────────

function SubSection({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '10px 12px', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 6 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
      {subtitle && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2, marginBottom: 8, lineHeight: 1.5 }}>{subtitle}</div>}
      {children}
    </div>
  )
}


// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({ icon, title, subtitle, right, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div style={{
      margin: '14px 18px 0', padding: '14px 16px',
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
            <span style={{ color: 'var(--engram-accent-primary)' }}>{icon}</span>
            {title}
          </div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3 }}>{subtitle}</div>}
        </div>
        {right}
      </div>
      {children}
    </div>
  )
}


// ── Replay panel ─────────────────────────────────────────────────────────────

function ReplayPanel({ onDone }: { onDone: () => void }) {
  const { t } = useI18n()
  const schemas = useDimensionSchemas()
  const [dim, setDim]       = useState<string>('')
  const [limit, setLimit]   = useState<string>('')
  const [busy, setBusy]     = useState(false)
  const [result, setResult] = useState<(ReplayResult & { dry_run?: boolean }) | null>(null)
  const [err, setErr]       = useState<string>('')

  const scoreDims = useMemo(
    () => schemas.filter(s => s.summary_format === 'scores' && s.enabled !== false),
    [schemas],
  )

  async function run(dryRun: boolean) {
    setBusy(true); setResult(null); setErr('')
    try {
      const opts: { dimension?: string; limit?: number; dry_run?: boolean } = { dry_run: dryRun }
      if (dim) opts.dimension = dim
      if (limit) opts.limit = parseInt(limit, 10)
      const r = await replayProfileMerge(opts)
      setResult(r)
      if (!dryRun) onDone()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={dim} onChange={e => setDim(e.target.value)} disabled={busy}
          style={{
            fontSize: 11, padding: '5px 8px', borderRadius: 6,
            background: 'var(--surface)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}>
          <option value="">{t('pipeline.replay_dimension_all')}</option>
          {scoreDims.map(s => <option key={s.key} value={s.key}>{s.name || s.key}</option>)}
        </select>
        <input type="number" min="1" placeholder={t('pipeline.replay_limit_all')}
          value={limit} onChange={e => setLimit(e.target.value)} disabled={busy}
          style={{
            fontSize: 11, padding: '5px 8px', borderRadius: 6, width: 100,
            background: 'var(--surface)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}/>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button onClick={() => run(true)} disabled={busy} className="btn btn-ghost" style={{ fontSize: 11 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.replay_preview_button')}
        </button>
        <button onClick={() => run(false)} disabled={busy} className="btn btn-primary" style={{ fontSize: 11 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.replay_apply_button')}
        </button>
      </div>
      {result && (
        <div style={{ marginTop: 10, fontSize: 11, color: result.dry_run ? 'var(--text2)' : 'var(--engram-accent-success)' }}>
          {result.dry_run ? '(preview · DB unchanged) ' : '✓ Applied · '}
          {t('pipeline.replay_done', {
            entries: result.entries_processed,
            features: result.slice_features_replayed,
            dims: result.dimensions_touched,
            snaps: result.snapshots_written,
          })}
        </div>
      )}
      {err && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--engram-accent-warning)' }}>
          {t('pipeline.replay_failed', { error: err })}
        </div>
      )}
    </div>
  )
}


// ── Node strength replay panel ───────────────────────────────────────────────

function NodeStrengthReplayPanel({ onDone }: { onDone: () => void }) {
  const { t } = useI18n()
  const { data: bbInfo } = useQuery({ queryKey: ['backbones'], queryFn: fetchBackbones })
  const [domain, setDomain]   = useState<string>('')
  const [busy, setBusy]       = useState(false)
  const [result, setResult]   = useState<(NodeStrengthReplayResult & { dry_run?: boolean }) | null>(null)
  const [err, setErr]         = useState<string>('')

  async function run(dryRun: boolean) {
    setBusy(true); setResult(null); setErr('')
    try {
      const opts: { domain?: string; dry_run?: boolean } = { dry_run: dryRun }
      if (domain) opts.domain = domain
      const r = await replayNodeStrength(opts)
      setResult(r)
      if (!dryRun) onDone()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={domain} onChange={e => setDomain(e.target.value)} disabled={busy}
          style={{
            fontSize: 11, padding: '5px 8px', borderRadius: 6,
            background: 'var(--surface)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}>
          <option value="">{t('pipeline.strength_replay_domain_all')}</option>
          {(bbInfo?.backbones ?? []).map(b => (
            <option key={b.key} value={b.key}>{b.name || b.key}</option>
          ))}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button onClick={() => run(true)} disabled={busy} className="btn btn-ghost" style={{ fontSize: 11 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.replay_preview_button')}
        </button>
        <button onClick={() => run(false)} disabled={busy} className="btn btn-primary" style={{ fontSize: 11 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.replay_apply_button')}
        </button>
      </div>
      {result && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: result.dry_run ? 'var(--text2)' : 'var(--engram-accent-success)', marginBottom: 8 }}>
            {result.dry_run ? '(preview · DB unchanged) ' : '✓ Applied · '}
            {t('pipeline.strength_replay_done', {
              nodes: result.nodes_touched,
              acts: result.activations_replayed,
              max: result.max_strength.toFixed(2),
              median: result.median_strength.toFixed(2),
            })}
          </div>
          {Object.keys(result.histogram || {}).length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
                {t('pipeline.strength_distribution')}
              </div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {Object.entries(result.histogram).map(([bucket, n]) => (
                  <span key={bucket} style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 10,
                    background: 'var(--surface2)', color: 'var(--text2)',
                    fontFamily: 'monospace',
                  }}>{bucket}: {n}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {err && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--engram-accent-warning)' }}>
          {t('pipeline.replay_failed', { error: err })}
        </div>
      )}
    </div>
  )
}


// ── Health table ─────────────────────────────────────────────────────────────

function HealthTable({ rows }: { rows: PipelineHealthRow[] }) {
  const { t } = useI18n()

  if (rows.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text3)' }}>{t('pipeline.health_no_data')}</div>
  }

  const cellStyle: React.CSSProperties = { padding: '6px 8px', fontSize: 12, color: 'var(--text2)' }
  const numStyle: React.CSSProperties  = { ...cellStyle, fontFamily: 'monospace', textAlign: 'right' }

  return (
    <div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ ...cellStyle, textAlign: 'left', fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('pipeline.th_dimension')}</th>
            <th style={{ ...numStyle, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('pipeline.th_obs')}</th>
            <th style={{ ...numStyle, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('pipeline.th_null')}</th>
            <th style={{ ...numStyle, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('pipeline.th_low_conf')}</th>
            <th style={{ ...numStyle, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('pipeline.th_hedge')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.dimension} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ ...cellStyle, fontWeight: 600 }}>{r.dimension}</td>
              <td style={numStyle}>{r.subdim_observations}</td>
              <td style={{ ...numStyle, color: ratioColor(r.null_ratio, 'good') }}>{(r.null_ratio * 100).toFixed(1)}%</td>
              <td style={{ ...numStyle, color: ratioColor(r.low_conf_ratio, 'bad') }}>{(r.low_conf_ratio * 100).toFixed(1)}%</td>
              <td style={{ ...numStyle, color: ratioColor(r.midpoint_hedge_ratio, 'bad') }}>{(r.midpoint_hedge_ratio * 100).toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text3)', lineHeight: 1.7 }}>
        <div>· {t('pipeline.health_legend_null')}</div>
        <div>· {t('pipeline.health_legend_low')}</div>
        <div>· {t('pipeline.health_legend_hedge')}</div>
      </div>
    </div>
  )
}

function ratioColor(r: number, semantic: 'good' | 'bad'): string {
  // For "good" metrics (null), high = good (success color)
  // For "bad" metrics (low_conf, hedge), high = bad (warning color)
  if (semantic === 'good') {
    if (r > 0.3) return 'var(--engram-accent-success)'
    if (r > 0.1) return 'var(--text2)'
    return 'var(--text3)'
  }
  if (r > 0.15) return 'var(--engram-accent-warning)'
  if (r > 0.05) return 'var(--text2)'
  return 'var(--text3)'
}



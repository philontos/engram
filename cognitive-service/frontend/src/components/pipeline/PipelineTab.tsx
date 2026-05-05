import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchPipelineEntries, fetchPipelineHealth, fetchEntryTrace, replayProfileMerge, replayNodeStrength,
  fetchBackbones,
} from '@/api'
import type { PipelineHealthRow, ReplayResult, NodeStrengthReplayResult } from '@/api'
import type { TraceData } from '@/types'
import { fmtTime } from '@/lib/utils'
import { useDimensionSchemas } from '@/lib/useDimensionSchemas'
import { useI18n } from '@/i18n'
import { RefreshCw, Activity, BarChart3, Zap } from 'lucide-react'

export function PipelineTab() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: entries = [] } = useQuery({
    queryKey: ['pipeline-entries'],
    queryFn:  () => fetchPipelineEntries(50),
  })
  const { data: health, refetch: refetchHealth } = useQuery({
    queryKey: ['pipeline-health'],
    queryFn:  () => fetchPipelineHealth(100),
  })
  const effectiveId = selectedId ?? entries[0]?.id ?? null
  const { data: traceData, isLoading: traceLoading } = useQuery({
    queryKey: ['pipeline-trace', effectiveId],
    queryFn:  () => fetchEntryTrace(effectiveId!),
    enabled:  effectiveId !== null,
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
        {/* Profile merge replay */}
        <Section icon={<Zap size={14} />} title={t('pipeline.replay_title')} subtitle={t('pipeline.replay_subtitle')}>
          <ReplayPanel onDone={() => { qc.invalidateQueries({ queryKey: ['pipeline-health'] }); qc.invalidateQueries({ queryKey: ['profile'] }); qc.invalidateQueries({ queryKey: ['profile-evolution'] }) }} />
        </Section>

        {/* Node strength replay */}
        <Section icon={<Zap size={14} />} title={t('pipeline.strength_replay_title')} subtitle={t('pipeline.strength_replay_subtitle')}>
          <NodeStrengthReplayPanel onDone={() => { qc.invalidateQueries({ queryKey: ['graph'] }) }} />
        </Section>

        {/* Health metrics */}
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

        {/* Timeline */}
        <Section icon={<Activity size={14} />} title={t('pipeline.timeline_title')} subtitle={effectiveId ? `entry #${effectiveId}` : ''}>
          {traceLoading && <div style={{ fontSize: 12, color: 'var(--text3)', padding: 8 }}>{t('common.loading')}</div>}
          {!traceLoading && traceData?.trace
            ? <Timeline trace={traceData.trace} />
            : <div style={{ fontSize: 12, color: 'var(--text3)', padding: 8 }}>{t('pipeline.no_trace')}</div>}
        </Section>
      </div>
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
  const [result, setResult] = useState<ReplayResult | null>(null)
  const [err, setErr]       = useState<string>('')

  const scoreDims = useMemo(
    () => schemas.filter(s => s.summary_format === 'scores' && s.enabled !== false),
    [schemas],
  )

  async function run() {
    setBusy(true); setResult(null); setErr('')
    try {
      const opts: { dimension?: string; limit?: number } = {}
      if (dim) opts.dimension = dim
      if (limit) opts.limit = parseInt(limit, 10)
      const r = await replayProfileMerge(opts)
      setResult(r)
      onDone()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={dim} onChange={e => setDim(e.target.value)} disabled={busy}
          style={{
            fontSize: 12, padding: '6px 10px', borderRadius: 6,
            background: 'var(--surface2)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}>
          <option value="">{t('pipeline.replay_dimension_all')}</option>
          {scoreDims.map(s => <option key={s.key} value={s.key}>{s.name || s.key}</option>)}
        </select>
        <input type="number" min="1" placeholder={t('pipeline.replay_limit_all')}
          value={limit} onChange={e => setLimit(e.target.value)} disabled={busy}
          style={{
            fontSize: 12, padding: '6px 10px', borderRadius: 6, width: 130,
            background: 'var(--surface2)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}/>
        <button onClick={run} disabled={busy} className="btn btn-primary" style={{ fontSize: 12 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.replay_button')}
        </button>
      </div>
      {result && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--engram-accent-success)' }}>
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
  const [result, setResult]   = useState<NodeStrengthReplayResult | null>(null)
  const [err, setErr]         = useState<string>('')

  async function run() {
    setBusy(true); setResult(null); setErr('')
    try {
      const opts: { domain?: string } = {}
      if (domain) opts.domain = domain
      const r = await replayNodeStrength(opts)
      setResult(r)
      onDone()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={domain} onChange={e => setDomain(e.target.value)} disabled={busy}
          style={{
            fontSize: 12, padding: '6px 10px', borderRadius: 6,
            background: 'var(--surface2)', border: '1px solid var(--border2)', color: 'var(--text)',
          }}>
          <option value="">{t('pipeline.strength_replay_domain_all')}</option>
          {(bbInfo?.backbones ?? []).map(b => (
            <option key={b.key} value={b.key}>{b.name || b.key}</option>
          ))}
        </select>
        <button onClick={run} disabled={busy} className="btn btn-primary" style={{ fontSize: 12 }}>
          {busy ? t('pipeline.replay_running') : t('pipeline.strength_replay_button')}
        </button>
      </div>
      {result && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--engram-accent-success)', marginBottom: 8 }}>
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


// ── Pipeline timeline ────────────────────────────────────────────────────────

type TraceObj = NonNullable<TraceData['trace']>

function Timeline({ trace }: { trace: TraceObj }) {
  const { t } = useI18n()

  // Stage definitions — derived from what data exists in trace
  const slice  = trace.slice
  const prof   = trace.profile_diff
  const health = (trace as any).slice_extraction_health as Record<string, { total: number; null_count: number; low_conf_count: number; midpoint_hedge_count: number }> | undefined
  const act    = trace.activation
  const ndExt  = trace.node_extract
  const edExt  = trace.edge_extract
  const dbDiff = trace.db_diff
  const llm    = (trace as any).llm_summary as { count?: number; total_tokens?: number; duration_ms?: number } | undefined

  type Stage = { key: string; label: string; details: React.ReactNode; status: 'done' | 'skipped' }
  const stages: Stage[] = []

  if (slice) {
    const featureCount = Array.isArray(slice) ? slice.length : Object.keys(slice).length
    stages.push({
      key: 'slice', label: t('pipeline.stage_slice'), status: 'done',
      details: (
        <div>
          <Tag>{t('pipeline.feature_count_n', { n: featureCount })}</Tag>
          {health && Object.entries(health).map(([dim, h]) => (
            <Tag key={dim} variant="muted">
              {dim}: null={h.null_count}/{h.total} · low={h.low_conf_count} · hedge={h.midpoint_hedge_count}
            </Tag>
          ))}
        </div>
      ),
    })
  }

  if (prof) {
    const subdimChangedCount = Object.values(prof).reduce((acc, v) => acc + Object.keys(v).length, 0)
    stages.push({
      key: 'profile', label: t('pipeline.stage_profile'), status: subdimChangedCount > 0 ? 'done' : 'skipped',
      details: <Tag>{t('pipeline.profile_changed_n', { n: subdimChangedCount })}</Tag>,
    })
  }

  if (act || ndExt || edExt || dbDiff) {
    const nodesNew = (dbDiff as any)?.nodes_new?.length ?? 0
    const nodesUpd = (dbDiff as any)?.nodes_updated?.length ?? 0
    const edgesNew = (dbDiff as any)?.edges_new?.length ?? 0
    const edgesUpd = (dbDiff as any)?.edges_updated?.length ?? 0
    stages.push({
      key: 'backbone', label: t('pipeline.stage_backbone'), status: 'done',
      details: (
        <div>
          <Tag>{t('pipeline.nodes_n', { n: nodesNew + nodesUpd })}</Tag>
          <Tag>{t('pipeline.edges_n', { n: edgesNew + edgesUpd })}</Tag>
        </div>
      ),
    })
  }

  if (llm) {
    stages.push({
      key: 'llm', label: t('pipeline.stage_done'), status: 'done',
      details: (
        <div>
          <Tag>{t('pipeline.llm_calls_n', { n: llm.count ?? 0 })}</Tag>
          {llm.total_tokens != null && <Tag variant="muted">{llm.total_tokens.toLocaleString()} tokens</Tag>}
          {llm.duration_ms != null && <Tag variant="muted">{t('pipeline.duration_ms', { n: llm.duration_ms })}</Tag>}
        </div>
      ),
    })
  }

  return (
    <div>
      {stages.map((s, i) => (
        <div key={s.key} style={{
          display: 'flex', gap: 12, padding: '10px 0',
          borderTop: i === 0 ? 'none' : '1px solid var(--border)',
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: s.status === 'done' ? 'var(--engram-tint-primary)' : 'var(--surface2)',
            color: s.status === 'done' ? 'var(--engram-accent-primary)' : 'var(--text3)',
            fontSize: 11, fontWeight: 700,
          }}>{i + 1}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>{s.label}</div>
            <div>{s.details}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function Tag({ children, variant }: { children: React.ReactNode; variant?: 'muted' }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', marginRight: 6, marginTop: 2,
      borderRadius: 10, fontSize: 11,
      background: variant === 'muted' ? 'transparent' : 'var(--engram-tint-primary)',
      color: variant === 'muted' ? 'var(--text3)' : 'var(--engram-accent-primary)',
      border: variant === 'muted' ? '1px solid var(--border2)' : 'none',
    }}>{children}</span>
  )
}

import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchPipelineEntries, fetchSandboxDimensions, runSandboxExtract,
} from '@/api'
import type {
  SandboxDimension, SandboxRunResult, SandboxResultRow, SandboxSubDimValue,
  SandboxHealthAggregate,
} from '@/api'
import { fmtTime } from '@/lib/utils'
import { useI18n, type TKey } from '@/i18n'
import { Play, RotateCcw } from 'lucide-react'

export function SandboxTab() {
  const { t } = useI18n()
  const [dimKey, setDimKey] = useState<string>('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [promptText, setPromptText] = useState<string>('')
  const [rubricText, setRubricText] = useState<string>('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SandboxRunResult | null>(null)
  const [err, setErr] = useState<string>('')

  const { data: dims = [] } = useQuery({
    queryKey: ['sandbox-dimensions'],
    queryFn:  fetchSandboxDimensions,
  })
  const { data: entries = [] } = useQuery({
    queryKey: ['pipeline-entries'],
    queryFn:  () => fetchPipelineEntries(50),
  })

  // Pre-select first dim when loaded; load its prompt+rubric
  useEffect(() => {
    if (!dimKey && dims.length) {
      const first = dims[0]
      setDimKey(first.key)
      setPromptText(first.current_prompt)
      setRubricText(first.current_rubric)
    }
  }, [dims, dimKey])

  const currentDim: SandboxDimension | undefined = useMemo(
    () => dims.find(d => d.key === dimKey),
    [dims, dimKey],
  )

  function selectDim(key: string) {
    setDimKey(key)
    const d = dims.find(x => x.key === key)
    if (d) {
      setPromptText(d.current_prompt)
      setRubricText(d.current_rubric)
      setResult(null)
    }
  }

  function resetPromptToCurrent() {
    if (!currentDim) return
    setPromptText(currentDim.current_prompt)
    setRubricText(currentDim.current_rubric)
  }

  function toggleEntry(id: number) {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id); else next.add(id)
    setSelectedIds(next)
  }

  async function run() {
    if (!dimKey || selectedIds.size === 0) return
    setRunning(true); setErr(''); setResult(null)
    try {
      const r = await runSandboxExtract(dimKey, [...selectedIds], promptText, rubricText)
      setResult(r)
    } catch (e) {
      setErr(String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Left: entry picker */}
      <div style={{
        width: 280, flexShrink: 0, borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        background: 'var(--surface)',
      }}>
        <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{t('sandbox.title')}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4, lineHeight: 1.5 }}>
            {t('sandbox.subtitle')}
          </div>
        </div>
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
            {t('sandbox.pick_entries')}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text2)' }}>
            {t('sandbox.selected_n', { n: selectedIds.size })}
          </div>
        </div>
        <div style={{ overflow: 'auto', flex: 1 }}>
          {entries.map(e => {
            const sel = selectedIds.has(e.id)
            return (
              <button key={e.id}
                onClick={() => toggleEntry(e.id)}
                style={{
                  width: '100%', textAlign: 'left',
                  padding: '8px 16px', border: 'none', cursor: 'pointer',
                  background: sel ? 'var(--engram-tint-primary)' : 'transparent',
                  color: sel ? 'var(--engram-accent-primary)' : 'var(--text2)',
                  borderLeft: sel ? '2px solid var(--engram-accent-primary)' : '2px solid transparent',
                  fontSize: 12,
                  display: 'flex', alignItems: 'flex-start', gap: 8,
                }}>
                <input type="checkbox" checked={sel} readOnly style={{ marginTop: 2, accentColor: 'var(--engram-accent-primary)' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontWeight: 600 }}>#{e.id}</span>
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(e.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {e.preview || '—'}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: editor + run + results */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        {/* Dimension picker + prompt editor */}
        <div style={{ padding: '16px 18px 0' }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
            <label style={{ fontSize: 12, color: 'var(--text2)' }}>{t('sandbox.dimension_label')}:</label>
            <select value={dimKey} onChange={e => selectDim(e.target.value)}
              style={{ fontSize: 13, padding: '5px 10px', borderRadius: 6, background: 'var(--surface2)', border: '1px solid var(--border2)', color: 'var(--text)' }}>
              {dims.length === 0 && <option>—</option>}
              {dims.map(d => <option key={d.key} value={d.key}>{d.name}</option>)}
            </select>
            <div style={{ flex: 1 }} />
            <button onClick={resetPromptToCurrent} className="btn btn-ghost" style={{ fontSize: 11 }} disabled={!currentDim}>
              <RotateCcw size={11} /> {t('sandbox.reset_to_current')}
            </button>
            <button onClick={run} disabled={!dimKey || selectedIds.size === 0 || running}
              className="btn btn-primary" style={{ fontSize: 12 }}>
              {running ? <>{t('sandbox.running')}</> : <><Play size={11} /> {t('sandbox.run_button', { n: selectedIds.size })}</>}
            </button>
          </div>

          <PromptEditor label={t('sandbox.prompt_label')} value={promptText} onChange={setPromptText} rows={14} />
          <PromptEditor label={t('sandbox.rubric_label')} value={rubricText} onChange={setRubricText} rows={8} />
        </div>

        {/* Error */}
        {err && (
          <div style={{ margin: '12px 18px', padding: '10px 12px', fontSize: 12, color: 'var(--engram-accent-warning)',
                        background: 'var(--engram-tint-warning)', borderRadius: 6 }}>
            {t('sandbox.failed', { error: err })}
          </div>
        )}

        {/* Results */}
        {!result && !err && (
          <div style={{ padding: '16px 18px', fontSize: 12, color: 'var(--text3)', fontStyle: 'italic' }}>
            {t('sandbox.no_results')}
          </div>
        )}

        {result && currentDim && (
          <div style={{ padding: '6px 18px 18px' }}>
            <AggregateCompare baseline={result.baseline_health} candidate={result.candidate_health} />
            <PerEntryDiff result={result} dim={currentDim} />
          </div>
        )}
      </div>
    </div>
  )
}


// ── Reusable editor ──────────────────────────────────────────────────────────

function PromptEditor({ label, value, onChange, rows }: {
  label: string; value: string; onChange: (s: string) => void; rows: number
}) {
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
        {label}
      </div>
      <textarea value={value} onChange={e => onChange(e.target.value)} rows={rows}
        style={{
          width: '100%', resize: 'vertical', minHeight: 80,
          background: 'var(--surface2)', border: '1px solid var(--border2)',
          borderRadius: 6, color: 'var(--text)', fontFamily: 'monospace', fontSize: 11,
          padding: '8px 10px', lineHeight: 1.5, outline: 'none',
        }}/>
    </div>
  )
}


// ── Aggregate compare table ──────────────────────────────────────────────────

function AggregateCompare({ baseline, candidate }: {
  baseline: SandboxHealthAggregate; candidate: SandboxHealthAggregate
}) {
  const { t } = useI18n()

  const rows: { key: 'null' | 'low_conf' | 'hedge'; labelKey: TKey; b: number; c: number; goodDirection: 'up' | 'down' }[] = [
    { key: 'null',     labelKey: 'sandbox.metric_null',     b: baseline.null_ratio,           c: candidate.null_ratio,           goodDirection: 'up'   },
    { key: 'low_conf', labelKey: 'sandbox.metric_low_conf', b: baseline.low_conf_ratio,       c: candidate.low_conf_ratio,       goodDirection: 'down' },
    { key: 'hedge',    labelKey: 'sandbox.metric_hedge',    b: baseline.midpoint_hedge_ratio, c: candidate.midpoint_hedge_ratio, goodDirection: 'down' },
  ]

  const cell: React.CSSProperties = { padding: '6px 8px', fontSize: 12 }
  const num: React.CSSProperties  = { ...cell, fontFamily: 'monospace', textAlign: 'right' }

  return (
    <div style={{ marginTop: 10, marginBottom: 16, padding: '12px 14px',
                  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
        {t('sandbox.aggregate_compare')}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ ...cell, textAlign: 'left', fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('sandbox.th_metric')}</th>
            <th style={{ ...num, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('sandbox.th_baseline')}</th>
            <th style={{ ...num, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('sandbox.th_candidate')}</th>
            <th style={{ ...num, fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{t('sandbox.th_delta')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const delta = r.c - r.b
            const isGood = r.goodDirection === 'up' ? delta > 0 : delta < 0
            const color = Math.abs(delta) < 0.005 ? 'var(--text3)' : isGood ? 'var(--engram-accent-success)' : 'var(--engram-accent-warning)'
            const sign = delta > 0 ? '+' : ''
            return (
              <tr key={r.key} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ ...cell, fontWeight: 600, color: 'var(--text2)' }}>{t(r.labelKey)}</td>
                <td style={num}>{(r.b * 100).toFixed(1)}%</td>
                <td style={num}>{(r.c * 100).toFixed(1)}%</td>
                <td style={{ ...num, color, fontWeight: 600 }}>{sign}{(delta * 100).toFixed(1)}pp</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


// ── Per-entry diff ───────────────────────────────────────────────────────────

function PerEntryDiff({ result, dim }: { result: SandboxRunResult; dim: SandboxDimension }) {
  const { t } = useI18n()
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
        {t('sandbox.per_entry_results')}
      </div>
      {result.results.map(r => (
        <EntryRow key={r.entry_id} row={r} dim={dim} />
      ))}
    </div>
  )
}

function EntryRow({ row, dim }: { row: SandboxResultRow; dim: SandboxDimension }) {
  const { t } = useI18n()
  return (
    <div style={{
      marginBottom: 14, padding: '12px 14px',
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>#{row.entry_id}</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 10, lineHeight: 1.5,
                    background: 'var(--surface2)', padding: '6px 8px', borderRadius: 4 }}>
        {row.raw}
      </div>
      {row.error && (
        <div style={{ fontSize: 11, color: 'var(--engram-accent-warning)' }}>
          {t('sandbox.error_prefix')}: {row.error}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <SubDimColumn label={t('sandbox.baseline_label')} content={row.baseline} dim={dim} fallback={t('sandbox.no_baseline')} />
        <SubDimColumn label={t('sandbox.candidate_label')} content={row.candidate} dim={dim} fallback={null} />
      </div>
    </div>
  )
}

function SubDimColumn({ label, content, dim, fallback }: {
  label: string; content: Record<string, SandboxSubDimValue> | null; dim: SandboxDimension; fallback: string | null
}) {
  const { t } = useI18n()
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
        {label}
      </div>
      {content === null && fallback && (
        <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic' }}>{fallback}</div>
      )}
      {content !== null && (
        <div style={{ fontFamily: 'monospace', fontSize: 11 }}>
          {dim.sub_dimensions.map(sd => {
            const v = content[sd.key] ?? null
            return (
              <div key={sd.key} style={{ display: 'flex', gap: 10, marginBottom: 2 }}>
                <span style={{ width: 60, color: 'var(--text2)' }}>{sd.key}:</span>
                {v === null
                  ? <span style={{ color: 'var(--text3)' }}>{t('sandbox.null_value')}</span>
                  : <span style={{ color: 'var(--text)' }}>
                      {v.score.toFixed(0)} <span style={{ color: 'var(--text3)' }}>(c={v.confidence.toFixed(2)})</span>
                      {v.evidence && <span style={{ color: 'var(--text3)' }}> · {v.evidence}</span>}
                    </span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

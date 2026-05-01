import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchEntries, fetchEntry, fetchEntryTrace, fetchMemos, processEntry, deleteEntry, revertEntry } from '@/api'
import type { EntryDetail, TraceData, SliceFeature, Memo, SituationContext } from '@/types'
import { DOMAIN_COLORS, SCHWARTZ_COLORS } from '@/lib/constants'
import { useDimensionSchemas, getDimSchema } from '@/lib/useDimensionSchemas'
import type { DimensionSchema } from '@/types'
import { fmtTime } from '@/lib/utils'
import { RefreshCw, Cpu, Search, Trash2, ChevronRight, RotateCcw } from 'lucide-react'
import { useConfirm } from '@/components/ui/ConfirmDialog'

type ListTab = 'entries' | 'memos'

export function EntriesTab() {
  const qc = useQueryClient()
  const [listTab, setListTab]          = useState<ListTab>('entries')
  const [selectedId, setSelectedId]    = useState<number | null>(null)
  const [selectedMemoId, setSelectedMemoId] = useState<number | null>(null)
  const [traceId, setTraceId]          = useState<number | null>(null)
  const [captureText, setCaptureText]  = useState('')
  const [capturing, setCapturing]      = useState(false)
  const [processingIds, setProcessingIds] = useState<Set<number>>(new Set())
  const [processResult, setProcessResult] = useState<Record<number, string>>({})
  const [revertingIds, setRevertingIds] = useState<Set<number>>(new Set())
  const confirm     = useConfirm()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['entries'], queryFn: () => fetchEntries(200),
  })
  const { data: memosData, isLoading: memosLoading } = useQuery({
    queryKey: ['memos'], queryFn: () => fetchMemos(200),
  })
  const memos = memosData?.memos ?? []

  const { data: detail } = useQuery({
    queryKey: ['entry', selectedId], queryFn: () => fetchEntry(selectedId!), enabled: selectedId !== null,
  })
  const { data: traceData } = useQuery({
    queryKey: ['trace', traceId], queryFn: () => fetchEntryTrace(traceId!), enabled: traceId !== null,
  })

  const selectedMemo = memos.find(m => m.id === selectedMemoId) ?? memos[0] ?? null

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'Enter' && document.activeElement === textareaRef.current) handleCapture()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  useEffect(() => {
    if (!selectedId && entries.length > 0) setSelectedId(entries[0].id)
  }, [entries])

  async function handleCapture() {
    const text = captureText.trim(); if (!text || capturing) return
    setCapturing(true)
    try {
      const res = await fetch('/capture', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text, source: 'web' }) })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setCaptureText('')
      if (data.track === 'memo') {
        await qc.invalidateQueries({ queryKey: ['memos'] })
        setListTab('memos')
      } else {
        await qc.invalidateQueries({ queryKey: ['entries'] })
        await qc.invalidateQueries({ queryKey: ['stats'] })
      }
    } catch (err) { alert('写入失败: ' + String(err)) }
    finally { setCapturing(false) }
  }

  async function handleProcess(id: number, e: React.MouseEvent) {
    e.stopPropagation()
    setProcessingIds(prev => new Set(prev).add(id))
    try {
      const r = await processEntry(id)
      setProcessResult(prev => ({ ...prev, [id]: `${r.nodes_upserted}节点 ${r.edges_upserted}边` }))
      await Promise.all([qc.invalidateQueries({ queryKey: ['entries'] }), qc.invalidateQueries({ queryKey: ['stats'] }), qc.invalidateQueries({ queryKey: ['graph'] })])
    } catch { setProcessResult(prev => ({ ...prev, [id]: '失败' })) }
    finally { setProcessingIds(prev => { const s = new Set(prev); s.delete(id); return s }) }
  }

  async function handleDelete(id: number, e: React.MouseEvent) {
    e.stopPropagation()
    const ok = await confirm({ title: `删除 Entry #${id}`, message: '将同时删除关联的切片和激活记录，无法恢复。', confirmLabel: '删除', danger: true })
    if (!ok) return
    await deleteEntry(id)
    if (selectedId === id) setSelectedId(null)
    await qc.invalidateQueries({ queryKey: ['entries'] })
    await qc.invalidateQueries({ queryKey: ['stats'] })
  }

  async function handleRevert(id: number, newerCount: number, e: React.MouseEvent) {
    e.stopPropagation()
    const cascadeNote = newerCount > 0 ? `\n\n将同时级联撤销之后的 ${newerCount} 条记忆。` : ''
    const ok = await confirm({
      title: `撤销 Entry #${id}`,
      message: `将回滚该条记忆对图谱和画像的影响，entry 状态变为 reverted。${cascadeNote}`,
      confirmLabel: '撤销',
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
    } catch (err) { alert('撤销失败: ' + String(err)) }
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
            placeholder="写点什么… (Ctrl+Enter 提交)"
            className="input"
            style={{ resize: 'none', marginBottom: 8, lineHeight: 1.6, fontSize: 12 }}
          />
          <button onClick={handleCapture} disabled={capturing || !captureText.trim()} className="btn btn-primary" style={{ width: '100%', fontSize: 12 }}>
            {capturing ? '存储中…' : '存储'}
          </button>
        </div>

        {/* Header with tab switcher */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['entries', 'memos'] as ListTab[]).map(t => (
              <button key={t} onClick={() => setListTab(t)}
                style={{
                  padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 500,
                  background: listTab === t ? 'var(--accent)' : 'transparent',
                  color: listTab === t ? '#fff' : 'var(--text3)',
                }}>
                {t === 'entries' ? '记忆' : '备忘'}
              </button>
            ))}
          </div>
          <button onClick={() => qc.invalidateQueries({ queryKey: [listTab === 'entries' ? 'entries' : 'memos'] })}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', display: 'flex', padding: 4, borderRadius: 6 }}>
            <RefreshCw size={13} />
          </button>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {listTab === 'entries' && (
            <>
              {isLoading && <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>加载中…</div>}
              {entries.map(e => {
                const isSelected = selectedId === e.id
                const processing = processingIds.has(e.id)
                const result = processResult[e.id]
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
                      {e.domains.map(d => (
                        <span key={d} className="chip" style={{ background: DOMAIN_COLORS[d] + '22', color: DOMAIN_COLORS[d] }}>{d}</span>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }} onClick={ev => ev.stopPropagation()}>
                      {e.processing_status !== 'processed' && e.processing_status !== 'reverted' && (
                        <button onClick={ev => handleProcess(e.id, ev)} disabled={processing}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 4, padding: '3px 9px',
                            borderRadius: 6, border: '1px solid var(--border2)', cursor: 'pointer',
                            background: result?.includes('节点') ? 'rgba(16,185,129,0.1)' : 'var(--surface2)',
                            color: result?.includes('节点') ? '#10b981' : result === '失败' ? '#f87171' : 'var(--text2)',
                            fontSize: 11, opacity: processing ? 0.5 : 1,
                          }}>
                          <Cpu size={11} />
                          {processing ? '处理中…' : result || '处理'}
                        </button>
                      )}
                      {e.processing_status === 'processed' && (
                        <button onClick={ev => { ev.stopPropagation(); setTraceId(e.id) }}
                          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 9px', borderRadius: 6, border: '1px solid rgba(99,102,241,0.3)', cursor: 'pointer', background: 'rgba(99,102,241,0.08)', color: 'var(--accent2)', fontSize: 11 }}>
                          <Search size={11} />Trace
                        </button>
                      )}
                      {e.can_revert && (
                        <button onClick={ev => handleRevert(e.id, e.newer_processed_count, ev)}
                          disabled={revertingIds.has(e.id)}
                          title={e.newer_processed_count > 0 ? `级联撤销（含之后 ${e.newer_processed_count} 条）` : '撤销此条记忆'}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 3, padding: '3px 7px',
                            borderRadius: 6, border: '1px solid rgba(248,113,113,0.4)', cursor: 'pointer',
                            background: 'rgba(248,113,113,0.08)', color: '#f87171', fontSize: 11,
                            opacity: revertingIds.has(e.id) ? 0.5 : 1,
                          }}>
                          <RotateCcw size={11} />
                          {revertingIds.has(e.id) ? '撤销中…' : e.newer_processed_count > 0 ? `撤销+${e.newer_processed_count}` : '撤销'}
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
          )}
          {listTab === 'memos' && (
            <>
              {memosLoading && <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>加载中…</div>}
              {memos.map(m => {
                const isSelected = selectedMemo?.id === m.id
                return (
                  <div key={m.id} onClick={() => setSelectedMemoId(m.id)}
                    style={{
                      padding: '12px 16px', cursor: 'pointer', borderBottom: '1px solid var(--border)',
                      background: isSelected ? 'rgba(99,102,241,0.1)' : 'transparent',
                      borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                      transition: 'background 0.1s',
                    }}>
                    <div className="line-clamp-2" style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.55, marginBottom: 6 }}>
                      {m.raw}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{fmtTime(m.created_at)}</span>
                      <span className="badge" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>备忘</span>
                      {m.keywords.slice(0, 3).map(k => (
                        <span key={k} className="chip" style={{ background: 'rgba(100,116,139,0.15)', color: 'var(--text3)' }}>{k}</span>
                      ))}
                    </div>
                  </div>
                )
              })}
              {!memosLoading && memos.length === 0 && (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>暂无备忘</div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Right detail ── */}
      <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
        {listTab === 'entries' && !selectedId && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text3)', gap: 8 }}>
            <ChevronRight size={28} strokeWidth={1.5} />
            <span style={{ fontSize: 13 }}>选择一条记忆查看详情</span>
          </div>
        )}
        {listTab === 'entries' && selectedId && detail && (
          <EntryDetailPanel detail={detail} onTrace={() => setTraceId(selectedId)} />
        )}
        {listTab === 'memos' && selectedMemo && (
          <MemoDetailPanel memo={selectedMemo} />
        )}
      </div>

      {/* Trace Modal */}
      {traceId !== null && (
        <TraceModal traceId={traceId} traceData={traceData} onClose={() => setTraceId(null)} />
      )}
    </div>
  )
}

function MemoDetailPanel({ memo }: { memo: Memo }) {
  const meta = memo.metadata
  const META_LABELS: Record<string, string> = {
    captured_at: '记录时间', date: '日期', weekday: '星期',
    time_of_day: '时段', channel: '来源', source_type: '类型', timezone: '时区',
  }
  const metaRows = Object.entries(meta).filter(([k]) => k !== 'captured_at' || true)

  return (
    <div style={{ padding: '24px 28px', maxWidth: 720 }}>
      <div style={{ marginBottom: 20 }}>
        <span className="badge" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b', marginBottom: 8, display: 'inline-flex' }}>
          备忘 #{memo.id}
        </span>
        <div style={{ fontSize: 14, color: 'var(--text)', lineHeight: 1.75, marginBottom: 8 }}>{memo.raw}</div>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>{fmtTime(memo.created_at)} · {memo.source}</div>
      </div>

      {memo.keywords.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div className="t-caption" style={{ marginBottom: 8 }}>关键词</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {memo.keywords.map(k => (
              <span key={k} className="chip" style={{ background: 'rgba(100,116,139,0.15)', color: 'var(--text2)' }}>{k}</span>
            ))}
          </div>
        </div>
      )}

      {metaRows.length > 0 && (
        <div>
          <div className="t-caption" style={{ marginBottom: 8 }}>元信息</div>
          <div style={{ borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden' }}>
            {metaRows.map(([k, v], i) => (
              <div key={k} style={{
                display: 'flex', gap: 16, padding: '8px 14px', fontSize: 12,
                background: i % 2 === 0 ? 'var(--surface)' : 'var(--surface2)',
                borderBottom: i < metaRows.length - 1 ? '1px solid var(--border)' : 'none',
              }}>
                <span style={{ color: 'var(--text3)', width: 90, flexShrink: 0 }}>{META_LABELS[k] || k}</span>
                <span style={{ color: 'var(--text)', wordBreak: 'break-all' }}>{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { bg: string; color: string; label: string }> = {
    captured:     { bg: 'rgba(79,90,110,0.35)',  color: '#8892a4', label: '待处理' },
    processed:    { bg: 'rgba(16,185,129,0.15)', color: '#10b981', label: '已处理' },
    slice_failed: { bg: 'rgba(248,113,113,0.15)', color: '#f87171', label: '处理失败' },
    reverted:     { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', label: '已撤销' },
  }
  const s = cfg[status] || cfg.captured
  return <span className="badge" style={{ background: s.bg, color: s.color }}>{s.label}</span>
}

function EntryDetailPanel({ detail, onTrace }: { detail: EntryDetail; onTrace: () => void }) {
  const schemas = useDimensionSchemas()
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
                <Search size={11} /> 查看 Trace
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
          <div className="t-caption" style={{ marginBottom: 12 }}>切片分析</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {detail.features.map((f, i) => <FeatureBlock key={i} f={f} schemas={schemas} />)}
          </div>
        </div>
      )}

      {/* Activations */}
      {detail.activations.length > 0 && (
        <div>
          <div className="t-caption" style={{ marginBottom: 12 }}>激活节点 · {detail.activations.length}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {detail.activations.map((a, i) => {
              const color = DOMAIN_COLORS[a.domain] || '#6366f1'
              return (
                <div key={i} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--surface2)', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: a.user_relevance ? 4 : 0 }}>
                    <span className="chip" style={{ background: color + '22', color }}>{a.domain}</span>
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
        <div style={{ color: 'var(--text3)', fontSize: 12 }}>尚未处理</div>
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

const FRAME_LABEL: Record<string, string> = { present: '当下', retrospective: '回顾', hypothetical: '假设' }
const STANCE_LABEL: Record<string, string> = { present_reflection: '当下反思', recounting_past: '复述过去', mixed: '混合' }
const LEVEL_COLOR: Record<string, string> = { high: '#f87171', medium: '#f59e0b', low: '#34d399' }

function SituationBadges({ sit }: { sit: SituationContext }) {
  const items: { label: string; value: string; color?: string }[] = []
  if (sit.temporal_frame) items.push({ label: '时间视角', value: FRAME_LABEL[sit.temporal_frame] || sit.temporal_frame })
  if (sit.narrator_stance) items.push({ label: '叙述立场', value: STANCE_LABEL[sit.narrator_stance] || sit.narrator_stance })
  if (sit.life_phase_ref) items.push({ label: '人生阶段', value: sit.life_phase_ref })
  if (sit.emotional_state) items.push({ label: '情绪', value: sit.emotional_state })
  if (sit.pressure_level) items.push({ label: '压力', value: sit.pressure_level, color: LEVEL_COLOR[sit.pressure_level] })
  if (sit.energy_level) items.push({ label: '能量', value: sit.energy_level, color: LEVEL_COLOR[sit.energy_level] })
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

const EDGE_COLORS: Record<string, string> = { 支撑: '#818cf8', 对立: '#f87171', 蕴含: '#34d399', 属于: '#f59e0b', 影响: '#3b82f6', 相似: '#94a3b8' }

const FIELD_DOCS: Record<string, { title: string; body: string }> = {
  conf: {
    title: 'Confidence (conf)',
    body: `LLM 对该次提取结果的置信度，范围 0–1，由模型直接输出。

用途：
• profile merge 中作为新信号权重
  alpha = new_conf / (hist_effective + new_conf)
• 低于 0.15 的信号会被直接丢弃，不进入画像
• node 写入时影响 strength 增量：
  increment ∝ effort_weight × confidence

含义：0.9 = 模型非常确定；0.3 = 弱信号；<0.15 = 噪声过滤`,
  },
  strength: {
    title: 'Node Strength',
    body: `节点的累计激活强度，范围理论上无上界，实际常见 0–3。

更新公式（每次 entry 命中该节点）：
  new = old × time_decay + effort_weight × confidence
  time_decay = exp(−λ × days_since_last_hit)，λ = 0.005

含义：
• 高 strength (>1.5)：用户反复提及的认知锚点
• 中 strength (0.5–1.5)：有一定历史积累
• 低 strength (<0.5)：刚建立或很久未被强化

在查询链路中，strength 决定节点被激活和召回的优先级。`,
  },
  weight: {
    title: 'Edge Weight',
    body: `边的累计强化强度，从 0 开始累加，理论上限由配置决定。

LLM 边更新公式（每次被 entry 关联）：
  weight += min_delta + (base_delta − min_delta) × confidence
  min_delta = 0.02，base_delta = 0.15

强度等级（查询时动态标注）：
• weak    < 0.25：1–2 次观测，关系刚建立
• moderate 0.25–0.5：多次强化，有意义的模式
• strong  ≥ 0.5：深度建立，高置信结构性连接

注意：weak 不等于不可信，只代表观测次数少。算法边（相似/关联）有独立上限（0.3 / 0.5）。`,
  },
  sim: {
    title: 'Similarity (sim)',
    body: `语义向量余弦相似度，范围 0–1，由 embedding 模型计算。

用途：
• 粗召回阶段：从向量库检索与当前 entry 最相关的存量节点
• 算法边触发：sim ≥ 0.78 时自动建立"相似"边
• 关联边触发：sim ≥ 0.20 时建立"关联"边（共现兜底）

含义：0.9+ = 几乎相同语义；0.7–0.9 = 强相关；0.5–0.7 = 有关联；<0.5 = 弱相关`,
  },
}

function FieldHint({ field }: { field: keyof typeof FIELD_DOCS }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const doc = FIELD_DOCS[field]

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
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: 32, overflowY: 'auto' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="fade-in" style={{ width: '100%', maxWidth: 860, flexShrink: 0, borderRadius: 14, overflow: 'hidden', background: 'var(--surface)', border: '1px solid var(--border2)' }}>
        <div style={{ position: 'sticky', top: 0, display: 'flex', alignItems: 'center', padding: '16px 20px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', zIndex: 2 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Pipeline Trace — Entry #{traceId}</div>
            {traceData?.updated_at && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>运行于 {fmtTime(traceData.updated_at)}</div>}
          </div>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', fontSize: 18, lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {!traceData && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 8 }}>加载中…</div>}
          {traceData && !traceData.trace && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 8 }}>暂无 Trace 数据，请先执行处理</div>}
          {traceData?.trace && <TraceStages trace={traceData.trace} />}
        </div>
      </div>
    </div>
  )
}

function TraceStages({ trace }: { trace: NonNullable<TraceData['trace']> }) {
  return (
    <>
      <TraceStage num="1" title="Slice 切片" data={trace.slice}><SliceContent slice={trace.slice} /></TraceStage>
      <TraceStage num="2" title="Profile Diff" data={trace.profile_diff}><ProfileDiffContent diff={trace.profile_diff} /></TraceStage>
      <TraceStage num="3" title="Activation 激活" data={trace.activation}><ActivationContent act={trace.activation} /></TraceStage>
      <TraceStage num="4" title="粗召回 Top-K" data={trace.rough_retrieval} collapsed><RoughRetrievalContent nodes={trace.rough_retrieval} /></TraceStage>
      <TraceStage num="5" title="Node Extract 各域提取" data={trace.node_extract}><NodeExtractContent extract={trace.node_extract} /></TraceStage>
      <TraceStage num="6" title="Confirmed Nodes" data={trace.confirmed_nodes}><ConfirmedNodesContent nodes={trace.confirmed_nodes} /></TraceStage>
      <TraceStage num="7" title="精召回 子图" data={trace.subgraph} collapsed><SubgraphContent sg={trace.subgraph} /></TraceStage>
      <TraceStage num="8" title="Edge Extract LLM输出" data={trace.edge_extract}><EdgeExtractContent edges={trace.edge_extract} /></TraceStage>
      <TraceStage num="9" title="DB Diff 实际变更" data={trace.db_diff}><DbDiffContent diff={trace.db_diff} /></TraceStage>
    </>
  )
}

function TraceStage({ num, title, data, collapsed = false, children }: {
  num: string; title: string; data: unknown; collapsed?: boolean; children: React.ReactNode
}) {
  const [open, setOpen] = useState(!collapsed)
  const isEmpty = !data || (Array.isArray(data) && !data.length) || (typeof data === 'object' && !Array.isArray(data) && !Object.keys(data as object).length)
  const count = Array.isArray(data) ? data.length : (data && typeof data === 'object' ? Object.keys(data as object).length : 0)
  const badge = isEmpty ? '空' : count > 0 ? `${count}项` : '有数据'
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

function TEmpty({ text = '空' }: { text?: string }) {
  return <div style={{ color: 'var(--text3)', fontSize: 11 }}>{text}</div>
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
  const c = DOMAIN_COLORS[domain] || '#6366f1'
  return <span className="chip" style={{ background: c + '22', color: c }}>{domain}</span>
}

function SliceContent({ slice }: { slice: NonNullable<TraceData['trace']>['slice'] }) {
  const schemas = useDimensionSchemas()
  if (!slice || !Object.keys(slice).length) return <TEmpty text="无切片数据" />
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
  if (!diff || !Object.keys(diff).length) return <TEmpty text="无变化" />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(diff).map(([dim, keys]) => (
        <div key={dim}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>{dim}</div>
          <TTable headers={['字段', '分数', 'Δ', <span>conf<FieldHint field="conf" /></span>]}
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
  if (!act || !Object.keys(act).length) return <TEmpty text="无激活域" />
  return (
    <TTable headers={['域', 'effort_weight', '']}
      rows={Object.entries(act).sort(([, a], [, b]) => b - a).map(([domain, w]) => {
        const c = DOMAIN_COLORS[domain] || '#6366f1'
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
  if (!nodes?.length) return <TEmpty text="无存量节点" />
  return <TTable headers={['标签', '域', '类型', <span>strength<FieldHint field="strength" /></span>, <span>sim<FieldHint field="sim" /></span>]}
    rows={nodes.map(n => [n.label, <DPill domain={n.domain} />, n.node_type, n.strength.toFixed(3), <span style={{ color: '#10b981' }}>{n.sim.toFixed(3)}</span>])} />
}

function NodeExtractContent({ extract }: { extract: NonNullable<TraceData['trace']>['node_extract'] }) {
  if (!extract || !Object.keys(extract).length) return <TEmpty text="无提取结果" />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(extract).map(([domain, nodes]) => {
        const c = DOMAIN_COLORS[domain] || '#6366f1'
        return (
          <div key={domain}>
            <div style={{ fontSize: 10, fontWeight: 600, color: c, marginBottom: 6 }}>{domain} ({nodes.length}个节点)</div>
            {nodes.length === 0 ? <TEmpty /> : (
              <TTable headers={['标签', '类型', <span>conf<FieldHint field="conf" /></span>, '描述']}
                rows={nodes.map(n => [n.label, n.node_type, n.confidence.toFixed(2), <span style={{ color: 'var(--text3)', display: 'block', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.description || ''}</span>])} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function ConfirmedNodesContent({ nodes }: { nodes: NonNullable<TraceData['trace']>['confirmed_nodes'] }) {
  if (!nodes?.length) return <TEmpty text="无确认节点" />
  return <TTable headers={['标签', '域', '类型', '状态', <span>strength<FieldHint field="strength" /></span>, <span>conf<FieldHint field="conf" /></span>]}
    rows={nodes.map(n => [
      n.label, <DPill domain={n.domain} />, n.node_type,
      <span className="badge" style={n.is_new ? { background: 'rgba(16,185,129,0.15)', color: '#10b981' } : { background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>{n.is_new ? '新建' : '命中'}</span>,
      n.strength.toFixed(3), n.new_conf != null ? n.new_conf.toFixed(3) : '—',
    ])} />
}

function SubgraphContent({ sg }: { sg: NonNullable<TraceData['trace']>['subgraph'] }) {
  if (!sg) return <TEmpty text="无子图" />
  const nodes = sg.nodes || [], edges = sg.edges || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ color: 'var(--text3)', fontSize: 11 }}>{nodes.length} 节点 · {edges.length} 边</div>
      {nodes.length > 0 && <TTable headers={['标签', '域', <span>strength<FieldHint field="strength" /></span>]} rows={nodes.map(n => [n.label, <DPill domain={n.domain} />, n.strength.toFixed(3)])} />}
      {edges.length > 0 && <TTable headers={['from', '关系', 'to', <span>weight<FieldHint field="weight" /></span>]}
        rows={edges.map(e => [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label, (e.weight ?? 0).toFixed(3)])} />}
    </div>
  )
}

function EdgeExtractContent({ edges }: { edges: NonNullable<TraceData['trace']>['edge_extract'] }) {
  if (!edges?.length) return <TEmpty text="无边提取结果" />
  return <TTable headers={['from', '关系', 'to', '方向', <span>conf<FieldHint field="conf" /></span>, '证据']}
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
  if (!diff) return <TEmpty text="无 diff 数据" />
  const { nodes_new: nn = [], nodes_updated: nu = [], edges_new: en = [], edges_updated: eu = [] } = diff
  if (!nn.length && !nu.length && !en.length && !eu.length) return <TEmpty text="无 DB 变更" />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {nn.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981' }}>新建节点 ({nn.length})</div>
        <TTable headers={['id', '标签', '域', '类型', <span>strength<FieldHint field="strength" /></span>]}
          rows={nn.map(n => [`#${n.id}`, n.label, <DPill domain={n.domain} />, n.node_type, n.strength.toFixed(3)])} />
      </>}
      {nu.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#818cf8' }}>更新节点 ({nu.length})</div>
        <TTable headers={['标签', '域', <span>before<FieldHint field="strength" /></span>, 'after', 'Δ']}
          rows={nu.map(n => {
            const d = n.strength_after - n.strength_before
            return [n.label, <DPill domain={n.domain} />, n.strength_before.toFixed(3), n.strength_after.toFixed(3), <span style={{ color: d > 0 ? '#10b981' : '#f87171', fontWeight: 700 }}>{d > 0 ? '+' : ''}{d.toFixed(3)}</span>]
          })} />
      </>}
      {en.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#10b981' }}>新建边 ({en.length})</div>
        <TTable headers={['from', '关系', 'to', <span>weight<FieldHint field="weight" /></span>]}
          rows={en.map(e => [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label, (e.weight ?? 0).toFixed(3)])} />
      </>}
      {eu.length > 0 && <>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#818cf8' }}>更新边 ({eu.length})</div>
        <TTable headers={['from', '关系', 'to', <span>weight delta<FieldHint field="weight" /></span>]}
          rows={eu.map(e => {
            const dw = (e.weight_after ?? 0) - (e.weight_before ?? 0)
            return [e.from_label, <span style={{ color: EDGE_COLORS[e.relation_type] || '#64748b' }}>{e.relation_type}</span>, e.to_label,
              <span>{(e.weight_before ?? 0).toFixed(3)} → <b>{(e.weight_after ?? 0).toFixed(3)}</b> <span style={{ color: dw >= 0 ? '#10b981' : '#f87171', fontWeight: 700 }}>{dw >= 0 ? '+' : ''}{dw.toFixed(3)}</span></span>]
          })} />
      </>}
    </div>
  )
}

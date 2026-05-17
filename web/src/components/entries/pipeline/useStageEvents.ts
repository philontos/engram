import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import type { StageEvent, StageRowModel, TraceResponse, TraceJson } from './types'
import { stageGroup } from './stageLabels'

/**
 * Pipeline 透明化的核心数据 hook。
 *
 * - mode='live':   消费来自父组件透传的 SSE event 数组（实时流入）
 * - mode='replay': 初次挂载时拉 GET /ui/api/entry/{id}/trace，把 trace_json 转成等价 event 列表
 *
 * 对外返回统一的 StageRowModel[]，按出现顺序排序；并提供 loadTrace() 让 drawer 按需拉详情。
 */
export function useStageEvents(opts: {
  entryId: number
  mode: 'live' | 'replay'
  liveEvents?: StageEvent[]
}): {
  rows: StageRowModel[]
  trace: TraceJson | null
  traceLoading: boolean
  traceError: string | null
  loadTrace: () => Promise<void>
} {
  const { entryId, mode, liveEvents } = opts
  const [trace, setTrace] = useState<TraceJson | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [traceError, setTraceError] = useState<string | null>(null)
  const loadedRef = useRef(false)

  const loadTrace = useCallback(async () => {
    if (loadedRef.current || traceLoading) return
    loadedRef.current = true
    setTraceLoading(true)
    setTraceError(null)
    try {
      const res = await fetch(`/ui/api/entry/${entryId}/trace`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as TraceResponse
      setTrace(body.trace)
    } catch (err) {
      setTraceError(String((err as Error).message ?? err))
      loadedRef.current = false
    } finally {
      setTraceLoading(false)
    }
  }, [entryId, traceLoading])

  useEffect(() => {
    if (mode === 'replay') void loadTrace()
  }, [mode, loadTrace])

  const rows = useMemo<StageRowModel[]>(() => {
    if (mode === 'live') {
      return composeFromEvents(liveEvents ?? [])
    }
    return composeFromTrace(trace)
  }, [mode, liveEvents, trace])

  return { rows, trace, traceLoading, traceError, loadTrace }
}

function composeFromEvents(events: StageEvent[]): StageRowModel[] {
  const byStage = new Map<string, { start?: StageEvent; end?: StageEvent }>()
  const order: string[] = []
  for (const ev of events) {
    if (ev.type !== 'stage' || !ev.stage) continue
    if (!byStage.has(ev.stage)) {
      byStage.set(ev.stage, {})
      order.push(ev.stage)
    }
    const slot = byStage.get(ev.stage)!
    if (ev.status === 'start') slot.start = ev
    else slot.end = ev
  }
  return order.map(stage => {
    const { start, end } = byStage.get(stage)!
    const status: StageRowModel['status'] = (end?.status as StageRowModel['status']) ?? (start ? 'running' : 'pending')
    const durationMs = start && end ? Math.max(0, end.elapsed_ms - start.elapsed_ms) : 0
    return {
      key: stage,
      group: stageGroup(stage),
      status,
      durationMs,
      summary: end?.summary,
      payload: end?.payload,
      error: end?.error,
      reason: end?.reason,
      truncated: end?.payload?.truncated === true,
    }
  })
}

/**
 * 把 trace_json 转成同样的 row model。Replay 用，也作 stream-lost 兜底。
 * 旧 entry（在 per-sub-stage 重构前 captured）的 trace 没有细 stage 名，
 * 只能展示 trace.llm_calls 里有的 stage（同名 LLM 调用）。
 */
function composeFromTrace(trace: TraceJson | null): StageRowModel[] {
  if (!trace) return []
  const rows: StageRowModel[] = []
  const seen = new Set<string>()

  const calls = trace.llm_calls ?? []
  for (const c of calls) {
    if (!c.stage || seen.has(c.stage)) continue
    seen.add(c.stage)
    const status: StageRowModel['status'] =
      c.status === 'ok' ? 'done' :
      c.status === 'skipped' ? 'skipped' :
      'error'
    rows.push({
      key: c.stage,
      group: stageGroup(c.stage),
      status,
      durationMs: c.duration_ms ?? 0,
      summary: undefined,
      payload: c.response ? safeParse(c.response) : undefined,
      error: c.error ? { message: c.error } : undefined,
    })
  }

  if (trace.rough_retrieval && !seen.has('rough_retrieval')) {
    rows.push({
      key: 'rough_retrieval',
      group: 'backbone',
      status: 'done',
      durationMs: 0,
      summary: `top-${trace.rough_retrieval.length} candidates`,
      payload: { candidates: trace.rough_retrieval.slice(0, 15) },
    })
  }
  if (trace.algo_edges && !seen.has('algo_edges')) {
    rows.push({
      key: 'algo_edges',
      group: 'backbone',
      status: 'done',
      durationMs: 0,
      summary: `${trace.algo_edges.length} similarity edges`,
      payload: { edges: trace.algo_edges.slice(0, 20) },
    })
  }
  if (trace.association_edges && !seen.has('association')) {
    rows.push({
      key: 'association',
      group: 'backbone',
      status: 'done',
      durationMs: 0,
      summary: `${trace.association_edges.length} associative edges`,
      payload: { edges: trace.association_edges.slice(0, 20) },
    })
  }
  if (trace.opposition_propagation && !seen.has('opposition_propagation')) {
    rows.push({
      key: 'opposition_propagation',
      group: 'backbone',
      status: 'done',
      durationMs: 0,
      summary: `${trace.opposition_propagation.length} propagated`,
      payload: { edges: trace.opposition_propagation.slice(0, 20) },
    })
  }

  return rows
}

function safeParse(s: string): Record<string, any> | undefined {
  try { return JSON.parse(s) } catch { return undefined }
}

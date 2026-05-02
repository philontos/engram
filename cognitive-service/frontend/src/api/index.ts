import type {
  Entry, EntryDetail, GraphData, ProfileDimension, DimensionSchema,
  QueryLogSummary, QueryLogDetail, Stats, TraceData,
} from '@/types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${text}`)
  }
  return res.json()
}

// ── Stats ─────────────────────────────────────────────────────────────────────
export const fetchStats = () => req<Stats>('/ui/api/stats')

// ── Entries ───────────────────────────────────────────────────────────────────
export const fetchEntries = (limit = 200) =>
  req<Entry[]>(`/ui/api/entries?limit=${limit}`)

export const fetchEntry = (id: number) =>
  req<EntryDetail>(`/ui/api/entry/${id}`)

export const fetchEntryTrace = (id: number) =>
  req<TraceData>(`/ui/api/entry/${id}/trace`)

async function _downloadJson(url: string, fallbackName: string) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${await res.text().catch(() => res.statusText)}`)
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename=([^;]+)/i.exec(cd)
  const filename = (m?.[1] || fallbackName).replace(/^"|"$/g, '').trim()
  const a = document.createElement('a')
  const objUrl = URL.createObjectURL(blob)
  a.href = objUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objUrl)
}

export const exportEntryTrace = (id: number) =>
  _downloadJson(`/ui/api/entry/${id}/trace/export`, `entry_${id}_trace.json`)

export const exportAllTraces = () =>
  _downloadJson('/ui/api/traces/export', 'process_traces.json')

export const deleteEntry = (id: number) =>
  req<{ deleted: number }>(`/ui/api/entry/${id}`, { method: 'DELETE' })

export const revertEntry = (id: number) =>
  req<{ cascade_count: number; cascade_ids: number[]; reverted: unknown }>(
    `/ui/api/entry/${id}/revert`, { method: 'POST' }
  )

export const processEntry = (id: number, force = false) =>
  req<{ nodes_upserted: number; edges_upserted: number }>(
    `/entries/${id}/process${force ? '?force=true' : ''}`,
    { method: 'POST' }
  )

// ── Graph ─────────────────────────────────────────────────────────────────────
export const fetchGraph = (domain = '') =>
  req<GraphData>(`/ui/api/graph${domain ? `?domain=${domain}` : ''}`)

export const fetchGraphSeed = (domain = '', limit = 24) =>
  req<GraphData>(`/ui/api/graph/seed?limit=${limit}${domain ? `&domain=${domain}` : ''}`)

export const fetchGraphExpand = (nodeId: number, loadedIds: number[]) =>
  req<GraphData>(`/ui/api/graph/expand?node_id=${nodeId}&loaded=${loadedIds.join(',')}`)

// ── Profile ───────────────────────────────────────────────────────────────────
export const fetchProfile = () => req<ProfileDimension[]>('/ui/api/profile')
export const fetchDimensions = () => req<DimensionSchema[]>('/ui/api/dimensions')

// ── Backbones ─────────────────────────────────────────────────────────────────
export type BackboneSchema = {
  key: string
  name: string
  color: string
  description?: string
  focus_hints?: string[]
  enabled?: boolean
}
export const fetchBackbones = () =>
  req<{ backbones: BackboneSchema[]; orphan_domains: string[] }>('/ui/api/backbones')

export type EvolutionPoint = { entry_id: number; date: string; score: number; confidence: number }
export type ProfileEvolution = { ocean: Record<string, EvolutionPoint[]>; schwartz: Record<string, EvolutionPoint[]> }
export const fetchProfileEvolution = () => req<ProfileEvolution>('/ui/api/profile/evolution')

// ── Query Logs ────────────────────────────────────────────────────────────────
export const fetchQueryLogs = (limit = 50) =>
  req<{ logs: QueryLogSummary[]; total: number }>(`/ui/api/query-logs?limit=${limit}`)

export const fetchQueryLog = (id: number) =>
  req<QueryLogDetail>(`/ui/api/query-logs/${id}`)

export const deleteQueryLog = (id: number) =>
  req<{ deleted: boolean }>(`/ui/api/query-logs/${id}`, { method: 'DELETE' })

export const clearQueryLogs = () =>
  req<{ deleted: boolean }>('/ui/api/query-logs', { method: 'DELETE' })

// ── Admin ─────────────────────────────────────────────────────────────────────
export const exportEntries = () => fetch('/ui/api/export')

export const resetData = (scope: 'derived' | 'all') =>
  req<unknown>('/ui/api/admin/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope, confirm: 'yes' }),
  })

export const processPending = () =>
  req<{ processed: number; results: unknown[] }>('/ui/api/admin/process-pending', { method: 'POST' })

export const importEntries = (entries: unknown[]) =>
  req<unknown>('/import/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries }),
  })

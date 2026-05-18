/**
 * Pipeline 透明化前端类型定义。
 *
 * 后端 SSE event schema 见 docs/superpowers/specs/2026-05-17-pipeline-transparency-design.md §4.2
 */

export type StageStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped'

/** 单条 stage event（来自 SSE 或 replay /trace 转换的产物）*/
export interface StageEvent {
  type: 'stage'
  stage: string
  status: StageStatus
  elapsed_ms: number
  summary?: string
  payload?: Record<string, any>
  error?: { type?: string; message?: string }
  reason?: string
  truncated?: boolean

  // legacy / pipeline-level fields:
  raw_chars?: number
  duration_ms?: number
  final_status?: string
  metrics?: Record<string, any>
  message?: string
}

/** 折叠到 UI 行模型，由 useStageEvents hook 产出 */
export interface StageRowModel {
  key: string
  group: 'slice' | 'activation' | 'backbone' | 'pipeline'
  status: StageStatus
  durationMs: number
  summary?: string
  payload?: Record<string, any>
  error?: { type?: string; message?: string }
  reason?: string
  truncated?: boolean
}

/** 完整 trace JSON 形状（来自 GET /ui/api/entry/{id}/trace） */
export interface TraceJson {
  entry_id: number
  started_at: string
  finished_at?: string
  duration_ms?: number
  slice_extraction_health?: Record<string, any>
  slice?: Record<string, any>
  profile_diff?: Record<string, any>
  activation?: Record<string, number>
  rough_retrieval?: Array<Record<string, any>>
  node_extract_internal?: Record<string, Array<Record<string, any>>>
  node_extract_external?: Record<string, Array<Record<string, any>>>
  confirmed_nodes?: Array<Record<string, any>>
  subgraph?: { nodes: any[]; edges: any[] }
  algo_edges?: any[]
  edge_extract?: any[]
  association_edges?: any[]
  opposition_propagation?: any[]
  llm_calls?: Array<{
    stage: string
    model: string
    system_prompt?: string
    user_prompt?: string
    response?: string
    duration_ms?: number
    status?: string
    error?: string
  }>
  llm_summary?: Record<string, any>
  metrics?: Record<string, any>
}

/** /ui/api/entry/{id}/trace 接口返回体 */
export interface TraceResponse {
  entry_id: number
  updated_at: string
  trace: TraceJson
}

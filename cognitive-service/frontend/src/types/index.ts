// ── Dimension Schemas ─────────────────────────────────────────────────────────

export interface SubDimensionDef {
  key: string
  name: string
}

export interface DimensionSchema {
  key: string
  name: string
  summary_format: 'scores' | 'key_value' | 'skip' | 'free'
  summary_label: string
  sort_by_score?: boolean
  score_range?: [number, number]
  sub_dimensions?: SubDimensionDef[]
  enabled: boolean
}

// ── Entries ──────────────────────────────────────────────────────────────────

export interface Entry {
  id: number
  preview: string
  processing_status: 'captured' | 'processed' | 'slice_failed' | 'reverted'
  created_at: string
  slice_id: number | null
  domains: string[]
  can_revert: boolean
  newer_processed_count: number
}

export interface SliceFeature {
  dimension: string
  content_json: Record<string, unknown>
  confidence: number
}

export interface SituationContext {
  temporal_frame?: string
  narrator_stance?: string
  life_phase_ref?: string
  emotional_state?: string
  pressure_level?: string
  energy_level?: string
}

export interface EntryDetail {
  entry: {
    id: number
    raw: string
    created_at: string
    processing_status: string
    memory_type: string | null
    situation: SituationContext | null
  }
  features: SliceFeature[]
  activations: Activation[]
}

// ── Graph ─────────────────────────────────────────────────────────────────────

export interface GraphNode {
  data: {
    id: string
    db_id: number
    label: string
    node_type: string
    domain: string
    origin: 'internal' | 'external'
    weight: number
    activation_count: number
    source_entries: number[]
    user_relevance: string
    factual_summary: string
    last_activated: string
    neighbor_count?: number
    unexpanded_count?: number
  }
}

export interface GraphEdge {
  data: {
    id: string
    source: string
    target: string
    relation: string
    weight: number
    confidence: number
    source_entries: number[]
  }
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ── Profile ───────────────────────────────────────────────────────────────────

export interface SubDimValue {
  score: number
  confidence: number
  /** 累积观测精度（贝叶斯递推融合）。前端不直接使用，confidence 已由 τ 派生。 */
  tau?: number
  evidence?: string
}

export interface SubSource {
  entry_id: number
  score: number
  confidence: number
  evidence: string
  created_at: string
}

export interface ProfileDimension {
  dimension: string
  content: Record<string, SubDimValue | null>
  sample_count: number
  updated_at: string
  sub_sources: Record<string, SubSource[]>
}

// ── Activations ───────────────────────────────────────────────────────────────

export interface Activation {
  node_id?: number
  label: string
  domain: string
  node_type: string
  profile_match_score: number
  user_relevance: string
  created_at: string
}

// ── Query Logs ────────────────────────────────────────────────────────────────

export interface ToolCallTrace {
  round: number
  tool: string
  args: Record<string, unknown>
  summary?: string
  node_count?: number
  preview?: string
}

export interface ThemeRecall {
  node_label: string
  node_domain: string
  strength: number
  entries: { id: number; date: string; raw: string }[]
}

export interface QueryTurn {
  question: string
  intent: 'proceed' | 'off_topic' | 'clarify'
  mode?: 'factual' | 'reflective' | 'exploratory'
  response: string
  q1_text?: string
  q2_text?: string
  history_context?: string
  tool_calls?: ToolCallTrace[]
  theme_recall?: ThemeRecall[]
  created_at: string
}

export interface QueryLogSummary {
  id: number
  session_id: string | null
  question: string
  mode: string
  seeds: { label: string; domain: string }[]
  turn_count: number
  updated_at: string
  created_at: string
}

export interface QueryLogDetail extends QueryLogSummary {
  q1_text: string
  q2_text: string
  q3_text: string
  q4_text: string
  turns_json: QueryTurn[]
}

// ── Stats ─────────────────────────────────────────────────────────────────────

export interface Stats {
  entries: number
  entries_done: number
  slices: number
  nodes: number
  edges: number
  activations: number
}

// ── Trace ─────────────────────────────────────────────────────────────────────

export interface TraceData {
  entry_id: number
  updated_at?: string
  trace: {
    slice?: Record<string, { content: Record<string, unknown>; confidence: number }>
    profile_diff?: Record<string, Record<string, unknown>>
    activation?: Record<string, number>
    rough_retrieval?: Array<{ label: string; domain: string; node_type: string; strength: number; sim: number }>
    node_extract?: Record<string, Array<{ label: string; node_type: string; confidence: number; description?: string }>>
    confirmed_nodes?: Array<{ label: string; domain: string; node_type: string; is_new: boolean; strength: number; new_conf?: number }>
    subgraph?: {
      nodes: Array<{ label: string; domain: string; strength: number }>
      edges: Array<{ from_label: string; to_label: string; relation_type: string; weight: number }>
    }
    edge_extract?: Array<{ from_label: string; to_label: string; relation_type: string; direction: string; confidence: number; evidence?: string }>
    db_diff?: {
      nodes_new: Array<{ id: number; label: string; domain: string; node_type: string; strength: number }>
      nodes_updated: Array<{ label: string; domain: string; strength_before: number; strength_after: number }>
      edges_new: Array<{ from_label: string; to_label: string; relation_type: string; weight: number }>
      edges_updated: Array<{ from_label: string; to_label: string; relation_type: string; weight_before: number; weight_after: number }>
    }
  } | null
}

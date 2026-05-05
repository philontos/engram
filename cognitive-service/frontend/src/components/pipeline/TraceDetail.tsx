/**
 * Trace 下钻视图：左侧 stage 大纲 + 右侧选中 stage 的完整数据。
 *
 * 设计目标是 debug + recall —— 不做漂亮卡片，直接 raw + 折叠 JSON viewer。
 * 每个 LLM 调用阶段都能完整展示 system_prompt + response，方便定位"当时
 * LLM 看到了什么 / 输出了什么"。
 */

import { useMemo, useState } from 'react'
import type { TraceData, LLMCallRecord } from '@/types'
import { useI18n } from '@/i18n'

type Trace = NonNullable<TraceData['trace']>

interface OutlineNode {
  id:        string
  label:     string
  depth:     number
  badge?:    string  // small annotation, e.g. token count or status
  hasError?: boolean
}

export function TraceDetail({ trace, raw }: { trace: Trace; raw: string }) {
  const [selected, setSelected] = useState<string>('raw')

  const llmCallsByStage = useMemo(() => {
    const out: Record<string, LLMCallRecord[]> = {}
    for (const c of trace.llm_calls || []) {
      if (!out[c.stage]) out[c.stage] = []
      out[c.stage].push(c)
    }
    return out
  }, [trace.llm_calls])

  const outline = useMemo(() => buildOutline(trace, llmCallsByStage), [trace, llmCallsByStage])

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 480, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <Outline nodes={outline} selected={selected} onSelect={setSelected} />
      <Detail trace={trace} raw={raw} stage={selected} llmCallsByStage={llmCallsByStage} />
    </div>
  )
}


// ── Outline (left pane) ──────────────────────────────────────────────────────

function Outline({ nodes, selected, onSelect }: {
  nodes: OutlineNode[]; selected: string; onSelect: (id: string) => void
}) {
  return (
    <div style={{
      width: 260, flexShrink: 0, overflow: 'auto',
      borderRight: '1px solid var(--border)',
      background: 'var(--surface2)', padding: '8px 0',
    }}>
      {nodes.map(n => {
        const active = n.id === selected
        return (
          <button key={n.id}
            onClick={() => onSelect(n.id)}
            style={{
              width: '100%', textAlign: 'left',
              padding: `5px ${10 + n.depth * 14}px 5px ${10 + n.depth * 14}px`,
              border: 'none', cursor: 'pointer',
              background: active ? 'var(--engram-tint-primary)' : 'transparent',
              color: active ? 'var(--engram-accent-primary)' : 'var(--text2)',
              borderLeft: active ? '2px solid var(--engram-accent-primary)' : '2px solid transparent',
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 12,
              fontWeight: n.depth === 0 ? 600 : 400,
            }}>
            <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {n.label}
            </span>
            {n.badge && (
              <span style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 8,
                background: n.hasError ? 'var(--engram-tint-warning)' : 'var(--surface)',
                color:      n.hasError ? 'var(--engram-accent-warning)' : 'var(--text3)',
                fontFamily: 'monospace', flexShrink: 0,
              }}>{n.badge}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}


function buildOutline(trace: Trace, llmCallsByStage: Record<string, LLMCallRecord[]>): OutlineNode[] {
  const nodes: OutlineNode[] = []

  nodes.push({ id: 'raw', label: 'Raw entry', depth: 0 })
  nodes.push({ id: 'profile_inject', label: 'Profile inject (snapshot)', depth: 0 })

  // Slice section
  if (trace.slice || trace.slice_extraction_health) {
    nodes.push({ id: 'slice', label: 'Slice extraction', depth: 0 })

    // Per-dimension nodes (each has its own LLM call)
    const dimKeys = new Set<string>()
    for (const k of Object.keys(trace.slice || {})) dimKeys.add(k)
    for (const k of Object.keys(trace.slice_extraction_health || {})) dimKeys.add(k)
    for (const stage of Object.keys(llmCallsByStage)) {
      if (stage.startsWith('slice:')) dimKeys.add(stage.replace('slice:', ''))
    }
    for (const key of Array.from(dimKeys).sort()) {
      const calls = llmCallsByStage[`slice:${key}`] || []
      const totalTokens = calls.reduce((s, c) => s + (c.total_tokens || 0), 0)
      const hasError = calls.some(c => c.status !== 'ok')
      nodes.push({
        id:    `slice:${key}`,
        label: key,
        depth: 1,
        badge: totalTokens > 0 ? `${totalTokens}t` : undefined,
        hasError,
      })
    }

    if (trace.profile_diff && Object.keys(trace.profile_diff).length > 0) {
      nodes.push({ id: 'profile_diff', label: 'Profile merge diff', depth: 1 })
    }
  }

  // Backbone section
  const hasBackbone = !!(trace.activation || trace.rough_retrieval || trace.node_extract_internal || trace.node_extract_external || trace.edge_extract || trace.db_diff)
  if (hasBackbone) {
    nodes.push({ id: 'backbone', label: 'Backbone (graph growth)', depth: 0 })

    if (trace.activation) {
      const calls = llmCallsByStage['activation'] || []
      const tokens = calls.reduce((s, c) => s + (c.total_tokens || 0), 0)
      nodes.push({ id: 'activation', label: 'Activation', depth: 1, badge: tokens > 0 ? `${tokens}t` : undefined })
    }

    if (trace.rough_retrieval) {
      nodes.push({ id: 'rough_retrieval', label: `Rough retrieval (${trace.rough_retrieval.length})`, depth: 1 })
    }

    // node_extract_internal / external — per domain.
    // IMPORTANT: backend stage labels are `node_internal:{domain}` and
    // `node_external:{domain}` (no `_extract` infix). Outline IDs must match
    // for llmCallsByStage lookup to succeed.
    const internalDomains = Object.keys(trace.node_extract_internal || {})
    const externalDomains = Object.keys(trace.node_extract_external || {})
    if (internalDomains.length || externalDomains.length || trace.node_extract) {
      nodes.push({ id: 'node_extract', label: 'Node extract', depth: 1 })
      for (const domain of internalDomains.sort()) {
        const calls = llmCallsByStage[`node_internal:${domain}`] || []
        const tokens = calls.reduce((s, c) => s + (c.total_tokens || 0), 0)
        nodes.push({
          id: `node_internal:${domain}`,
          label: `internal · ${domain}`,
          depth: 2,
          badge: tokens > 0 ? `${tokens}t` : undefined,
        })
      }
      for (const domain of externalDomains.sort()) {
        const calls = llmCallsByStage[`node_external:${domain}`] || []
        const tokens = calls.reduce((s, c) => s + (c.total_tokens || 0), 0)
        nodes.push({
          id: `node_external:${domain}`,
          label: `external · ${domain}`,
          depth: 2,
          badge: tokens > 0 ? `${tokens}t` : undefined,
        })
      }
    }

    if (trace.confirmed_nodes) {
      nodes.push({ id: 'confirmed_nodes', label: `Confirmed nodes (${trace.confirmed_nodes.length})`, depth: 1 })
    }
    if (trace.subgraph) {
      nodes.push({ id: 'subgraph', label: 'Local subgraph', depth: 1 })
    }
    if (trace.edge_extract) {
      // edge_extract is a SINGLE global LLM call (stage='edge_extract'), not
      // per-domain. The trace's edge_extract list is flat across all domains.
      const calls = llmCallsByStage['edge_extract'] || []
      const tokens = calls.reduce((s, c) => s + (c.total_tokens || 0), 0)
      nodes.push({
        id: 'edge_extract',
        label: `Edge extract (${trace.edge_extract.length})`,
        depth: 1,
        badge: tokens > 0 ? `${tokens}t` : undefined,
      })
    }
    if (trace.db_diff) {
      nodes.push({ id: 'db_diff', label: 'DB diff', depth: 1 })
    }
  }

  // Summary
  if (trace.llm_summary || trace.metrics) {
    nodes.push({ id: 'summary', label: 'Summary', depth: 0 })
  }

  return nodes
}


// ── Detail (right pane) ──────────────────────────────────────────────────────

function Detail({ trace, raw, stage, llmCallsByStage }: {
  trace: Trace; raw: string; stage: string; llmCallsByStage: Record<string, LLMCallRecord[]>
}) {
  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '14px 18px', minWidth: 0 }}>
      <DetailContent trace={trace} raw={raw} stage={stage} llmCallsByStage={llmCallsByStage} />
    </div>
  )
}

function DetailContent({ trace, raw, stage, llmCallsByStage }: {
  trace: Trace; raw: string; stage: string; llmCallsByStage: Record<string, LLMCallRecord[]>
}) {
  // raw entry view
  if (stage === 'raw') {
    return (
      <Section title="Raw entry">
        <Pre>{raw || '(empty)'}</Pre>
      </Section>
    )
  }

  // profile inject snapshot — pull from any slice LLM call's system_prompt (first one is fine)
  if (stage === 'profile_inject') {
    const sample = (trace.llm_calls || []).find(c => c.stage.startsWith('slice:') && c.system_prompt)
    if (!sample?.system_prompt) {
      return <Section title="Profile inject"><Empty>No LLM call captured profile_summary in this trace (older trace, or LLM not called).</Empty></Section>
    }
    // Try to extract profile_summary section from the system_prompt by simple marker search
    const psMatch = /## Historical (?:user )?profile.*?\n([\s\S]*?)(?:\n##|\Z)/i.exec(sample.system_prompt)
                 || /## Current user profile[\s\S]*?\n([\s\S]*?)(?:\n##|\Z)/i.exec(sample.system_prompt)
    const profileText = psMatch ? psMatch[1].trim() : '(could not auto-extract profile_summary section; full system_prompt below)'
    return (
      <Section title="Profile inject (extracted from slice prompt)" subtitle="What the LLM saw as historical profile context">
        <Pre>{profileText}</Pre>
        <Details summary="Full system_prompt of the slice call (for context)">
          <Pre>{sample.system_prompt}</Pre>
        </Details>
      </Section>
    )
  }

  // Slice section parent
  if (stage === 'slice') {
    return (
      <Section title="Slice extraction" subtitle="LLM 抽取每个维度的特征 + 融合到 profile_dimensions">
        <KV label="Features extracted" value={Object.keys(trace.slice || {}).length} />
        {trace.slice_extraction_health && (
          <Details summary="Per-dimension health metrics">
            <ObjectTable obj={trace.slice_extraction_health} />
          </Details>
        )}
      </Section>
    )
  }

  // Per-dimension slice
  if (stage.startsWith('slice:')) {
    const dim = stage.replace('slice:', '')
    const sliceData = (trace.slice || {})[dim]
    const health = (trace.slice_extraction_health || {})[dim]
    const calls = llmCallsByStage[stage] || []
    return (
      <Section title={`Slice · ${dim}`}>
        <KV label="Confidence (slice_features)" value={sliceData?.confidence ?? '—'} />
        {health && (
          <KV label="Health" value={`null=${health.null_count}/${health.total} · low=${health.low_conf_count} · hedge=${health.midpoint_hedge_count}`} />
        )}
        {sliceData?.content && (
          <Details summary="Extracted content (normalized)" defaultOpen>
            <JsonView data={sliceData.content} />
          </Details>
        )}
        {calls.map((c, i) => <LLMCallView key={i} call={c} />)}
      </Section>
    )
  }

  if (stage === 'profile_diff') {
    return (
      <Section title="Profile merge diff" subtitle="贝叶斯递推 (μ, τ) 在本条 entry 前后的变化">
        {trace.profile_diff
          ? <JsonView data={trace.profile_diff} />
          : <Empty>No profile changes this round.</Empty>}
      </Section>
    )
  }

  // Backbone section parent
  if (stage === 'backbone') {
    return (
      <Section title="Backbone pipeline" subtitle="知识图谱节点与边的生长">
        <KV label="Activated domains" value={Object.keys(trace.activation || {}).length} />
        <KV label="Confirmed nodes" value={trace.confirmed_nodes?.length ?? 0} />
        <KV label="Edges extracted" value={trace.edge_extract?.length ?? 0} />
      </Section>
    )
  }

  if (stage === 'activation') {
    const calls = llmCallsByStage['activation'] || []
    return (
      <Section title="Activation" subtitle="LLM 决定激活哪些 backbone 域 + effort_weight">
        <JsonView data={trace.activation || {}} />
        {calls.map((c, i) => <LLMCallView key={i} call={c} />)}
      </Section>
    )
  }

  if (stage === 'rough_retrieval') {
    return (
      <Section title="Rough retrieval" subtitle="向量搜索召回的存量节点（top-k）">
        {trace.rough_retrieval?.length
          ? <JsonView data={trace.rough_retrieval} />
          : <Empty>No nodes retrieved.</Empty>}
      </Section>
    )
  }

  if (stage === 'node_extract') {
    return (
      <Section title="Node extract" subtitle="LLM 抽取候选节点（内源 + 外源）">
        <KV label="Internal domains" value={Object.keys(trace.node_extract_internal || trace.node_extract || {}).length} />
        <KV label="External domains" value={Object.keys(trace.node_extract_external || {}).length} />
      </Section>
    )
  }

  if (stage.startsWith('node_internal:') || stage.startsWith('node_external:')) {
    const isInternal = stage.startsWith('node_internal:')
    const domain = stage.replace(/^node_(internal|external):/, '')
    const candidates = isInternal
      ? (trace.node_extract_internal || trace.node_extract || {})[domain]
      : (trace.node_extract_external || {})[domain]
    const calls = llmCallsByStage[stage] || []
    return (
      <Section title={`${isInternal ? 'Internal' : 'External'} node extract · ${domain}`}>
        <KV label="Candidates extracted" value={candidates?.length ?? 0} />
        {candidates && candidates.length > 0 && (
          <Details summary="Candidate nodes" defaultOpen><JsonView data={candidates} /></Details>
        )}
        {calls.map((c, i) => <LLMCallView key={i} call={c} />)}
      </Section>
    )
  }

  if (stage === 'confirmed_nodes') {
    return (
      <Section title="Confirmed nodes" subtitle="去重 + origin 升级后的最终节点集">
        {trace.confirmed_nodes?.length
          ? <JsonView data={trace.confirmed_nodes} />
          : <Empty>No confirmed nodes.</Empty>}
      </Section>
    )
  }

  if (stage === 'subgraph') {
    return (
      <Section title="Local subgraph" subtitle="精召回展开的局部图谱">
        {trace.subgraph
          ? <JsonView data={trace.subgraph} />
          : <Empty>Empty subgraph.</Empty>}
      </Section>
    )
  }

  if (stage === 'edge_extract') {
    // edge_extract is a SINGLE global LLM call (chat_json stage='edge_extract')
    // that takes ALL confirmed_nodes and returns a flat list of edges. No
    // per-domain breakdown.
    const calls = llmCallsByStage['edge_extract'] || []
    return (
      <Section title="Edge extract" subtitle="LLM 在所有 confirmed_nodes 间抽取关系边（单次全域调用）">
        <KV label="Edges extracted" value={trace.edge_extract?.length ?? 0} />
        {trace.edge_extract?.length
          ? <Details summary="All edges" defaultOpen><JsonView data={trace.edge_extract} /></Details>
          : <Empty>No edges extracted.</Empty>}
        {calls.map((c, i) => <LLMCallView key={i} call={c} />)}
      </Section>
    )
  }

  if (stage === 'db_diff') {
    return (
      <Section title="DB diff" subtitle="本次 entry 实际写入图谱的增量">
        {trace.db_diff
          ? <JsonView data={trace.db_diff} />
          : <Empty>No DB changes.</Empty>}
      </Section>
    )
  }

  if (stage === 'summary') {
    return (
      <Section title="Summary">
        {trace.llm_summary && <Details summary="LLM call summary" defaultOpen><JsonView data={trace.llm_summary} /></Details>}
        {trace.metrics && <Details summary="Pipeline metrics" defaultOpen><JsonView data={trace.metrics} /></Details>}
        {trace.duration_ms != null && <KV label="Total duration" value={`${trace.duration_ms}ms`} />}
        {trace.finished_at && <KV label="Finished at" value={trace.finished_at} />}
      </Section>
    )
  }

  return <Section title={stage}><Empty>No details available for this stage.</Empty></Section>
}


// ── Reusable atoms ───────────────────────────────────────────────────────────

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 12 }}>{subtitle}</div>}
      {children}
    </div>
  )
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12, padding: '3px 0', color: 'var(--text2)' }}>
      <span style={{ color: 'var(--text3)', minWidth: 160 }}>{label}</span>
      <span style={{ fontFamily: 'monospace' }}>{value}</span>
    </div>
  )
}

function Pre({ children }: { children: React.ReactNode }) {
  return (
    <pre style={{
      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      background: 'var(--surface2)', padding: '8px 10px', borderRadius: 6,
      fontSize: 11, lineHeight: 1.6, color: 'var(--text)',
      maxHeight: 400, overflow: 'auto', margin: '6px 0',
    }}>{children}</pre>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 12, color: 'var(--text3)', fontStyle: 'italic', padding: '6px 0' }}>{children}</div>
}

function Details({ summary, children, defaultOpen }: { summary: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} style={{ margin: '8px 0' }}>
      <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--text2)', userSelect: 'none', padding: '2px 0' }}>
        {summary}
      </summary>
      <div style={{ paddingLeft: 12, marginTop: 4 }}>{children}</div>
    </details>
  )
}

function JsonView({ data }: { data: unknown }) {
  return <Pre>{JSON.stringify(data, null, 2)}</Pre>
}

function ObjectTable({ obj }: { obj: Record<string, Record<string, unknown> | object> }) {
  const data = obj as Record<string, Record<string, unknown>>
  const keys = Object.keys(data)
  if (keys.length === 0) return <Empty>(empty)</Empty>
  const cols = Array.from(new Set(keys.flatMap(k => Object.keys(data[k] || {}))))
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'monospace' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          <th style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)' }}>key</th>
          {cols.map(c => <th key={c} style={{ textAlign: 'right', padding: '4px 8px', color: 'var(--text3)' }}>{c}</th>)}
        </tr>
      </thead>
      <tbody>
        {keys.map(k => (
          <tr key={k} style={{ borderBottom: '1px solid var(--border)' }}>
            <td style={{ padding: '4px 8px', color: 'var(--text2)' }}>{k}</td>
            {cols.map(c => (
              <td key={c} style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text)' }}>
                {String(data[k]?.[c] ?? '—')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}


// ── LLM Call view (the most important debug primitive) ──────────────────────

function LLMCallView({ call }: { call: LLMCallRecord }) {
  const { t } = useI18n()
  void t  // i18n hook reserved for future status labels
  const isError = call.status !== 'ok'
  return (
    <div style={{
      marginTop: 12, padding: '10px 12px',
      background: 'var(--surface2)',
      border: `1px solid ${isError ? 'var(--engram-accent-warning)' : 'var(--border)'}`,
      borderRadius: 6,
    }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8, fontSize: 11 }}>
        <span style={{ fontWeight: 700, color: 'var(--text)' }}>LLM Call</span>
        <span style={{ color: 'var(--text3)' }}>{call.model}</span>
        <span style={{
          padding: '1px 8px', borderRadius: 8,
          background: isError ? 'var(--engram-tint-warning)' : 'var(--engram-tint-primary)',
          color:      isError ? 'var(--engram-accent-warning)' : 'var(--engram-accent-primary)',
          fontFamily: 'monospace',
        }}>{call.status}</span>
        <span style={{ flex: 1 }} />
        <span style={{ color: 'var(--text3)', fontFamily: 'monospace' }}>
          {call.total_tokens || call.prompt_tokens + call.completion_tokens || 0}t · {call.duration_ms}ms
        </span>
      </div>

      {call.error && (
        <div style={{ fontSize: 11, color: 'var(--engram-accent-warning)', marginBottom: 6 }}>
          error: {call.error}
        </div>
      )}

      {(call.prompt_tokens > 0 || call.completion_tokens > 0) && (
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6, fontFamily: 'monospace' }}>
          prompt: {call.prompt_tokens}t · completion: {call.completion_tokens}t · prompt_chars: {call.prompt_chars}
        </div>
      )}

      <Details summary="System prompt (substituted)" defaultOpen={false}>
        <Pre>{call.system_prompt || '(not captured — older trace)'}</Pre>
      </Details>
      {call.user_prompt && (
        <Details summary="User prompt">
          <Pre>{call.user_prompt}</Pre>
        </Details>
      )}
      <Details summary="Response (raw)" defaultOpen={false}>
        <Pre>{call.response || '(not captured — older trace)'}</Pre>
      </Details>
    </div>
  )
}
